"""Abre o painel do Jarvis sem console. É o alvo do ícone JARVIS da Área de Trabalho.

Não depende da pasta de início do atalho: aberto como administrador, o Windows pode
ignorá-la e começar em C:\\Windows\\System32, e aí `python -m nexo` não acha o pacote.
"""
import os
import sys

PASTA = os.path.dirname(os.path.abspath(__file__))
os.chdir(PASTA)
sys.path.insert(0, PASTA)

from nexo.__main__ import main  # noqa: E402

main(["painel", *sys.argv[1:]])
