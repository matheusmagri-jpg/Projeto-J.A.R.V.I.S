"""Ferramentas que consultam a internet sem precisar de chave: clima e Wikipédia."""
import json
import urllib.parse
import urllib.request

from . import Ferramenta

TEMPO = {0: "céu limpo", 1: "poucas nuvens", 2: "parcialmente nublado", 3: "nublado", 45: "neblina",
         48: "neblina", 51: "garoa", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva",
         65: "chuva forte", 80: "pancadas de chuva", 81: "pancadas de chuva", 82: "temporal",
         95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo"}


def _json(url: str) -> dict:
    pedido = urllib.request.Request(url, headers={"User-Agent": "NEXO/1.0"})
    with urllib.request.urlopen(pedido, timeout=10) as r:
        return json.load(r)


def clima_dados(cidade: str) -> dict | None:
    """Clima atual e previsão de hoje e amanhã, em números (o painel usa direto; clima() vira frase)."""
    q = urllib.parse.quote(cidade)
    lugares = _json(f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=pt").get("results")
    if not lugares:
        return None
    lugar = lugares[0]
    dados = _json(
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lugar['latitude']}&longitude={lugar['longitude']}"
        "&current=temperature_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        "&timezone=auto&forecast_days=2")
    atual, dia = dados["current"], dados["daily"]
    return {
        "cidade": lugar["name"],
        "agora": round(atual["temperature_2m"]),
        "condicao": TEMPO.get(atual["weather_code"], "tempo variável"),
        "hoje": {"min": round(dia["temperature_2m_min"][0]), "max": round(dia["temperature_2m_max"][0]),
                 "chuva": dia["precipitation_probability_max"][0]},
        "amanha": {"min": round(dia["temperature_2m_min"][1]), "max": round(dia["temperature_2m_max"][1]),
                   "chuva": dia["precipitation_probability_max"][1],
                   "condicao": TEMPO.get(dia["weather_code"][1], "tempo variável")},
    }


def clima(cidade: str) -> str:
    c = clima_dados(cidade)
    if not c:
        return f"Não encontrei a cidade {cidade}."
    return (f"{c['cidade']}: agora {c['agora']} graus, {c['condicao']}. "
            f"Hoje entre {c['hoje']['min']} e {c['hoje']['max']} graus, {c['hoje']['chuva']}% de chance de chuva. "
            f"Amanhã entre {c['amanha']['min']} e {c['amanha']['max']} graus, {c['amanha']['condicao']}.")


def wikipedia(termo: str) -> str:
    titulo = urllib.parse.quote(termo.replace(" ", "_"))
    try:
        dados = _json(f"https://pt.wikipedia.org/api/rest_v1/page/summary/{titulo}")
    except Exception:
        return f"Não encontrei '{termo}' na Wikipédia."
    return dados.get("extract") or f"A Wikipédia não tem um resumo para '{termo}'."


FERRAMENTAS = [
    Ferramenta("clima", "Temperatura atual e previsão de hoje e amanhã de uma cidade.", clima,
               {"cidade": {"type": "string"}}, ["cidade"]),
    Ferramenta("wikipedia", "Resumo de um assunto na Wikipédia em português.", wikipedia,
               {"termo": {"type": "string", "description": "Título do artigo, ex.: Alan Turing"}}, ["termo"]),
]
