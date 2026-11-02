"""Busca no cérebro: SQLite FTS5 (BM25) + bônus para notas muito ligadas.

O índice é incremental: só reindexa arquivos cuja data de modificação mudou.
"""
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from time import monotonic

from . import cerebro, config

BONUS_POR_LINK = 0.15  # cada nota que aponta para esta melhora um pouco a posição
TTL_LINKS_S = 10.0
# Abaixo disso a busca por palavras achou pouco e a busca por significado (semantica.py) entra junto.
# Acima, ela fica de fora: cada uso custa uma chamada ao Gemini e a resposta do painel demora mais.
MINIMO_PALAVRAS = 3
RRF_K = 60             # fusão por posição (reciprocal rank fusion) das duas listas


@dataclass
class Resultado:
    titulo: str
    rel: str
    trecho: str
    pontos: float


_cache_links: tuple[float, dict[str, int]] | None = None


def _conectar() -> sqlite3.Connection:
    config.DADOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DADOS / "indice.db")
    con.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS notas USING fts5(
            rel UNINDEXED, titulo, meta, corpo, tokenize = 'unicode61 remove_diacritics 2');
        CREATE TABLE IF NOT EXISTS arquivos (rel TEXT PRIMARY KEY, mtime REAL, links TEXT);
    """)
    return con


def indexar() -> int:
    """Atualiza o índice. Devolve quantas notas foram (re)indexadas."""
    con = _conectar()
    vistos, mudados = set(), 0
    conhecidos = dict(con.execute("SELECT rel, mtime FROM arquivos"))
    for caminho in cerebro.todas():
        nota = cerebro.ler(caminho)
        vistos.add(nota.rel)
        mtime = caminho.stat().st_mtime
        if conhecidos.get(nota.rel) == mtime:
            continue
        con.execute("DELETE FROM notas WHERE rel = ?", (nota.rel,))
        meta = " ".join(f"{k} {v}" for k, v in nota.meta.items())
        con.execute("INSERT INTO notas (rel, titulo, meta, corpo) VALUES (?, ?, ?, ?)",
                    (nota.rel, nota.titulo, meta, nota.corpo))
        con.execute("INSERT OR REPLACE INTO arquivos VALUES (?, ?, ?)",
                    (nota.rel, mtime, "\n".join(sorted(nota.links))))
        mudados += 1
    for rel in set(conhecidos) - vistos:
        con.execute("DELETE FROM notas WHERE rel = ?", (rel,))
        con.execute("DELETE FROM arquivos WHERE rel = ?", (rel,))
    con.commit()
    con.close()
    global _cache_links
    _cache_links = None
    return mudados


def _links_recebidos(con: sqlite3.Connection) -> dict[str, int]:
    global _cache_links
    if _cache_links and monotonic() - _cache_links[0] <= TTL_LINKS_S:
        return _cache_links[1]

    links_recebidos: dict[str, int] = {}
    for (links,) in con.execute("SELECT links FROM arquivos"):
        for alvo in filter(None, links.split("\n")):
            links_recebidos[alvo.lower()] = links_recebidos.get(alvo.lower(), 0) + 1
    _cache_links = (monotonic(), links_recebidos)
    return links_recebidos


def _termos(consulta: str) -> list[str]:
    """Palavras sem acento, reduzidas a um radical simples (decisão/decisões -> deci*)."""
    sem_acento = unicodedata.normalize("NFKD", consulta).encode("ascii", "ignore").decode()
    palavras = [t for t in re.findall(r"\w+", sem_acento.lower()) if len(t) > 1]
    return [t[:max(4, len(t) - 3)] if len(t) > 4 else t for t in palavras]


def buscar(consulta: str, limite: int = 5, semantica: bool | None = None) -> list[Resultado]:
    """Busca por palavras; semantica=None junta a busca por significado só quando as palavras acham pouco."""
    indexar()
    termos = _termos(consulta)
    if not termos:
        return []
    con = _conectar()
    links_recebidos = _links_recebidos(con)

    # Primeiro exige todos os termos; se não achar nada, aceita qualquer um.
    linhas = []
    for juncao in (" AND ", " OR "):
        expressao = juncao.join(f'"{t}"*' for t in termos)
        linhas = con.execute(
            "SELECT rel, titulo, snippet(notas, 3, '**', '**', '…', 16), bm25(notas, 0.0, 5.0, 2.0, 1.0) "
            "FROM notas WHERE notas MATCH ? ORDER BY bm25(notas, 0.0, 5.0, 2.0, 1.0) LIMIT ?",
            (expressao, limite * 3)).fetchall()
        if linhas:
            break

    resultados = []
    for rel, titulo, trecho, bm25 in linhas:
        # bm25 do SQLite é negativo: quanto menor, melhor.
        pontos = -bm25 * (1 + BONUS_POR_LINK * links_recebidos.get(titulo.lower(), 0))
        resultados.append(Resultado(titulo, rel, " ".join(trecho.split()), round(pontos, 3)))
    resultados.sort(key=lambda r: r.pontos, reverse=True)
    if semantica if semantica is not None else len(resultados) < MINIMO_PALAVRAS:
        resultados = _com_semantica(con, consulta, resultados, limite)
    con.close()
    return resultados[:limite]


def _com_semantica(con: sqlite3.Connection, consulta: str, por_palavras: list[Resultado],
                   limite: int) -> list[Resultado]:
    from . import semantica
    parecidas = semantica.buscar(consulta, limite)
    if not parecidas:
        return por_palavras
    pontos: dict[str, float] = {}
    achados = {r.rel: r for r in por_palavras}
    for lista in ([r.rel for r in por_palavras], [rel for rel, _ in parecidas]):
        for posicao, rel in enumerate(lista):
            pontos[rel] = pontos.get(rel, 0.0) + 1 / (RRF_K + posicao)
    for rel, _ in parecidas:
        if rel not in achados:
            linha = con.execute("SELECT titulo, substr(corpo, 1, 240) FROM notas WHERE rel = ?", (rel,)).fetchone()
            if linha:
                achados[rel] = Resultado(linha[0], rel, " ".join(linha[1].split()) + "…", 0.0)
    juntos = [Resultado(r.titulo, r.rel, r.trecho, round(pontos[rel] * 1000, 3)) for rel, r in achados.items()]
    return sorted(juntos, key=lambda r: r.pontos, reverse=True)
