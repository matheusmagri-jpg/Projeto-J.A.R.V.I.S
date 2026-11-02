"""Busca por significado no cérebro: acha "veículo" quando a nota diz "carro".

Cada nota vira um vetor (embedding do Gemini) guardado em dados/vetores.db, refeito só quando a nota muda.
A busca compara o vetor da pergunta com o de cada nota. Complementa o FTS5 de busca.py, não o substitui:
no modo privado, ou sem Gemini, não há vetores e a busca por palavras segue sozinha.
"""
from __future__ import annotations

import os
import sqlite3
import threading

import numpy as np

from . import cerebro, config, ia

MODELO = os.environ.get("NEXO_EMBEDDING_MODELO", "gemini-embedding-001")
DIMENSOES = 768
LOTE = 50                 # notas por chamada à API
LIMIAR = 0.55             # abaixo disso a nota não tem a ver com a pergunta
_trava = threading.Lock()


def disponivel() -> bool:
    return not ia.privado_ativo() and "gemini" in ia.disponiveis()


def _conectar() -> sqlite3.Connection:
    config.DADOS.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DADOS / "vetores.db")
    con.execute("CREATE TABLE IF NOT EXISTS vetores (rel TEXT PRIMARY KEY, mtime REAL, modelo TEXT, vetor BLOB)")
    return con


def _vetores(textos: list[str], tarefa: str) -> list[np.ndarray]:
    from google.genai import types
    r = ia.cliente("gemini").models.embed_content(
        model=MODELO, contents=textos,
        config=types.EmbedContentConfig(task_type=tarefa, output_dimensionality=DIMENSOES))
    saida = []
    for e in r.embeddings:
        v = np.asarray(e.values, dtype=np.float32)
        saida.append(v / (np.linalg.norm(v) or 1.0))   # normalizado: o produto escalar já é o cosseno
    return saida


def atualizar() -> int:
    """Gera o vetor das notas novas ou alteradas e apaga o das removidas. Devolve quantas mudaram."""
    if not disponivel():
        return 0
    with _trava:
        con = _conectar()
        try:
            conhecidos = {rel: (mtime, modelo) for rel, mtime, modelo in con.execute(
                "SELECT rel, mtime, modelo FROM vetores")}
            pendentes, vistos = [], set()
            for caminho in cerebro.todas():
                nota = cerebro.ler(caminho)
                vistos.add(nota.rel)
                mtime = caminho.stat().st_mtime
                if conhecidos.get(nota.rel) != (mtime, MODELO):
                    pendentes.append((nota.rel, mtime, f"{nota.titulo}\n\n{nota.corpo[:6000]}"))
            for i in range(0, len(pendentes), LOTE):
                lote = pendentes[i:i + LOTE]
                for (rel, mtime, _), v in zip(lote, _vetores([t for *_, t in lote], "RETRIEVAL_DOCUMENT")):
                    con.execute("INSERT OR REPLACE INTO vetores VALUES (?, ?, ?, ?)", (rel, mtime, MODELO, v.tobytes()))
            for rel in set(conhecidos) - vistos:
                con.execute("DELETE FROM vetores WHERE rel = ?", (rel,))
            con.commit()
            return len(pendentes)
        finally:
            con.close()


def buscar(consulta: str, limite: int = 5) -> list[tuple[str, float]]:
    """[(rel, semelhança)] das notas mais parecidas com a consulta. Vazio se não der para usar vetores."""
    if not consulta.strip() or not disponivel():
        return []
    try:
        atualizar()
        pergunta = _vetores([consulta], "RETRIEVAL_QUERY")[0]
    except Exception as e:
        # Sem internet ou sem cota: a busca por palavras continua respondendo.
        print(f"[semantica] {type(e).__name__}: {e}")
        return []
    con = _conectar()
    try:
        linhas = con.execute("SELECT rel, vetor FROM vetores WHERE modelo = ?", (MODELO,)).fetchall()
    finally:
        con.close()
    if not linhas:
        return []
    matriz = np.stack([np.frombuffer(v, dtype=np.float32) for _, v in linhas])
    notas = matriz @ pergunta
    ordem = np.argsort(-notas)[:limite]
    return [(linhas[i][0], round(float(notas[i]), 3)) for i in ordem if notas[i] >= LIMIAR]
