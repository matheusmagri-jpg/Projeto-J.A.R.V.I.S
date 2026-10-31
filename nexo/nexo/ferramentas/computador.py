"""Ferramentas do computador: hora, sites, aplicativos, playlists e desligamento."""
import datetime as dt
import os
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser

from .. import config
from . import Ferramenta

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]

# Só abre aplicativos desta lista: a IA nunca executa um comando arbitrário.
APPS = {
    "calculadora": ["calc.exe"],
    "bloco de notas": ["notepad.exe"],
    "explorador": ["explorer.exe"],
    "paint": ["mspaint.exe"],
    "vscode": ["code"],
    "word": ["winword"],
    "excel": ["excel"],
    "obsidian": ["obsidian://open"],
}

PLAYLISTS = {
    "foco": "lofi para foco e concentração",
    "estudo": "música para estudar sem letra",
    "treino": "playlist treino academia",
    "relaxar": "música calma para relaxar",
}


def hora_data() -> str:
    agora = dt.datetime.now()
    return (f"{DIAS[agora.weekday()]}, {agora.day} de {MESES[agora.month - 1]} de {agora.year}, "
            f"{agora:%H:%M}.")


def abrir_site(endereco: str) -> str:
    if not endereco.startswith(("http://", "https://")):
        endereco = "https://" + endereco
    webbrowser.open(endereco)
    return f"Abri {endereco}."


def pesquisar(termos: str, onde: str = "google") -> str:
    q = urllib.parse.quote_plus(termos)
    url = {"youtube": f"https://www.youtube.com/results?search_query={q}"}.get(
        onde, f"https://www.google.com/search?q={q}")
    webbrowser.open(url)
    return f"Abri a pesquisa por '{termos}' no {onde}."


def tocar_playlist(tipo: str) -> str:
    busca = PLAYLISTS.get(tipo, tipo)
    pesquisar(busca, "youtube")
    return f"Abri uma playlist de {tipo} no YouTube."


def abrir_app(nome: str) -> str:
    comando = APPS.get(nome.lower().strip())
    if not comando:
        return f"Não conheço o aplicativo '{nome}'. Posso abrir: {', '.join(APPS)}."
    alvo = comando[0]
    caminho = shutil.which(alvo)
    if "://" in alvo:
        webbrowser.open(alvo)
    elif caminho:
        subprocess.Popen([caminho, *comando[1:]])
    elif sys.platform == "win32":
        os.startfile(alvo)  # deixa o Windows resolver (ex.: winword)
    else:
        return f"Não encontrei {nome} neste computador."
    return f"Abri {nome}."


def agendar_desligamento(minutos: int = 1) -> str:
    segundos = max(60, int(minutos) * 60)
    subprocess.run(["shutdown", "/s", "/t", str(segundos)], check=False, **config.SEM_JANELA)
    return f"O computador desliga em {segundos // 60} minuto(s). Para cancelar, peça para cancelar o desligamento."


def cancelar_desligamento() -> str:
    subprocess.run(["shutdown", "/a"], check=False, **config.SEM_JANELA)
    return "Desligamento cancelado."


FERRAMENTAS = [
    Ferramenta("hora_data", "Diz o dia da semana, a data e a hora atuais.", hora_data),
    Ferramenta("abrir_site", "Abre um site no navegador.", abrir_site,
               {"endereco": {"type": "string", "description": "Endereço, ex.: youtube.com"}}, ["endereco"]),
    Ferramenta("pesquisar", "Abre uma pesquisa no Google ou no YouTube no navegador.", pesquisar,
               {"termos": {"type": "string"},
                "onde": {"type": "string", "enum": ["google", "youtube"]}}, ["termos"]),
    Ferramenta("tocar_playlist", "Abre uma playlist no YouTube conforme o momento: foco, estudo, treino ou relaxar.",
               tocar_playlist, {"tipo": {"type": "string", "description": "foco, estudo, treino, relaxar ou outro estilo"}},
               ["tipo"]),
    Ferramenta("abrir_app", f"Abre um aplicativo do computador. Disponíveis: {', '.join(APPS)}.", abrir_app,
               {"nome": {"type": "string", "enum": list(APPS)}}, ["nome"]),
    Ferramenta("agendar_desligamento", "Agenda o desligamento do computador.", agendar_desligamento,
               {"minutos": {"type": "integer", "description": "Daqui a quantos minutos (mínimo 1)"}}, [],
               confirmar=True),
    Ferramenta("cancelar_desligamento", "Cancela um desligamento agendado.", cancelar_desligamento),
]
