"""Galo no painel: colocação do Atlético Mineiro no Brasileirão e os próximos jogos.

Dados da API pública da ESPN (sem chave). O time pode ser trocado por NEXO_TIME_ESPN
(id do time na ESPN; o Atlético-MG é 7632).
"""
import datetime as dt
import json
import os
import time
import urllib.request

TIME = os.environ.get("NEXO_TIME_ESPN", "7632")
TABELA = "https://site.api.espn.com/apis/v2/sports/soccer/bra.1/standings"
JOGOS = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/{time}/schedule?fixture=true"
BRASILIA = dt.timezone(dt.timedelta(hours=-3))   # sem horário de verão desde 2019
COMPETICOES = {"Brazilian Serie A": "Brasileirão", "Copa do Brasil": "Copa do Brasil",
               "CONMEBOL Libertadores": "Libertadores", "CONMEBOL Sudamericana": "Sul-Americana"}


def _baixar(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (NEXO)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def colocacao(tabela: dict, time: str = TIME) -> dict | None:
    for grupo in tabela.get("children", []):
        for linha in grupo.get("standings", {}).get("entries", []):
            if str(linha["team"]["id"]) != str(time):
                continue
            s = {x["name"]: x.get("value") for x in linha.get("stats", [])}
            return {"time": linha["team"]["displayName"], "posicao": int(s.get("rank") or 0),
                    "pontos": int(s.get("points") or 0), "jogos": int(s.get("gamesPlayed") or 0),
                    "vitorias": int(s.get("wins") or 0), "empates": int(s.get("ties") or 0),
                    "derrotas": int(s.get("losses") or 0)}
    return None


def proximos(agenda: dict, time: str = TIME, quantos: int = 4) -> list[dict]:
    jogos = []
    for evento in agenda.get("events", []):
        c = evento["competitions"][0]
        if c.get("status", {}).get("type", {}).get("completed"):
            continue
        casa = next((t for t in c["competitors"] if t.get("homeAway") == "home"), c["competitors"][0])
        fora = next((t for t in c["competitors"] if t is not casa), c["competitors"][-1])
        em_casa = str(casa["team"]["id"]) == str(time)
        quando = dt.datetime.fromisoformat(evento["date"].replace("Z", "+00:00")).astimezone(BRASILIA)
        liga = evento.get("league", {}).get("name", "") if isinstance(evento.get("league"), dict) else ""
        jogos.append({"quando": quando.isoformat(), "adversario": (fora if em_casa else casa)["team"]["displayName"],
                      "em_casa": em_casa, "competicao": COMPETICOES.get(liga, liga),
                      "local": c.get("venue", {}).get("fullName", "")})
    return sorted(jogos, key=lambda j: j["quando"])[:quantos]


_guardado: tuple[float, dict | None] = (0.0, None)


def galo_recente(validade_s: float = 30 * 60) -> dict | None:
    """O mesmo que galo(), guardado por 30 min. Se a ESPN falhar, fica o último que deu certo."""
    global _guardado
    instante, dados = _guardado
    if time.time() - instante > validade_s:
        novo = galo()
        if novo["colocacao"] or novo["jogos"] or dados is None:
            dados = novo
        _guardado = (time.time(), dados)
    return dados


def falar_galo(dados: dict | None) -> str | None:
    """Frase para responder "e o Galo?" na hora, sem IA."""
    if not dados or not (dados.get("colocacao") or dados.get("jogos")):
        return None
    partes = []
    c = dados.get("colocacao")
    if c:
        partes.append(f"O Galo está em {c['posicao']}º no Brasileirão, com {c['pontos']} pontos em {c['jogos']} jogos: "
                      f"{c['vitorias']} vitórias, {c['empates']} empates e {c['derrotas']} derrotas.")
    if dados.get("jogos"):
        j = dados["jogos"][0]
        quando = dt.datetime.fromisoformat(j["quando"])
        dia = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][quando.weekday()]
        hora = f"{quando.hour}h{quando.minute:02d}" if quando.minute else f"{quando.hour}h"
        lado = "contra o" if j["em_casa"] else "fora, contra o"
        local = f", na {j['local']}" if j.get("local") and j["em_casa"] else ""
        partes.append(f"Próximo jogo: {dia}, {quando:%d/%m}, às {hora}, {lado} {j['adversario']}{local}, "
                      f"pelo {j['competicao']}." if j["competicao"] == "Brasileirão" else
                      f"Próximo jogo: {dia}, {quando:%d/%m}, às {hora}, {lado} {j['adversario']}{local}, "
                      f"pela {j['competicao']}.")
    return " ".join(partes)


def galo() -> dict:
    """Colocação e próximos jogos. Uma fonte fora do ar não derruba a outra."""
    dados: dict = {"colocacao": None, "jogos": []}
    try:
        dados["colocacao"] = colocacao(_baixar(TABELA))
    except Exception:
        pass
    try:
        dados["jogos"] = proximos(_baixar(JOGOS.format(time=TIME)))
    except Exception:
        pass
    return dados
