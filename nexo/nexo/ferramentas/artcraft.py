"""Ferramentas do ArtCraft (PhotoCraft, VectorCraft, WordCraft, GridCraft, SoundCraft).

Usa a linha de comando de cada programa, sem abrir janela. Regras de segurança:
- só lê e escreve dentro da pasta de arquivos do NEXO (config.ARQUIVOS);
- nunca sobrescreve: se o arquivo de saída já existe, ganha um sufixo (-1, -2...).
"""
import json
import os
import re
import subprocess
from pathlib import Path

from .. import config
from . import Ferramenta

PROGRAMAS = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
CLIS = {
    "photocraft": PROGRAMAS / "PhotoCraft" / "photocraft-cli.exe",
    "vectorcraft": PROGRAMAS / "VectorCraft" / "vectorcraft-cli.exe",
    "wordcraft": PROGRAMAS / "WordCraft" / "wordcraft-cli.exe",
    "gridcraft": PROGRAMAS / "GridCraft" / "gridcraft-cli.exe",
    "soundcraft": PROGRAMAS / "SoundCraft" / "soundcraft-cli.exe",
}
FORMATOS = {
    "imagem": ["webp", "png", "jpg", "tif", "psd"],
    "vetor": ["png", "pdf", "svg", "eps"],
    "documento": ["pdf", "docx", "html", "md", "txt", "odt", "rtf"],
    "planilha": ["xlsx", "csv", "json", "html", "tsv"],
    "audio": ["wav", "flac", "aiff"],
}


class ErroArtCraft(Exception):
    pass


# ---------- apoio ----------

def _pasta() -> Path:
    config.ARQUIVOS.mkdir(parents=True, exist_ok=True)
    return config.ARQUIVOS.resolve()


def _dentro(nome: str) -> Path:
    """Caminho de um arquivo da pasta do NEXO; recusa qualquer coisa fora dela."""
    caminho = (_pasta() / nome).resolve()
    if _pasta() not in caminho.parents:
        raise ErroArtCraft(f"Só trabalho com arquivos da pasta {_pasta()}.")
    return caminho


def _existente(nome: str) -> Path:
    caminho = _dentro(nome)
    if not caminho.is_file():
        raise ErroArtCraft(f"Não achei {nome} na pasta de arquivos. Use arquivos_listar para ver o que há.")
    return caminho


def _saida(origem: Path, formato: str, sufixo: str = "") -> Path:
    """Nome de saída ao lado do original, sem nunca sobrescrever."""
    base = f"{origem.stem}{sufixo}"
    alvo = origem.with_name(f"{base}.{formato}")
    n = 1
    while alvo.exists():
        alvo = origem.with_name(f"{base}-{n}.{formato}")
        n += 1
    return alvo


