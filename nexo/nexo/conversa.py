"""Conversa com o NEXO: memória da conversa + ferramentas + Claude, Gemini, DeepSeek e Ollama.

O histórico é guardado em formato neutro (só os textos), então cada turno pode ser
atendido por qualquer uma das IAs. Dentro do turno, cada IA usa as ferramentas no
seu próprio formato. Se uma IA falhar antes de executar qualquer ferramenta, a outra
assume; depois que algo foi executado, não repete (para não fazer a ação duas vezes).
"""
import json
import re
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable

from . import agente, atalhos, cerebro, config, ferramentas, ia

MAX_PASSOS = 8
# No modo rápido, as duas primeiras IAs da ordem começam juntas e o turno fica com a que responder
# (ou pedir uma ferramenta) primeiro. Corta as esperas longas quando uma delas está lenta ou sem cota.
CORRIDA = {"rapido": True, "profundo": False}
# Só correm IAs baratas e rápidas: o Claude fica de reserva, para não pagar dois turnos a cada pergunta.
CORREDORAS = ("gemini", "deepseek")
# Raciocínio do Gemini por modo: mínimo no rápido (1,2 s por chamada contra 3,7 s no "low"), muito no profundo.
PENSAMENTO_GEMINI = {"rapido": "minimal", "profundo": "high"}
INSTRUCOES = (
    f"\n\nVocê está conversando com o usuário agora; chame-o de {config.TRATAMENTO}. Responda curto, "
    "como se fosse falado. Use as ferramentas quando precisar: para qualquer fato sobre o usuário, os projetos ou o "
    "passado, consulte buscar_cerebro antes de responder. Quando ele pedir para lembrar algo, "
    "use guardar. Se ele mandar um link do GitHub, aprenda com aprender_do_link; perguntas sobre o que "
    "você já aprendeu de repositórios e pastas vão para consultar_conhecimento. Se uma busca não trouxer "
    "a resposta, use consultar_myhub com a pergunta completa antes de dizer que não achou. Não invente "
    "resultados de ferramentas."
)
# Respostas de quem não achou o que foi pedido: aí o Jarvis tenta o MyHub sozinho (ver _reforco_myhub).
NAO_ACHOU = re.compile(
    r"n[aã]o (?:encontrei|achei|localizei|consegui (?:encontrar|achar|acessar|confirmar|obter|localizar)"
    r"|tenho (?:acesso|essa informa|como (?:saber|confirmar|acessar)|informa[cç])"
    r"|(?:est[aã]o|est[aá]|ficou|foram|foi) (?:dispon[ií]ve|consolidad|confirmad)"
    r"|sei (?:dizer|informar|responder))", re.I)


@dataclass
class Turno:
    texto: str
    provedor: str
    acoes: list[str] = field(default_factory=list)


class FalhaNoTurno(Exception):
    """A IA falhou depois de já ter executado ferramentas: não dá para tentar a outra."""


class _Perdeu(Exception):
    """Na corrida, a outra IA chegou primeiro: esta para sem executar nada."""


