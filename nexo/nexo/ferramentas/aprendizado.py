"""Ferramentas de aprendizado: absorver repositórios do GitHub e pastas, e consultar o que foi aprendido."""
from .. import conhecimento
from . import Ferramenta


def aprender_do_link(origem: str) -> str:
    try:
        return conhecimento.aprender(origem)
    except conhecimento.ErroConhecimento as e:
        return str(e)


FERRAMENTAS = [
    Ferramenta("aprender_do_link",
               "Aprende o conteúdo de um repositório do GitHub (link github.com/dono/repo, também /tree/ramo/pasta "
               "ou /blob/ramo/arquivo) ou de uma pasta local: lê os textos e o código e guarda na base de "
               "conhecimento. Use sempre que o usuário mandar um link do GitHub, mesmo sem dizer 'aprenda', ou "
               "pedir para estudar um repositório. Reaprender o mesmo link atualiza só o que mudou.",
               aprender_do_link, {"origem": {"type": "string", "description": "Link do GitHub ou caminho de pasta"}},
               ["origem"]),
    Ferramenta("consultar_conhecimento",
               "Busca nos repositórios e pastas já aprendidos (base de conhecimento externa) e devolve trechos com "
               "a fonte. Use para perguntas sobre esses projetos, o código deles ou como algo funciona neles.",
               conhecimento.contexto, {"pergunta": {"type": "string"}}, ["pergunta"]),
    Ferramenta("listar_fontes", "Lista os repositórios e pastas que já aprendi.", conhecimento.listar),
    Ferramenta("esquecer_fonte", "Apaga da base de conhecimento uma fonte aprendida (pelo título, ex.: dono/repo).",
               conhecimento.esquecer, {"titulo": {"type": "string"}}, ["titulo"], confirmar=True),
]
