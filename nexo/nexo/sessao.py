"""Resume uma sessão do Claude Code no diário do cérebro (roda em segundo plano).

Só olha as mensagens novas desde o último resumo daquela sessão, para não repetir.
"""
import json
from pathlib import Path

from . import cerebro, config, ia

LIMITE_CARACTERES = 15000


def _texto(conteudo) -> str:
    if isinstance(conteudo, str):
        return conteudo
    if isinstance(conteudo, list):
        return "\n".join(b.get("text", "") for b in conteudo if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _mensagens(transcript: Path) -> list[tuple[str, str]]:
    msgs = []
    for linha in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(linha)
        except ValueError:
            continue
        if item.get("type") not in ("user", "assistant"):
            continue
        texto = _texto((item.get("message") or {}).get("content")).strip()
        if texto:
            msgs.append((item["type"], texto))
    return msgs


ROTULOS = {"claude-code": "Sessão do Claude Code", "conversa": f"Conversa com a {config.NOME}"}


def registrar_resumo(conversa: str, origem: str, mensagens: int) -> None:
    """Pede a uma IA o que vale lembrar da conversa e escreve no diário."""
    rotulo = ROTULOS.get(origem, origem)
    conversa = conversa[-LIMITE_CARACTERES:]
    if ia.disponiveis():
        prompt = (
            f"<conversa>\n{conversa}\n</conversa>\n\n"
            f"Esta é uma {rotulo.lower()}. Liste em tópicos curtos só o que vale lembrar no "
            "futuro: decisões tomadas, lições aprendidas, fatos novos sobre o usuário ou projetos, "
            "pendências. Cite projetos e pessoas como [[Nome]]. Se nada valer a pena, responda só NADA."
        )
        try:
            resumo = ia.perguntar(prompt, modo="rapido").texto
        except ia.SemIA:
            resumo = f"Encerrada com {mensagens} mensagens novas (as IAs não responderam)."
    else:
        resumo = f"Encerrada com {mensagens} mensagens novas (sem IA configurada para resumir)."
    if resumo.strip().upper() != "NADA":
        cerebro.registrar_diario(f"{rotulo}:\n{resumo}", origem=origem)


def resumir(transcript: str, sessao_id: str = "") -> None:
    caminho = Path(transcript)
    if not caminho.exists():
        return
    estado_arq = config.DADOS / "sessoes.json"
    config.DADOS.mkdir(parents=True, exist_ok=True)
    estado = json.loads(estado_arq.read_text(encoding="utf-8")) if estado_arq.exists() else {}
    chave = sessao_id or caminho.stem

    msgs = _mensagens(caminho)
    novas = msgs[estado.get(chave, 0):]
    if not novas:
        return
    conversa = "\n\n".join(f"[{quem}] {texto}" for quem, texto in novas)
    registrar_resumo(conversa, "claude-code", len(novas))
    estado[chave] = len(msgs)
    tmp = estado_arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(estado_arq)
