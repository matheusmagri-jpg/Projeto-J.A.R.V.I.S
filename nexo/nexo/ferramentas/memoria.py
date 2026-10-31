"""Ferramentas para consultar e alimentar o cérebro."""
from .. import busca, cerebro
from . import Ferramenta


def buscar_cerebro(consulta: str) -> str:
    achados = busca.buscar(consulta, limite=5)
    if not achados:
        return "Nada encontrado no cérebro."
    return "\n".join(f"[[{r.titulo}]]: {r.trecho}" for r in achados)


def ler_nota(titulo: str) -> str:
    caminho = cerebro.encontrar(titulo.strip("[]"))
    if not caminho:
        return f"Não existe nota chamada {titulo}."
    return cerebro.ler(caminho).corpo[:4000]


def guardar(texto: str) -> str:
    caminho = cerebro.guardar(texto, origem="conversa")
    return f"Guardado na caixa de entrada como [[{caminho.stem}]]."


def criar_nota(tipo: str, titulo: str, conteudo: str) -> str:
    caminho = cerebro.criar_nota(tipo, titulo, conteudo)
    return f"Nota [[{caminho.stem}]] salva em {cerebro.TIPOS[tipo][0]}."


FERRAMENTAS = [
    Ferramenta(
        nome="buscar_cerebro",
        descricao="Procura nas notas do cérebro (pessoas, projetos, ideias, decisões, diário). "
                  "Use antes de responder qualquer coisa sobre o usuário, os projetos ou o passado.",
        parametros={"consulta": {"type": "string", "description": "Palavras-chave em português"}},
        obrigatorios=["consulta"],
        executar=buscar_cerebro,
    ),
    Ferramenta(
        nome="ler_nota",
        descricao="Lê uma nota inteira do cérebro pelo título (o que aparece entre [[ ]]).",
        parametros={"titulo": {"type": "string", "description": "Título exato da nota"}},
        obrigatorios=["titulo"],
        executar=ler_nota,
    ),
    Ferramenta(
        nome="guardar",
        descricao="Guarda algo que o usuário pediu para lembrar na caixa de entrada do cérebro. "
                  "Use quando ele disser 'guarda isso', 'anota', 'lembra que'.",
        parametros={"texto": {"type": "string", "description": "O que guardar, com contexto suficiente"}},
        obrigatorios=["texto"],
        executar=guardar,
    ),
    Ferramenta(
        nome="criar_nota",
        descricao="Cria ou completa uma nota organizada de pessoa, projeto, ideia ou decisão. "
                  "Se a nota já existir, o conteúdo é acrescentado no fim.",
        parametros={
            "tipo": {"type": "string", "enum": list(cerebro.TIPOS)},
            "titulo": {"type": "string", "description": "Título curto; reuse o título de uma nota existente"},
            "conteudo": {"type": "string", "description": "Markdown; cite outras notas como [[Título]]"},
        },
        obrigatorios=["tipo", "titulo", "conteudo"],
        executar=criar_nota,
    ),
]
