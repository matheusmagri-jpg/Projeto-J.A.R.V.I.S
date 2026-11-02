"""Claude, Gemini, DeepSeek, NVIDIA e Ollama juntos.

Modos:
- rapido:   Gemini primeiro (barato e veloz); Claude se o Gemini falhar.
- profundo: Claude primeiro (raciocínio, organizar o cérebro); Gemini se o Claude falhar.
- dupla:    os dois respondem em paralelo e o Claude junta o melhor de cada um.

O Ollama local é a última reserva (sem internet, sem cota). Para voltar a tentá-lo primeiro,
NEXO_OLLAMA_PRIMEIRO=1. Com o modo privado ligado (dados/privado.json), só o Ollama responde e
nenhum texto sai para as IAs da nuvem.

As chaves ficam no .env e nunca entram no texto enviado para as IAs.
"""
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from urllib import error, request

from . import config

NUVEM = {
    "rapido": ["gemini", "deepseek", "nvidia", "claude"],
    "profundo": ["claude", "gemini", "nvidia", "deepseek"],
}


def montar_ordem(ollama_primeiro: bool) -> dict[str, list[str]]:
    """Nesta máquina o Ollama leva 37 s (frio) contra 6 s do Gemini e ocupa 2,5 GB de 8 GB de RAM."""
    return {modo: ["ollama", *ias] if ollama_primeiro else [*ias, "ollama"] for modo, ias in NUVEM.items()}


ORDEM = montar_ordem(config.OLLAMA_PRIMEIRO)
ESFORCO = {"rapido": "low", "profundo": "high", "dupla": "medium"}
TTL_CACHE_S = 12.0
MAX_CACHE = 128


class SemIA(RuntimeError):
    """Nenhuma IA disponível ou todas falharam."""


class ModoPrivado(SemIA):
    """O modo privado está ligado: o pedido iria para uma IA da nuvem e foi barrado."""


# ---------- modo privado ----------
# Fica num arquivo, não na memória: a vigia (bom-dia, resumos) pode rodar em outro processo.

def _arquivo_privado():
    return config.DADOS / "privado.json"


def privado_ativo() -> bool:
    try:
        return json.loads(_arquivo_privado().read_text(encoding="utf-8")).get("privado") is True
    except (OSError, ValueError, AttributeError):
        return False


def definir_privado(ligado: bool) -> None:
    arquivo = _arquivo_privado()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps({"privado": bool(ligado)}), encoding="utf-8")
    temporario.replace(arquivo)


def barrar_nuvem(nome: str) -> None:
    """Toda chamada a uma IA da nuvem passa por aqui antes de sair do PC."""
    if privado_ativo():
        raise ModoPrivado(f"Modo privado ligado: nada foi enviado para {nome}.")


@dataclass
class Resposta:
    texto: str
    provedor: str
    dados: dict | list | None = None  # preenchido quando um esquema JSON foi pedido


# ---------- provedores ----------

_clientes: dict = {}
_cache_respostas: dict[tuple, tuple[float, Resposta]] = {}
_preaquecendo = False
_preaquecido_em = 0.0


def cliente(nome: str):
    """Cliente da IA, criado uma vez só. As chaves vêm do ambiente (.env)."""
    barrar_nuvem(nome)
    if nome not in _clientes:
        # Limites de tempo: se uma IA travar, o NEXO passa para a outra em vez de esperar.
        if nome == "claude":
            import anthropic
            _clientes[nome] = anthropic.Anthropic(timeout=120.0, max_retries=1)
        elif nome in ("gemini", "gemini-reserva", "gemini-agente"):
            from google import genai
            from google.genai import types
            acesso = {"gemini": {},  # lê GEMINI_API_KEY
                      "gemini-reserva": {"api_key": os.environ.get("GEMINI_API_KEY_RESERVA")},
                      "gemini-agente": {"vertexai": True, "api_key": os.environ.get("GEMINI_AGENT_PLATFORM_KEY")}}[nome]
            _clientes[nome] = genai.Client(http_options=types.HttpOptions(timeout=60_000), **acesso)
        else:
            raise ValueError(f"cliente desconhecido: {nome}")
    return _clientes[nome]


# Se um filtro de segurança do Claude recusar, a própria API tenta outro modelo Claude.
CLAUDE_FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


