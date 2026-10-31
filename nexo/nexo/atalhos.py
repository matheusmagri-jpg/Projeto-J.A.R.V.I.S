"""Pedidos comuns respondidos na hora, sem chamar nenhuma IA (hora, data, clima, Galo).

Cada passo de IA leva de 1 a 6 s e um pedido com ferramenta custa dois passos; para o que tem
resposta direta, o Jarvis fala em menos de um segundo. Só entram pedidos curtos e inequívocos:
qualquer coisa diferente vai para a conversa normal.
"""
import re
import unicodedata

from . import config


def _normalizar(texto: str) -> str:
    sem = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", sem.lower()).split())


_HORA = re.compile(r"^(?:jarvis )?(?:que|qual) (?:horas? (?:sao|e)|a hora)(?: agora)?(?: por favor)?$|^(?:me )?(?:diga|fala|fale) as horas$|^horas$")
_DATA = re.compile(r"^(?:jarvis )?(?:que dia (?:e|eh) hoje|qual (?:e )?a data(?: de hoje)?|que data (?:e|eh) hoje|qual (?:e )?o dia de hoje|que dia da semana (?:e|eh) hoje)(?: por favor)?$")
_CLIMA = re.compile(r"^(?:jarvis )?(?:(?:como esta|qual e|qual) )?(?:o )?(?:clima|tempo)(?: de)?(?: hoje| agora| la fora)?(?: por favor)?$|^vai chover(?: hoje)?$")


# "E o Galo?", "Jarvis, e o Galão?", "qual o próximo jogo do Atlético?": pergunta curta sobre o time.
_TIME = {"galo", "galao", "atletico"}
_SOBRE_O_TIME = _TIME | {
    "jarvis", "e", "ai", "o", "a", "os", "as", "como", "esta", "ta", "vai", "anda", "qual", "quais", "quando",
    "que", "do", "da", "de", "no", "na", "proximo", "proximos", "jogo", "jogos", "colocacao", "posicao",
    "tabela", "brasileirao", "campeonato", "brasileiro", "me", "fala", "fale", "diga", "sobre", "hoje",
    "agora", "meu", "mineiro", "mg", "joga", "lugar", "tem",
}


def _galo(m: str) -> bool:
    palavras = m.split()
    return bool(palavras) and len(palavras) <= 9 and bool(_TIME & set(palavras)) and set(palavras) <= _SOBRE_O_TIME


def tem(mensagem: str) -> bool:
    """O pedido tem resposta local (não precisa de IA nem de reconhecimento falado)?"""
    m = _normalizar(mensagem)
    return bool(_HORA.match(m) or _DATA.match(m) or _CLIMA.match(m) or _galo(m))


def tentar(mensagem: str, ferramentas: dict) -> tuple[str, str] | None:
    """(texto, ferramenta usada) se o pedido tem atalho, senão None."""
    m = _normalizar(mensagem)
    t = config.TRATAMENTO
    try:
        if _HORA.match(m) and "hora_data" in ferramentas:
            achou = re.search(r"(\d{1,2}):(\d{2})", str(ferramentas["hora_data"].executar()))
            if achou:
                h, mi = int(achou[1]), achou[2]
                return f"São {h}h{mi}, {t}." if mi != "00" else f"São {h} horas em ponto, {t}.", "hora_data"
        if _DATA.match(m) and "hora_data" in ferramentas:
            data = re.sub(r",?\s*\d{1,2}:\d{2}\.?$", "", str(ferramentas["hora_data"].executar()).strip())
            return f"Hoje é {data}, {t}.", "hora_data"
        if _CLIMA.match(m) and "clima" in ferramentas:
            from .proativo import CIDADE
            texto = str(ferramentas["clima"].executar(cidade=CIDADE)).strip().rstrip(".")
            if texto and "erro" not in texto.lower() and "não consegui" not in texto.lower():
                return f"{texto}, {t}.", "clima"
        if _galo(m):
            from . import futebol
            texto = futebol.falar_galo(futebol.galo_recente())
            if texto:
                return texto, "galo"
    except Exception:
        return None   # qualquer falha: deixa a IA responder
    return None