def _cli(programa: str, *args: str | Path, tempo: int = 180) -> str:
    """Roda a CLI dentro da pasta de trabalho; caminhos viram relativos a ela."""
    exe = CLIS[programa]
    if not exe.exists():
        raise ErroArtCraft(f"{programa} não está instalado ({exe}).")
    args = [a.relative_to(_pasta()).as_posix() if isinstance(a, Path) else a for a in args]
    r = subprocess.run([str(exe), *args], cwd=_pasta(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=tempo, **config.SEM_JANELA)
    if r.returncode != 0:
        raise ErroArtCraft(f"{programa} falhou: {(r.stderr or r.stdout).strip()[-400:]}")
    return r.stdout


def _kb(caminho: Path) -> str:
    tamanho = caminho.stat().st_size
    return f"{tamanho} bytes" if tamanho < 1024 else f"{tamanho / 1024:.0f} KB"


_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _sem_links(texto: str) -> str:
    """[[Nota]] -> Nota e [[Nota|apelido]] -> apelido: links do Obsidian não fazem sentido num PDF."""
    return _LINK.sub(lambda m: m.group(2) or m.group(1), texto)


def _checar_formato(tipo: str, formato: str) -> str:
    formato = formato.lower().lstrip(".")
    if formato not in FORMATOS[tipo]:
        raise ErroArtCraft(f"Formato {formato} não suportado para {tipo}. Use: {', '.join(FORMATOS[tipo])}.")
    return formato


# ---------- arquivos ----------

def arquivos_listar() -> str:
    itens = sorted(p for p in _pasta().rglob("*") if p.is_file())
    if not itens:
        return f"A pasta {_pasta()} está vazia. Coloque lá os arquivos que quer que eu trabalhe."
    return "\n".join(f"{p.relative_to(_pasta()).as_posix()} ({_kb(p)})" for p in itens[:100])


# ---------- imagem (PhotoCraft) ----------

def _dimensoes(caminho: Path) -> str:
    info = json.loads(_cli("photocraft", "info", caminho, "--compact"))
    return f"{info['width']}x{info['height']}"


def imagem_info(arquivo: str) -> str:
    origem = _existente(arquivo)
    return f"{arquivo}: {_dimensoes(origem)} px, {_kb(origem)}."


def imagem_converter(arquivo: str, formato: str = "webp", largura: int = 0, qualidade: int = 0) -> str:
    origem = _existente(arquivo)
    formato = _checar_formato("imagem", formato)
    saida = _saida(origem, formato, f"-{largura}" if largura else "")
    extra = ["--quality", str(qualidade)] if qualidade else []
    if largura:
        _cli("photocraft", "run", origem, "--cmd", "image.imageSize",
             "--params", json.dumps({"width": int(largura), "resample": "bicubicSharper"}),
             "--out", saida, *extra)
    else:
        _cli("photocraft", "convert", origem, saida, *extra)
    return (f"Criei {saida.name}: {_dimensoes(saida)} px, {_kb(saida)} "
            f"(original {_dimensoes(origem)} px, {_kb(origem)}).")


# ---------- vetor (VectorCraft) ----------

def vetor_exportar(arquivo: str, formato: str = "png", escala: float = 1) -> str:
    origem = _existente(arquivo)
    formato = _checar_formato("vetor", formato)
    saida = _saida(origem, formato)
    extra = ["--scale", str(escala)] if formato == "png" else []
    _cli("vectorcraft", "convert", origem, saida, *extra)
    return f"Exportei {saida.name} ({_kb(saida)})."


# ---------- documento (WordCraft) ----------

def documento_criar(titulo: str, conteudo: str, formato: str = "pdf") -> str:
    formato = _checar_formato("documento", formato)
    from ..cerebro import nome_arquivo
    rascunho = _saida(_dentro(f"{nome_arquivo(titulo)}.md"), "md")
    conteudo = _sem_links(conteudo)
    rascunho.write_text(conteudo if conteudo.lstrip().startswith("#") else f"# {titulo}\n\n{conteudo}",
                        encoding="utf-8")
    if formato == "md":
        return f"Criei {rascunho.name}."
    saida = _saida(rascunho, formato)
    _cli("wordcraft", "convert", rascunho, saida)
    return f"Criei {saida.name} ({_kb(saida)}); o texto-fonte ficou em {rascunho.name}."


def documento_converter(arquivo: str, formato: str = "pdf") -> str:
    origem = _existente(arquivo)
    formato = _checar_formato("documento", formato)
    saida = _saida(origem, formato)
    _cli("wordcraft", "convert", origem, saida)
    return f"Criei {saida.name} ({_kb(saida)})."


def documento_ler(arquivo: str) -> str:
    texto = _cli("wordcraft", "text", _existente(arquivo))
    return texto[:6000] + ("\n[...texto cortado]" if len(texto) > 6000 else "")


# ---------- planilha (GridCraft) ----------

def planilha_converter(arquivo: str, formato: str = "xlsx") -> str:
    origem = _existente(arquivo)
    formato = _checar_formato("planilha", formato)
    saida = _saida(origem, formato)
    _cli("gridcraft", "convert", origem, saida)
    return f"Criei {saida.name} ({_kb(saida)})."


def planilha_ver(arquivo: str, intervalo: str = "") -> str:
    extra = ["--range", intervalo] if intervalo else []
    texto = _cli("gridcraft", "cat", _existente(arquivo), "--csv", *extra)
    return texto[:6000] + ("\n[...cortado]" if len(texto) > 6000 else "")


def planilha_formula(formula: str, arquivo: str = "") -> str:
    if not formula.startswith("="):
        formula = "=" + formula
    extra = ["--in", _existente(arquivo)] if arquivo else []
    return f"{formula} = {_cli('gridcraft', 'eval', formula, *extra).strip()}"


# ---------- áudio (SoundCraft) ----------

def audio_converter(arquivo: str, formato: str = "wav", normalizar: bool = False) -> str:
    origem = _existente(arquivo)
    formato = _checar_formato("audio", formato)
    saida = _saida(origem, formato, "-normalizado" if normalizar else "")
    _cli("soundcraft", "convert", origem, saida, *(["--normalize"] if normalizar else []))
    return f"Criei {saida.name} ({_kb(saida)})."


_ARQ = {"type": "string", "description": "Nome do arquivo dentro da pasta de arquivos do NEXO"}

FERRAMENTAS = [
    Ferramenta("arquivos_listar", "Lista os arquivos da pasta de trabalho do NEXO (onde ficam imagens, "
               "documentos, planilhas e áudios para os programas do ArtCraft).", arquivos_listar),
    Ferramenta("imagem_info", "Mostra dimensões e tamanho de uma imagem (PhotoCraft).", imagem_info,
               {"arquivo": _ARQ}, ["arquivo"]),
    Ferramenta("imagem_converter",
               "Converte e/ou redimensiona uma imagem com o PhotoCraft (ex.: JPG para WebP de 800 px). "
               "Qualidade 80 é boa para fotos; sem qualidade, WebP sai sem perda. Nunca altera o original.",
               imagem_converter,
               {"arquivo": _ARQ, "formato": {"type": "string", "enum": FORMATOS["imagem"]},
                "largura": {"type": "integer", "description": "Nova largura em pixels; 0 mantém"},
                "qualidade": {"type": "integer", "description": "1 a 100 para JPG/WebP; 0 = padrão"}},
               ["arquivo"]),
    Ferramenta("vetor_exportar", "Exporta um desenho vetorial (SVG, AI, PDF) para PNG, PDF, SVG ou EPS "
               "com o VectorCraft. Escala = pixels por ponto no PNG (2 = dobro).", vetor_exportar,
               {"arquivo": _ARQ, "formato": {"type": "string", "enum": FORMATOS["vetor"]},
                "escala": {"type": "number"}}, ["arquivo"]),
    Ferramenta("documento_criar",
               "Escreve um documento novo (proposta, relatório, roteiro, apostila) em Markdown e gera "
               "PDF, DOCX ou outro formato com o WordCraft.", documento_criar,
               {"titulo": {"type": "string"},
                "conteudo": {"type": "string", "description": "Texto completo em Markdown"},
                "formato": {"type": "string", "enum": FORMATOS["documento"]}},
               ["titulo", "conteudo"]),
    Ferramenta("documento_converter", "Converte um documento (DOCX, MD, ODT, RTF, HTML) para PDF, DOCX etc. "
               "com o WordCraft.", documento_converter,
               {"arquivo": _ARQ, "formato": {"type": "string", "enum": FORMATOS["documento"]}}, ["arquivo"]),
    Ferramenta("documento_ler", "Lê o texto de um documento DOCX, ODT, RTF, MD ou HTML (WordCraft).",
               documento_ler, {"arquivo": _ARQ}, ["arquivo"]),
    Ferramenta("planilha_converter", "Converte planilhas entre XLSX, CSV, JSON, TSV e HTML (GridCraft).",
               planilha_converter,
               {"arquivo": _ARQ, "formato": {"type": "string", "enum": FORMATOS["planilha"]}}, ["arquivo"]),
    Ferramenta("planilha_ver", "Mostra o conteúdo de uma planilha como CSV, opcionalmente só um intervalo "
               "(ex.: A1:D20) (GridCraft).", planilha_ver,
               {"arquivo": _ARQ, "intervalo": {"type": "string"}}, ["arquivo"]),
    Ferramenta("planilha_formula", "Calcula uma fórmula de planilha (ex.: =SOMA(B2:B10) escrito como "
               "=SUM(B2:B10)), sozinha ou sobre um arquivo (GridCraft).", planilha_formula,
               {"formula": {"type": "string"}, "arquivo": _ARQ}, ["formula"]),
    Ferramenta("audio_converter", "Converte áudio para WAV, FLAC ou AIFF e pode normalizar o volume "
               "(SoundCraft). Não gera MP3.", audio_converter,
               {"arquivo": _ARQ, "formato": {"type": "string", "enum": FORMATOS["audio"]},
                "normalizar": {"type": "boolean"}}, ["arquivo"]),
]