def _claude(prompt: str, sistema: str | None, esquema: dict | None, modo: str) -> str:
    output_config: dict = {"effort": ESFORCO.get(modo, "medium")}
    if esquema:
        output_config["format"] = {"type": "json_schema", "schema": esquema}
    pedido = dict(
        model=config.CLAUDE_MODELO,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        output_config=output_config,
        **CLAUDE_FALLBACK,
    )
    if sistema:
        pedido["system"] = sistema
    resposta = cliente("claude").beta.messages.create(**pedido)
    if resposta.stop_reason == "refusal":
        raise RuntimeError("o Claude recusou o pedido")
    return "".join(b.text for b in resposta.content if b.type == "text").strip()


# O plano gratuito do Gemini oscila: o mesmo pedido leva 1 s num momento e 30 s no outro.
# Se um modelo não responder em HEDGE_S, o próximo da lista é disparado em paralelo e vale o primeiro
# que responder; modelo sem cota (429) é pulado por ESGOTADO_S.
HEDGE_S = float(os.environ.get("NEXO_GEMINI_HEDGE", "4"))
ESGOTADO_S = 300.0
HEDGE_PROFUNDO_S = 45.0   # o modelo forte pensa mais: disputar cedo daria o turno sempre ao mais fraco
_esgotados: dict[tuple[str, str], float] = {}


def contas_gemini() -> list[str]:
    """Contas do Gemini com chave, na ordem de uso. Cada conta tem a própria cota."""
    contas = ["gemini"] if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") else []
    if os.environ.get("GEMINI_AGENT_PLATFORM_KEY"):
        contas.append("gemini-agente")
    if os.environ.get("GEMINI_API_KEY_RESERVA"):
        contas.append("gemini-reserva")
    return contas


def modelos_gemini(modo: str) -> list[str]:
    if modo != "profundo":
        return list(config.GEMINI_MODELOS)
    return [config.GEMINI_MODELO_PROFUNDO] + [m for m in config.GEMINI_MODELOS if m != config.GEMINI_MODELO_PROFUNDO]


def gerar_gemini(contents, ajustes, modelos: list[str] | None = None, hedge: float | None = None):
    """Chama o Gemini; se um modelo bater no limite de uso (429), estiver sobrecarregado ou fora do
    ar (5xx), ou demorar mais que HEDGE_S, a próxima opção entra na disputa.

    Cada conta tem a própria cota por modelo: o mesmo modelo é tentado em todas as contas antes de
    cair para um modelo mais fraco.
    """
    from concurrent.futures import FIRST_COMPLETED, wait
    from google.genai import errors

    lista = list(modelos or config.GEMINI_MODELOS)
    agora = monotonic()
    opcoes = [(conta, m) for m in lista for conta in contas_gemini() or ["gemini"]]
    ativos = [o for o in opcoes if _esgotados.get(o, 0) <= agora] or opcoes
    espera = HEDGE_S if hedge is None else hedge

    def chamar(opcao):
        return cliente(opcao[0]).models.generate_content(model=opcao[1], contents=contents, config=ajustes)

    pool = ThreadPoolExecutor(len(ativos), thread_name_prefix="nexo-gemini")
    pendentes: dict = {}
    proximo, ultimo = 0, None
    try:
        while True:
            if proximo < len(ativos) and not pendentes:
                pendentes[pool.submit(chamar, ativos[proximo])] = ativos[proximo]
                proximo += 1
            feitos, _ = wait(pendentes, timeout=espera if proximo < len(ativos) else None,
                             return_when=FIRST_COMPLETED)
            if not feitos:   # demorou: dispara o próximo sem desistir do que já está rodando
                pendentes[pool.submit(chamar, ativos[proximo])] = ativos[proximo]
                proximo += 1
                continue
            for futuro in feitos:
                opcao = pendentes.pop(futuro)
                try:
                    return futuro.result()
                except errors.ServerError as e:
                    ultimo = e
                except errors.ClientError as e:
                    # 403: a chave não vale para este serviço; 404: o modelo não existe nele. Outra conta pode atender.
                    if e.code != 429 and not (e.code in (403, 404) and len(opcoes) > len(lista)):
                        raise
                    _esgotados[opcao] = monotonic() + ESGOTADO_S
                    ultimo = e
            if not pendentes and proximo >= len(ativos):
                raise ultimo
    finally:
        pool.shutdown(wait=False)


