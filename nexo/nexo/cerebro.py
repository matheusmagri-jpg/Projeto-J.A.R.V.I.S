"""Operações no cérebro (vault do Obsidian): ler, escrever com segurança, ligar notas.

Regras de escrita (ideia do claude-obsidian):
- toda escrita é atômica (arquivo temporário + os.replace);
- quem leu uma nota e vai reescrevê-la passa o hash que leu; se a nota mudou
  no meio do caminho (você editou no Obsidian), a escrita é recusada;
- ALMA.md nunca é escrita pelo NEXO.
"""
import datetime as dt
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config

# tipo da nota -> (pasta, índice que a lista)
TIPOS = {
    "pessoa": ("pessoas", "Pessoas"),
    "projeto": ("projetos", "Projetos"),
    "ideia": ("ideias", "Ideias"),
    "decisao": ("decisoes", "Decisões"),
    "fonte": ("fontes", "Fontes"),   # repositórios e pastas aprendidos (ver conhecimento.py)
}
PROTEGIDAS = {"ALMA.md"}
NUCLEO = ["ALMA", "USUARIO", "MEMORIA"]

_LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_PROIBIDOS = re.compile(r'[\\/:*?"<>|#^\[\]]')


class Conflito(Exception):
    """A nota mudou desde que foi lida."""


@dataclass
class Nota:
    caminho: Path
    titulo: str
    meta: dict = field(default_factory=dict)
    corpo: str = ""
    hash: str = ""

    @property
    def rel(self) -> str:
        return self.caminho.relative_to(raiz()).as_posix()

    @property
    def links(self) -> set[str]:
        return extrair_links(self.corpo)


def raiz() -> Path:
    return config.CEREBRO


def agora() -> dt.datetime:
    return dt.datetime.now()


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def nome_arquivo(titulo: str) -> str:
    """Título legível -> nome de arquivo válido no Windows e no Obsidian."""
    nome = _PROIBIDOS.sub(" ", titulo).strip().strip(".")
    return re.sub(r"\s+", " ", nome)[:120] or "sem titulo"


def extrair_links(texto: str) -> set[str]:
    return {m.strip() for m in _LINK.findall(texto)}


def _separar_frontmatter(texto: str) -> tuple[dict, str]:
    if not texto.startswith("---"):
        return {}, texto
    fim = texto.find("\n---", 3)
    if fim == -1:
        return {}, texto
    meta = {}
    for linha in texto[3:fim].strip().splitlines():
        if ":" in linha:
            chave, valor = linha.split(":", 1)
            meta[chave.strip()] = valor.strip()
    return meta, texto[fim + 4:].lstrip("\n")


def _montar(meta: dict, corpo: str) -> str:
    if not meta:
        return corpo
    linhas = "\n".join(f"{k}: {v}" for k, v in meta.items())
    return f"---\n{linhas}\n---\n{corpo}"


def ler(caminho: Path | str) -> Nota:
    caminho = Path(caminho)
    if not caminho.is_absolute():
        caminho = raiz() / caminho
    texto = caminho.read_text(encoding="utf-8")
    meta, corpo = _separar_frontmatter(texto)
    return Nota(caminho, caminho.stem, meta, corpo, hash_texto(texto))


def escrever(caminho: Path | str, texto: str, hash_esperado: str | None = None) -> Path:
    caminho = Path(caminho)
    if not caminho.is_absolute():
        caminho = raiz() / caminho
    if caminho.name in PROTEGIDAS and caminho.parent == raiz():
        raise PermissionError(f"{caminho.name} é protegida: só o dono do cérebro edita esta nota.")
    if hash_esperado is not None:
        atual = hash_texto(caminho.read_text(encoding="utf-8")) if caminho.exists() else ""
        if atual != hash_esperado:
            raise Conflito(f"{caminho.name} mudou desde a leitura; nada foi gravado.")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8", newline="\n")
    os.replace(tmp, caminho)
    return caminho


def todas() -> list[Path]:
    return sorted(p for p in raiz().rglob("*.md") if ".obsidian" not in p.parts)


def encontrar(titulo: str) -> Path | None:
    """Resolve um [[link]] como o Obsidian: pelo nome do arquivo, em qualquer pasta."""
    alvo = titulo.strip().lower()
    for p in todas():
        if p.stem.lower() == alvo:
            return p
    return None


def _adicionar_ao_indice(indice: str, titulo: str) -> None:
    """Acrescenta '- [[titulo]]' na seção ## Notas do índice, se ainda não estiver lá."""
    caminho = raiz() / f"{indice}.md"
    if not caminho.exists():
        escrever(caminho, f"---\ntipo: indice\n---\n# {indice}\n\nVolta para o [[00-mapa]].\n\n## Notas\n")
    nota = ler(caminho)
    if titulo in nota.links:
        return
    texto = caminho.read_text(encoding="utf-8").rstrip("\n") + f"\n- [[{titulo}]]\n"
    escrever(caminho, texto, hash_esperado=nota.hash)