class Conversa:
    def __init__(self, modo: str = "rapido", privado: bool = False,
                 confirmar: Callable[[str], bool] | None = None,
                 ferramentas_disponiveis: dict | None = None,
                 ao_evento: Callable[[str, dict], None] | None = None):
        self.modo = modo
        # A interface recebe aqui o que o NEXO está fazendo (ex.: quais notas consultou).
        self.ao_evento = ao_evento or (lambda tipo, dados: None)
        self.privado = privado
        # Sem interface para perguntar, ações que pedem confirmação são negadas.
        self.confirmar = confirmar or (lambda pergunta: False)
        self.ferramentas = ferramentas_disponiveis if ferramentas_disponiveis is not None else ferramentas.carregar()
        self.historico: list[tuple[str, str]] = []  # ("usuario" | "nexo", texto)
        self._acoes: list[str] = []
        self._dono: str | None = None        # IA que ficou com o turno atual
        self._trava_dono = threading.Lock()

    # ---------- turno ----------

    def enviar(self, mensagem: str) -> Turno:
        rapido = atalhos.tentar(mensagem, self.ferramentas)
        if rapido:
            texto, ferramenta = rapido
            self.ao_evento("acao", {"descricao": f"{ferramenta}()", "erro": False, "notas": []})
            self.historico += [("usuario", mensagem), ("nexo", texto)]
            return Turno(texto, "local", [f"{ferramenta}()"])
        sistema = agente._sistema() + INSTRUCOES
        ordem = ia.ORDEM.get(self.modo, ia.ORDEM["profundo"])
        # O Ollama local não usa ferramentas nem consulta o cérebro: na conversa ele é só a reserva
        # para quando as IAs da nuvem falharem (sem internet, sem cota).
        ordem = [n for n in ordem if n != "ollama"] + [n for n in ordem if n == "ollama"]
        candidatas = [n for n in ordem if n in ia.disponiveis()]
        erros: list[str] = []
        self._acoes = []
        par = [n for n in candidatas[:2] if n in CORREDORAS]
        if CORRIDA.get(self.modo) and len(par) == 2:
            turno = self._corrida(par, sistema, mensagem, erros)
            if turno:
                return self._reforco_myhub(mensagem, turno)
            candidatas = candidatas[2:]
        for nome in candidatas:
            self._dono, self._acoes = None, []
            turno = self._tentar(nome, sistema, mensagem, erros)
            if turno:
                return self._reforco_myhub(mensagem, turno)
        if not erros:
            raise ia.SemIA("Nenhuma chave de IA configurada. Preencha o .env.")
        raise ia.SemIA("Todas as IAs falharam:\n" + "\n".join(erros))

    def _reforco_myhub(self, mensagem: str, turno: Turno) -> Turno:
        """Se a resposta foi "não achei", pergunta às IAs do MyHub (conta salva) e responde com o que vier."""
        if "consultar_myhub" not in self.ferramentas or not NAO_ACHOU.search(turno.texto):
            return turno
        if any(a.startswith("consultar_myhub") for a in turno.acoes):
            return turno   # a IA já tentou o MyHub neste turno
        from . import myhub
        if not myhub.logado():
            return turno
        self._acoes = list(turno.acoes)
        self.ao_evento("pensando", {"provedor": "myhub"})
        resultado, erro = self._executar("consultar_myhub", {"pergunta": mensagem})
        if erro or not resultado.startswith("Resposta do"):
            return Turno(turno.texto, turno.provedor, list(self._acoes))
        try:
            resumo = ia.perguntar(
                f"Pergunta do usuário: {mensagem}\n\n{resultado}\n\n"
                f"Responda ao usuário com base só nesse conteúdo, em português, curto, como se fosse falado, "
                f"chamando-o de {config.TRATAMENTO}. Diga que encontrou pelo MyHub.",
                modo="rapido").texto.strip()
        except Exception:
            resumo = resultado.split("\n", 1)[-1][:1500]
        self.historico[-1] = ("nexo", resumo)
        return Turno(resumo, f"{turno.provedor} + myhub", list(self._acoes))

    def _tentar(self, nome: str, sistema: str, mensagem: str, erros: list[str]) -> Turno | None:
        """Uma IA atende o turno. None quando ela falhou antes de agir (a próxima pode tentar)."""
        self.ao_evento("pensando", {"provedor": nome})
        laco = {"claude": self._laco_claude, "gemini": self._laco_gemini,
                "deepseek": self._laco_deepseek}.get(nome, self._laco_ollama)
        try:
            texto = laco(sistema, mensagem, nome)
        except _Perdeu:
            return None
        except FalhaNoTurno as e:
            texto = f"Desculpe, {config.TRATAMENTO}, algo falhou no meio da tarefa: {e}"
        except Exception as e:
            if self._dono not in (None, nome):
                return None   # perdeu a corrida e depois falhou: o erro não importa
            if self._acoes:
                texto = f"Desculpe, {config.TRATAMENTO}, algo falhou no meio da tarefa: {e}"
            else:
                ia.chave_recusada(nome, e)
                erros.append(f"{nome}: {type(e).__name__}: {e}")
                return None
        self.historico += [("usuario", mensagem), ("nexo", texto)]
        return Turno(texto, nome, list(self._acoes))

    def _corrida(self, nomes: list[str], sistema: str, mensagem: str, erros: list[str]) -> Turno | None:
        """As duas IAs começam juntas; fica com o turno a primeira que responder ou pedir uma ferramenta."""
        self._dono = None
        pool = ThreadPoolExecutor(len(nomes), thread_name_prefix="nexo-corrida")
        pendentes = {pool.submit(self._tentar, n, sistema, mensagem, erros) for n in nomes}
        try:
            while pendentes:
                prontos, pendentes = wait(pendentes, return_when=FIRST_COMPLETED)
                for f in prontos:
                    if f.result():
                        return f.result()
            return None
        finally:
            pool.shutdown(wait=False)   # a perdedora termina sozinha e não executa nada

    def _vez(self, nome: str) -> None:
        """Antes de agir ou responder: garante o turno para esta IA (ou desiste, se a outra já o tem)."""
        with self._trava_dono:
            if self._dono is None:
                self._dono = nome
            elif self._dono != nome:
                raise _Perdeu()

    def _executar(self, nome: str, argumentos: dict) -> tuple[str, bool]:
        f = self.ferramentas.get(nome)
        if not f:
            return f"Ferramenta {nome} não existe.", True
        def curto(v) -> str:
            texto = repr(v)
            return texto if len(texto) <= 60 else texto[:57] + "…'"
        descricao = f"{nome}({', '.join(f'{k}={curto(v)}' for k, v in argumentos.items())})"
        if f.confirmar and not self.confirmar(f"Posso executar {descricao}?"):
            self._acoes.append(f"{descricao}: negado")
            return "O usuário não autorizou esta ação. Não tente de novo sem ele pedir.", False
        try:
            resultado, erro = str(f.executar(**argumentos)), False
            self._acoes.append(descricao)
        except Exception as e:
            resultado, erro = f"Erro ao executar {nome}: {type(e).__name__}: {e}", True
            self._acoes.append(f"{descricao}: erro")
        notas = cerebro.extrair_links(resultado)
        if nome == "ler_nota" and not erro:
            notas.add(str(argumentos.get("titulo", "")).strip("[]"))
        self.ao_evento("acao", {"descricao": descricao, "erro": erro, "notas": sorted(n for n in notas if n)})
        return resultado, erro

    # ---------- Claude ----------

    def _laco_claude(self, sistema: str, mensagem: str, nome: str = "claude") -> str:
        msgs = [{"role": "user" if p == "usuario" else "assistant", "content": t} for p, t in self.historico]
        msgs.append({"role": "user", "content": mensagem})
        tools = [{"name": f.nome, "description": f.descricao, "input_schema": f.esquema}
                 for f in self.ferramentas.values()]
        # Ferramentas + instruções são iguais em todos os passos do turno: com o cache do prompt,
        # só o primeiro passo paga por elas e os seguintes respondem mais rápido.
        sistema_cache = [{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}]
        for _ in range(MAX_PASSOS):
            r = ia.cliente("claude").beta.messages.create(
                model=config.CLAUDE_MODELO, max_tokens=16000, system=sistema_cache, messages=msgs,
                tools=tools, output_config={"effort": ia.ESFORCO.get(self.modo, "medium")},
                **ia.CLAUDE_FALLBACK)
            if r.stop_reason == "refusal":
                raise RuntimeError("o Claude recusou o pedido")
            self._vez(nome)
            if r.stop_reason != "tool_use":
                return "".join(b.text for b in r.content if b.type == "text").strip()
            msgs.append({"role": "assistant", "content": r.content})
            resultados = []
            for b in r.content:
                if b.type == "tool_use":
                    texto, erro = self._executar(b.name, dict(b.input or {}))
                    resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                       "content": texto, "is_error": erro})
            msgs.append({"role": "user", "content": resultados})
        raise FalhaNoTurno("precisei de passos demais")

    # ---------- Gemini ----------

    def _laco_gemini(self, sistema: str, mensagem: str, nome: str = "gemini") -> str:
        from google.genai import types

        conteudo = [types.Content(role="user" if p == "usuario" else "model", parts=[types.Part(text=t)])
                    for p, t in self.historico]
        conteudo.append(types.Content(role="user", parts=[types.Part(text=mensagem)]))
        declaracoes = [
            types.FunctionDeclaration(name=f.nome, description=f.descricao,
                                      parameters_json_schema=f.esquema if f.parametros else None)
            for f in self.ferramentas.values()
        ]
        ajustes = types.GenerateContentConfig(
            system_instruction=sistema,
            tools=[types.Tool(function_declarations=declaracoes)] if declaracoes else None,
            thinking_config=types.ThinkingConfig(thinking_level=PENSAMENTO_GEMINI.get(self.modo, "low")),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        for _ in range(MAX_PASSOS):
            r = ia.gerar_gemini(conteudo, ajustes)
            chamadas = r.function_calls or []
            self._vez(nome)
            if not chamadas:
                return (r.text or "").strip()
            conteudo.append(r.candidates[0].content)
            partes = []
            for c in chamadas:
                texto, erro = self._executar(c.name, dict(c.args or {}))
                partes.append(types.Part.from_function_response(
                    name=c.name, response={"erro" if erro else "resultado": texto}))
            conteudo.append(types.Content(role="user", parts=partes))
        raise FalhaNoTurno("precisei de passos demais")

    # ---------- DeepSeek ----------

    def _laco_deepseek(self, sistema: str, mensagem: str, nome: str = "deepseek") -> str:
        """DeepSeek com ferramentas, no formato da OpenAI (tools / tool_calls)."""
        msgs = [{"role": "system", "content": sistema}]
        msgs += [{"role": "user" if p == "usuario" else "assistant", "content": t} for p, t in self.historico]
        msgs.append({"role": "user", "content": mensagem})
        tools = [{"type": "function", "function": {"name": f.nome, "description": f.descricao, "parameters": f.esquema}}
                 for f in self.ferramentas.values()]
        for _ in range(MAX_PASSOS):
            corpo = {"messages": msgs, "max_tokens": 2048, "temperature": 0.6}
            if tools:
                corpo["tools"] = tools
            escolha = (ia.chamar_deepseek(corpo, timeout=45.0).get("choices") or [{}])[0]
            msg = escolha.get("message") or {}
            chamadas = msg.get("tool_calls") or []
            self._vez(nome)
            if not chamadas:
                texto = (msg.get("content") or "").strip()
                if not texto:
                    raise RuntimeError("DeepSeek devolveu resposta vazia")
                return texto
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": chamadas})
            for c in chamadas:
                funcao = c.get("function") or {}
                try:
                    argumentos = json.loads(funcao.get("arguments") or "{}")
                except ValueError:
                    argumentos = {}
                texto, erro = self._executar(funcao.get("name", ""), argumentos if isinstance(argumentos, dict) else {})
                msgs.append({"role": "tool", "tool_call_id": c.get("id", ""),
                             "content": f"ERRO: {texto}" if erro else texto})
        raise FalhaNoTurno("precisei de passos demais")

    # ---------- Ollama ----------

    def _laco_ollama(self, sistema: str, mensagem: str, nome: str = "ollama") -> str:
        historico = "\n".join(f"{p}: {t}" for p, t in self.historico[-6:])
        prompt = (
            "Conversa recente (se houver):\n"
            f"{historico}\n\n"
            "Mensagem atual do usuário:\n"
            f"{mensagem}"
        )
        texto = ia._ollama(prompt, sistema, None, self.modo)
        self._vez(nome)
        return texto

    # ---------- fim ----------

    def encerrar(self) -> None:
        """Resume a conversa no diário (a não ser no modo privado)."""
        if self.privado or not self.historico:
            return
        from . import sessao
        texto = "\n\n".join(f"[{p}] {t}" for p, t in self.historico)
        sessao.registrar_resumo(texto, "conversa", len(self.historico))