def _gemini(prompt: str, sistema: str | None, esquema: dict | None, modo: str) -> str:
    from google.genai import types

    ajustes = types.GenerateContentConfig(system_instruction=sistema)
    if esquema:
        ajustes.response_mime_type = "application/json"
        ajustes.response_json_schema = esquema
    resposta = gerar_gemini(prompt, ajustes, modelos_gemini(modo), HEDGE_PROFUNDO_S if modo == "profundo" else None)
    return (resposta.text or "").strip()


def _chamar_compativel(nome: str, base_url: str, api_key: str, corpo: dict, timeout: float) -> dict:
    """POST em /chat/completions (formato da OpenAI) e devolve o JSON da resposta."""
    barrar_nuvem(nome)
    req = request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps({"stream": False, **corpo}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as r:
            bruto = r.read().decode("utf-8")
    except error.HTTPError as e:
        detalhe = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{nome} HTTP {e.code}: {detalhe[:500]}") from e
    except error.URLError as e:
        raise RuntimeError(f"Não consegui conectar ao {nome} em {base_url}: {e.reason}") from e
    try:
        return json.loads(bruto)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{nome} devolveu JSON inválido.") from e


def chamar_deepseek(corpo: dict, timeout: float = 60.0) -> dict:
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY ausente")
    return _chamar_compativel("DeepSeek", config.DEEPSEEK_BASE_URL, api_key,
                              {"model": config.DEEPSEEK_MODELO, **corpo}, timeout)


def chamar_nvidia(corpo: dict, modo: str = "rapido", timeout: float = 60.0) -> dict:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY ausente")
    modelo = config.NVIDIA_MODELOS.get(modo, config.NVIDIA_MODELOS["rapido"])
    return _chamar_compativel("NVIDIA", config.NVIDIA_BASE_URL, api_key, {"model": modelo, **corpo}, timeout)


def sem_raciocinio(texto: str) -> str:
    """Alguns modelos abertos escrevem o raciocínio em <think> dentro da resposta."""
    return re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()


def _texto_compativel(prompt: str, sistema: str | None, esquema: dict | None, chamar, nome: str) -> str:
    if esquema:
        prompt = (
            "Responda somente em JSON válido, sem markdown nem texto extra, "
            f"seguindo exatamente este schema: {json.dumps(esquema, ensure_ascii=False)}\n\n"
            f"Pergunta:\n{prompt}"
        )

    corpo = {
        "messages": [
            {"role": "system", "content": sistema or "Responda em português do Brasil."},
            {"role": "user", "content": prompt},
        ],
    }
    if esquema:
        corpo["response_format"] = {"type": "json_object"}
    payload = chamar(corpo)

    texto = ""
    for escolha in payload.get("choices", []):
        msg = escolha.get("message") or {}
        conteudo = msg.get("content")
        if isinstance(conteudo, str) and conteudo.strip():
            texto = sem_raciocinio(conteudo)
            break
        if isinstance(conteudo, list):
            partes = []
            for parte in conteudo:
                if isinstance(parte, dict):
                    text = parte.get("text")
                    if isinstance(text, str):
                        partes.append(text)
            if partes:
                texto = sem_raciocinio("".join(partes))
                break
    if not texto:
        raise RuntimeError(f"{nome} devolveu resposta vazia.")
    return texto


def _deepseek(prompt: str, sistema: str | None, esquema: dict | None, modo: str) -> str:
    return _texto_compativel(prompt, sistema, esquema, chamar_deepseek, "DeepSeek")


def _nvidia(prompt: str, sistema: str | None, esquema: dict | None, modo: str) -> str:
    return _texto_compativel(prompt, sistema, esquema, lambda corpo: chamar_nvidia(corpo, modo), "NVIDIA")


def _ollama(prompt: str, sistema: str | None, esquema: dict | None, modo: str) -> str:
    if esquema:
        instrucao_json = (
            "Responda somente em JSON válido, sem markdown nem texto extra, "
            "seguindo exatamente este schema: "
            f"{json.dumps(esquema, ensure_ascii=False)}"
        )
        sistema = f"{sistema}\n\n{instrucao_json}" if sistema else instrucao_json

    corpo = {
        "model": config.OLLAMA_MODELO,
        "stream": False,
        "messages": [
            {"role": "system", "content": sistema or "Responda em português do Brasil."},
            {"role": "user", "content": prompt},
        ],
    }
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{config.OLLAMA_URL}/api/chat",
        data=dados,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=config.OLLAMA_TIMEOUT) as r:
            bruto = r.read().decode("utf-8")
    except error.HTTPError as e:
        detalhe = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {e.code}: {detalhe[:500]}") from e
    except error.URLError as e:
        raise RuntimeError(f"Não consegui conectar ao Ollama em {config.OLLAMA_URL}: {e.reason}") from e

    try:
        payload = json.loads(bruto)
    except json.JSONDecodeError as e:
        raise RuntimeError("Ollama devolveu JSON inválido.") from e

    texto = (payload.get("message") or {}).get("content", "").strip()
    if not texto:
        raise RuntimeError("Ollama devolveu resposta vazia.")
    return texto


