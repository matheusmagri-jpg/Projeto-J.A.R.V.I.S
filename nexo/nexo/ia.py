"""Claude, Gemini e Ollama juntos.

Modos:
- rapido:   Gemini primeiro (barato e veloz); Claude se o Gemini falhar.
- profundo: Claude primeiro (raciocínio, organizar o cérebro); Gemini se o Claude falhar.
- dupla:    os dois respondem em paralelo e o Claude junta o melhor de cada um.

As chaves ficam no .env e nunca entram no texto enviado para as IAs.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from urllib import error, request

from . import config

ORDEM = {
    "rapido": ["ollama", "gemini", "deepseek", "claude"],
    "profundo": ["ollama", "claude", "deepseek", "gemini"],
}
ESFORCO = {"rapido": "low", "profundo": "high", "dupla": "medium"}
TTL_CACHE_S = 12.0
MAX_CACHE = 128


class SemIA(RuntimeError):
    """Nenhuma IA disponível ou todas falharam."""


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
    if nome not in _clientes:
        # Limites de tempo: se uma IA travar, o NEXO passa para a outra em vez de esperar.
        if nome == "claude":
            import anthropic
            _clientes[nome] = anthropic.Anthropic(timeout=120.0, max_retries=1)
        elif nome == "gemini":
            from google import genai
            from google.genai import types
            _clientes[nome] = genai.Client(  # lê GEMINI_API_KEY
                http_options=types.HttpOptions(timeout=60_000))
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
_esgotados: dict[str, float] = {}


def gerar_gemini(contents, ajustes, modelos: list[str] | None = None):
    """Chama o Gemini; se um modelo bater no limite de uso (429), estiver sobrecarregado ou fora do
    ar (5xx), ou demorar mais que HEDGE_S, o próximo da lista entra na disputa.

    No plano gratuito cada modelo tem a própria cota por minuto, então trocar de modelo
    costuma resolver na hora.
    """
    from concurrent.futures import FIRST_COMPLETED, wait
    from google.genai import errors

    lista = list(modelos or config.GEMINI_MODELOS)
    agora = monotonic()
    ativos = [m for m in lista if _esgotados.get(m, 0) <= agora] or lista
    cliente_gemini = cliente("gemini")

    def chamar(modelo):
        return cliente_gemini.models.generate_content(model=modelo, contents=contents, config=ajustes)

    pool = ThreadPoolExecutor(len(ativos), thread_name_prefix="nexo-gemini")
    pendentes: dict = {}
    proximo, ultimo = 0, None
    try:
        while True:
            if proximo < len(ativos) and not pendentes:
                pendentes[pool.submit(chamar, ativos[proximo])] = ativos[proximo]
                proximo += 1
            feitos, _ = wait(pendentes, timeout=HEDGE_S if proximo < len(ativos) else None,
                             return_when=FIRST_COMPLETED)
            if not feitos:   # demorou: dispara o próximo sem desistir do que já está rodando
                pendentes[pool.submit(chamar, ativos[proximo])] = ativos[proximo]
                proximo += 1
                continue
            for futuro in feitos:
                modelo = pendentes.pop(futuro)
                try:
                    return futuro.result()
                except errors.ServerError as e:
                    ultimo = e
                except errors.ClientError as e:
                    if e.code != 429:
                        raise
                    _esgotados[modelo] = monotonic() + ESGOTADO_S
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
    resposta = gerar_gemini(prompt, ajustes)
    return (resposta.text or "").strip()


def chamar_deepseek(corpo: dict, timeout: float = 60.0) -> dict:
    """POST em /chat/completions (formato da OpenAI) e devolve o JSON da resposta."""
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY ausente")
    req = request.Request(
        f"{config.DEEPSEEK_BASE_URL}/chat/completions",
        data=json.dumps({"model": config.DEEPSEEK_MODELO, "stream": False, **corpo}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as r:
            bruto = r.read().decode("utf-8")
    except error.HTTPError as e:
        detalhe = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {e.code}: {detalhe[:500]}") from e
    except error.URLError as e:
        raise RuntimeError(f"Não consegui conectar ao DeepSeek em {config.DEEPSEEK_BASE_URL}: {e.reason}") from e
    try:
        return json.loads(bruto)
    except json.JSONDecodeError as e:
        raise RuntimeError("DeepSeek devolveu JSON inválido.") from e


def _deepseek(prompt: str, sistema: str | None, esquema: dict | None, modo: str) -> str:
    if esquema:
        json_prompt = (
            "Responda somente em JSON válido, sem markdown nem texto extra, "
            f"seguindo exatamente este schema: {json.dumps(esquema, ensure_ascii=False)}\n\n"
            f"Pergunta:\n{prompt}"
        )
        prompt = json_prompt

    corpo = {
        "messages": [
            {"role": "system", "content": sistema or "Responda em português do Brasil."},
            {"role": "user", "content": prompt},
        ],
    }
    if esquema:
        corpo["response_format"] = {"type": "json_object"}
    payload = chamar_deepseek(corpo)

    texto = ""
    for escolha in payload.get("choices", []):
        msg = escolha.get("message") or {}
        conteudo = msg.get("content")
        if isinstance(conteudo, str) and conteudo.strip():
            texto = conteudo.strip()
            break
        if isinstance(conteudo, list):
            partes = []
            for parte in conteudo:
                if isinstance(parte, dict):
                    text = parte.get("text")
                    if isinstance(text, str):
                        partes.append(text)
            if partes:
                texto = "".join(partes).strip()
                break
    if not texto:
        raise RuntimeError("DeepSeek devolveu resposta vazia.")
    return texto


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
    "ollama": (_ollama, config.tem_ollama),
}


# IAs cuja chave foi recusada (401/403) nesta execução: tentar de novo a cada pergunta só atrasa.
_recusadas: dict[str, str] = {}


def disponiveis() -> list[str]:
    return [nome for nome, (_, tem) in PROVEDORES.items() if tem() and nome not in _recusadas]


def chave_recusada(nome: str, erro: Exception) -> bool:
    """Se o erro é de chave inválida, tira a IA da lista até o Jarvis ser reiniciado."""
    texto = str(erro)
    if any(s in texto for s in ("HTTP 401", "HTTP 403", "authentication_error", "invalid x-api-key", "API_KEY_INVALID")):
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
        if config.tem_claude():
            cliente("claude")
        if config.tem_gemini():
            cliente("gemini")
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
        if tem():
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
            erros.append(f"{nome}: {type(e).__name__}: {e}")
    if not erros:
        raise SemIA(
            "Nenhuma IA disponível. Configure GEMINI_API_KEY, ANTHROPIC_API_KEY, "
            "DEEPSEEK_API_KEY ou ative o Ollama local (NEXO_OLLAMA_ATIVO=1)."
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