def criar_nota(tipo: str, titulo: str, corpo: str, tags: list[str] | None = None,
               ligar: list[str] | None = None) -> Path:
    """Cria (ou completa) uma nota de pessoa/projeto/ideia/decisão já ligada ao índice."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo desconhecido: {tipo}. Use um de {', '.join(TIPOS)}.")
    pasta, indice = TIPOS[tipo]
    titulo = nome_arquivo(titulo)
    existente = encontrar(titulo)
    relacionados = "".join(f"- [[{l}]]\n" for l in (ligar or []) if l != titulo)

    if existente:
        # Não sobrescreve: acrescenta o que é novo no fim.
        nota = ler(existente)
        acrescimo = f"\n## {agora():%Y-%m-%d}\n{corpo.strip()}\n"
        if relacionados:
            acrescimo += relacionados
        texto = existente.read_text(encoding="utf-8").rstrip("\n") + "\n" + acrescimo
        escrever(existente, texto, hash_esperado=nota.hash)
        return existente

    meta = {"tipo": tipo, "criado": f"{agora():%Y-%m-%d}", "tags": f"[{', '.join(tags or [tipo])}]"}
    corpo = re.sub(r"^\s*#\s[^\n]*\n+", "", corpo, count=1)   # a IA às vezes já põe o título
    texto_corpo = f"# {titulo}\n\n{corpo.strip()}\n"
    if relacionados:
        texto_corpo += f"\n## Relacionado\n{relacionados}"
    texto_corpo += f"\nÍndice: [[{indice}]]\n"
    caminho = escrever(raiz() / pasta / f"{titulo}.md", _montar(meta, texto_corpo))
    _adicionar_ao_indice(indice, titulo)
    return caminho


def registrar_diario(texto: str, origem: str = "nexo") -> Path:
    """Acrescenta uma linha no diário de hoje. Tudo passa pelo diário primeiro."""
    hoje = agora()
    titulo = f"{hoje:%Y-%m-%d}"
    caminho = raiz() / "diario" / f"{titulo}.md"
    if not caminho.exists():
        escrever(caminho, f"---\ntipo: diario\n---\n# {titulo}\n\nÍndice: [[Diário]]\n\n## Registro\n")
        _adicionar_ao_indice("Diário", titulo)
    nota = ler(caminho)
    linhas = texto.strip().splitlines() or [""]
    entrada = f"- {hoje:%H:%M} ({origem}) {linhas[0]}\n" + "".join(f"  {l}\n" for l in linhas[1:])
    escrever(caminho, caminho.read_text(encoding="utf-8").rstrip("\n") + "\n" + entrada,
             hash_esperado=nota.hash)
    return caminho


def guardar(texto: str, origem: str = "nexo") -> Path:
    """Joga um pensamento na caixa de entrada para ser organizado depois."""
    momento = agora()
    resumo = nome_arquivo(" ".join(texto.split()[:6]))
    titulo = f"{momento:%Y-%m-%d %H%M%S} {resumo}"
    meta = {"tipo": "entrada", "criado": f"{momento:%Y-%m-%d %H:%M}", "origem": origem, "status": "pendente"}
    caminho = escrever(raiz() / "entrada" / f"{titulo}.md",
                       _montar(meta, f"{texto.strip()}\n\nÍndice: [[Entrada]]\n"))
    _adicionar_ao_indice("Entrada", titulo)
    return caminho


def pendentes() -> list[Nota]:
    return [n for n in (ler(p) for p in sorted((raiz() / "entrada").glob("*.md")))
            if n.meta.get("status") == "pendente"]


def marcar_processada(nota: Nota, ligacoes: list[str]) -> None:
    meta = dict(nota.meta, status="processado")
    corpo = nota.corpo.rstrip("\n")
    if ligacoes:
        corpo += "\n\nVirou: " + ", ".join(f"[[{l}]]" for l in ligacoes) + "\n"
    escrever(nota.caminho, _montar(meta, corpo + "\n"), hash_esperado=nota.hash)


def contexto_nucleo(dias_diario: int = 2) -> str:
    """Texto que entra em toda conversa: alma, usuário, memória e diário recente."""
    partes = []
    for nome in NUCLEO:
        p = raiz() / f"{nome}.md"
        if p.exists():
            partes.append(f"<nota titulo=\"{nome}\">\n{ler(p).corpo.strip()}\n</nota>")
    diarios = sorted((raiz() / "diario").glob("*.md"))[-dias_diario:]
    for p in diarios:
        partes.append(f"<nota titulo=\"{p.stem}\">\n{ler(p).corpo.strip()}\n</nota>")
    return "\n\n".join(partes)


def grafo() -> dict:
    """Nós e ligações do cérebro, no formato da visualização em grafo."""
    notas = [ler(p) for p in todas()]
    por_nome = {n.titulo.lower(): n.titulo for n in notas}
    nos, ligacoes = [], []
    for n in notas:
        pasta = n.caminho.parent.name if n.caminho.parent != raiz() else ""
        nos.append({"id": n.titulo, "tipo": n.meta.get("tipo") or pasta or "nota", "pasta": pasta})
        for alvo in sorted(n.links):
            if alvo.lower() in por_nome and por_nome[alvo.lower()] != n.titulo:
                ligacoes.append({"source": n.titulo, "target": por_nome[alvo.lower()]})
    return {"nodes": nos, "links": ligacoes}


def assinatura() -> tuple:
    """Muda sempre que alguma nota é criada, apagada ou alterada (para atualizar o grafo ao vivo)."""
    return tuple((p.as_posix(), p.stat().st_mtime) for p in todas())


def checar() -> dict[str, list[str]]:
    """Saúde do cérebro: links quebrados, notas soltas e notas sem metadados."""
    notas = [ler(p) for p in todas()]
    nomes = {n.titulo.lower() for n in notas}
    recebidos: dict[str, int] = {n.titulo.lower(): 0 for n in notas}
    quebrados, sem_meta = [], []
    for n in notas:
        for alvo in n.links:
            if alvo.lower() in nomes:
                recebidos[alvo.lower()] += 1
            else:
                quebrados.append(f"{n.rel} -> [[{alvo}]]")
        if not n.meta:
            sem_meta.append(n.rel)
    soltas = [n.rel for n in notas if not n.links and recebidos[n.titulo.lower()] == 0]
    return {"links_quebrados": quebrados, "notas_soltas": soltas, "sem_metadados": sem_meta}