PROVEDORES = {
    "claude": (_claude, config.tem_claude),
    "gemini": (_gemini, config.tem_gemini),
    "deepseek": (_deepseek, config.tem_deepseek),
    "nvidia": (_nvidia, config.tem_nvidia),
    "ollama": (_ollama, config.tem_ollama),
}


# IAs com chave recusada (401/403) ou sem saldo nesta execução: tentar de novo a cada pergunta só atrasa.
_recusadas: dict[str, str] = {}


def disponiveis() -> list[str]:
    privado = privado_ativo()
    return [nome for nome, (_, tem) in PROVEDORES.items()
            if tem() and nome not in _recusadas and (nome == "ollama" or not privado)]


def chave_recusada(nome: str, erro: Exception) -> bool:
    """Se o erro é de chave inválida ou falta de saldo, tira a IA da lista até o Jarvis ser reiniciado."""
    texto = str(erro)
    if any(s in texto for s in ("HTTP 401", "HTTP 402", "HTTP 403", "authentication_error", "invalid x-api-key",
                                "API_KEY_INVALID", "credit balance")):
        _recusadas[nome] = texto[:200]
        return True
    return False


tem_deepseek = config.tem_deepseek


def _chave_cache(prompt: str, sistema: str | None, modo: str, ordem: list[str]) -> tuple:
    return (modo, tuple(ordem), sistema or "", prompt)


def _cache_get(chave: tuple) -> Resposta | None:
    item = _cache_respostas.get(chave)
    if not item:
        return None
    salvo_em, resposta = item
    if monotonic() - salvo_em > TTL_CACHE_S:
        _cache_respostas.pop(chave, None)
        return None
    return Resposta(resposta.texto, resposta.provedor, resposta.dados)


def _cache_set(chave: tuple, resposta: Resposta) -> None:
    _cache_respostas[chave] = (monotonic(), Resposta(resposta.texto, resposta.provedor, resposta.dados))
    if len(_cache_respostas) <= MAX_CACHE:
        return
    excesso = len(_cache_respostas) - MAX_CACHE
    for k in list(_cache_respostas)[:excesso]:
        _cache_respostas.pop(k, None)


def _extrair_json(texto: str):
    bruto = texto.strip()
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        if "```" not in bruto:
            raise
    linhas = bruto.splitlines()
    if len(linhas) < 3 or not linhas[0].startswith("```") or not linhas[-1].startswith("```"):
        raise
    return json.loads("\n".join(linhas[1:-1]).strip())


def _ping_ollama() -> None:
    req = request.Request(f"{config.OLLAMA_URL}/api/tags", method="GET")
    with request.urlopen(req, timeout=2.0) as r:
        r.read()


def _preaquecer_worker() -> None:
    global _preaquecendo, _preaquecido_em
    try:
        if privado_ativo():
            return
        # Só a primeira IA do modo rápido: importar o SDK do Claude junto leva dezenas de segundos com a
        # máquina cheia e atrasa o do Gemini. O Claude carrega quando for chamado de verdade.
        if config.tem_gemini():
            cliente("gemini")
        elif config.tem_claude():
            cliente("claude")
        if config.tem_ollama():
            try:
                _ping_ollama()
            except Exception:
                pass
        _preaquecido_em = monotonic()
    finally:
        _preaquecendo = False


def preaquecer_async(forcar: bool = False) -> bool:
    """Inicia pre-aquecimento em background. Retorna True quando um worker foi iniciado."""
    global _preaquecendo
    if not config.IA_PREAQUECER:
        return False
    if _preaquecendo:
        return False
    if not forcar and _preaquecido_em and monotonic() - _preaquecido_em < 300:
        return False
    _preaquecendo = True
    threading.Thread(target=_preaquecer_worker, daemon=True, name="nexo-preaquecer-ia").start()
    return True


# ---------- roteamento ----------

def _uma(prompt, sistema, esquema, modo, ordem) -> Resposta:
    privado = privado_ativo()
    if privado:
        ordem = ["ollama"]
    chave_cache = None
    if esquema is None and modo in ORDEM:
        chave_cache = _chave_cache(prompt, sistema, modo, ordem)
        em_cache = _cache_get(chave_cache)
        if em_cache:
            return em_cache

    erros = []
    ativos = []
    for nome in ordem:
        entrada = PROVEDORES.get(nome)
        if not entrada:
            continue
        chamar, tem = entrada
        if tem() and nome not in _recusadas:
            ativos.append((nome, chamar))

    for nome, chamar in ativos:
        try:
            texto = chamar(prompt, sistema, esquema, modo)
            if not texto:
                raise RuntimeError("resposta vazia")
            resposta = Resposta(texto, nome, _extrair_json(texto) if esquema else None)
            if chave_cache is not None:
                _cache_set(chave_cache, resposta)
            return resposta
        except Exception as e:  # tenta a próxima IA
            chave_recusada(nome, e)
            erros.append(f"{nome}: {type(e).__name__}: {e}")
    if privado:
        motivo = "\n".join(erros) or "o Ollama está desligado (NEXO_OLLAMA_ATIVO)."
        raise ModoPrivado(f"Modo privado ligado: o Ollama local não respondeu e nada foi enviado à nuvem.\n{motivo}")
    if not erros:
        raise SemIA(
            "Nenhuma IA disponível. Configure GEMINI_API_KEY, ANTHROPIC_API_KEY, "
            "DEEPSEEK_API_KEY, NVIDIA_API_KEY ou ative o Ollama local (NEXO_OLLAMA_ATIVO=1)."
        )
    raise SemIA("Todas as IAs falharam:\n" + "\n".join(erros))


def _dupla(prompt, sistema, esquema) -> Resposta:
    ativos = disponiveis()
    if len(ativos) < 2:
        return _uma(prompt, sistema, esquema, "profundo", ORDEM["profundo"])
    with ThreadPoolExecutor(2) as pool:
        futuros = {n: pool.submit(_uma, prompt, sistema, None, "dupla", [n]) for n in ativos}
    respostas = {}
    for nome, futuro in futuros.items():
        try:
            respostas[nome] = futuro.result().texto
        except SemIA:
            pass
    if len(respostas) < 2:
        return _uma(prompt, sistema, esquema, "profundo", ORDEM["profundo"])
    juncao = (
        "Duas IAs responderam ao mesmo pedido. Junte o melhor das duas numa única resposta: "
        "mantenha o que estiver certo e for útil, corrija o que estiver errado e não mencione "
        "que houve duas respostas.\n\n"
        f"<pedido>\n{prompt}\n</pedido>\n\n"
        + "".join(f"<resposta ia=\"{n}\">\n{t}\n</resposta>\n\n" for n, t in respostas.items())
    )
    final = _uma(juncao, sistema, esquema, "profundo", ORDEM["profundo"])
    final.provedor = "+".join([n for n in ativos if n in respostas])
    return final


def perguntar(prompt: str, sistema: str | None = None, modo: str = "rapido",
              esquema: dict | None = None) -> Resposta:
    """Pergunta às IAs conforme o modo. Com esquema, a resposta vem em JSON em .dados."""
    if modo == "dupla":
        return _dupla(prompt, sistema, esquema)
    if modo not in ORDEM:
        raise ValueError(f"modo desconhecido: {modo}. Use rapido, profundo ou dupla.")
    return _uma(prompt, sistema, esquema, modo, ORDEM[modo])
