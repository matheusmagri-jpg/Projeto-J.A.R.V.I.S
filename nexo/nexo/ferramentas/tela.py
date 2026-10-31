"""Agir na tela: clicar no que o usuário descrever, digitar e apertar atalhos de teclado.

Antes de agir, o painel sai da frente (minimiza) para a ação cair no programa que o usuário
estava usando. Para clicar, uma foto da tela vai ao Gemini, que devolve onde está o alvo.
Tudo aqui pede confirmação: são ações no computador do usuário.
"""
import ctypes
import json
import os
import time

from .. import config, ia
from . import Ferramenta

SW_MINIMIZE = 6
# Teclas com nome, além de letras, números e f1–f24 (códigos de tecla virtual do Windows).
TECLAS = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "espaco": 0x20, "espaço": 0x20, "backspace": 0x08,
    "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "cima": 0x26, "baixo": 0x28, "esquerda": 0x25, "direita": 0x27,
}


def _windows() -> bool:
    return os.name == "nt"


def _sair_da_frente() -> None:
    """Minimiza a janela do painel, se estiver na frente, para a ação ir ao programa de trás."""
    from ..interface import tecla
    hwnd = tecla.janela(config.NOME)
    if hwnd and tecla.em_frente(hwnd):
        ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
        time.sleep(0.5)


def _janela_em_uso() -> str | None:
    """Título da janela que vai receber a ação. None quando é o próprio painel (agir ali seria um erro)."""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    tamanho = user32.GetWindowTextLengthW(hwnd)
    texto = ctypes.create_unicode_buffer(tamanho + 1)
    user32.GetWindowTextW(hwnd, texto, tamanho + 1)
    return None if texto.value == config.NOME else (texto.value or "janela sem título")


def _pixels_reais():
    """Coordenadas em pixels físicos nesta thread, iguais às da captura (telas com escala 125%, 150%...)."""
    try:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # por monitor, v2
    except (AttributeError, OSError):
        pass


# ---------- teclado e mouse (SendInput) ----------

class _Tecla(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _Mouse(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _Uniao(ctypes.Union):
    _fields_ = [("ki", _Tecla), ("mi", _Mouse), ("_folga", ctypes.c_byte * 32)]


class _Entrada(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _Uniao)]


def _enviar(*entradas: _Entrada) -> None:
    lista = (_Entrada * len(entradas))(*entradas)
    ctypes.windll.user32.SendInput(len(entradas), lista, ctypes.sizeof(_Entrada))


def _tecla(vk: int = 0, scan: int = 0, flags: int = 0) -> _Entrada:
    e = _Entrada(type=1)
    e.u.ki = _Tecla(vk, scan, flags, 0, 0)
    return e


def _clique(duplo: bool = False, direito: bool = False) -> None:
    desce, sobe = (0x0008, 0x0010) if direito else (0x0002, 0x0004)
    for _ in range(2 if duplo else 1):
        a, b = _Entrada(type=0), _Entrada(type=0)
        a.u.mi = _Mouse(0, 0, 0, desce, 0, 0)
        b.u.mi = _Mouse(0, 0, 0, sobe, 0, 0)
        _enviar(a, b)
        time.sleep(0.05)


def _escrever(texto: str) -> None:
    """Digita qualquer caractere (acentos, emoji) como Unicode, sem depender do layout do teclado."""
    dados = texto.replace("\r\n", "\n").encode("utf-16-le")
    for i in range(0, len(dados), 2):
        codigo = int.from_bytes(dados[i:i + 2], "little")
        if codigo == 0x0A:
            _enviar(_tecla(0x0D), _tecla(0x0D, flags=0x0002))
            continue
        _enviar(_tecla(scan=codigo, flags=0x0004), _tecla(scan=codigo, flags=0x0004 | 0x0002))
        time.sleep(0.004)


def interpretar_teclas(combinacao: str) -> list[int]:
    codigos = []
    for parte in (p.strip().lower() for p in combinacao.replace(" ", "").split("+")):
        if parte in TECLAS:
            codigos.append(TECLAS[parte])
        elif len(parte) == 1 and parte.isalnum():
            codigos.append(ord(parte.upper()))
        elif parte[:1] == "f" and parte[1:].isdigit() and 1 <= int(parte[1:]) <= 24:
            codigos.append(0x6F + int(parte[1:]))
        else:
            raise ValueError(parte)
    return codigos


# ---------- localizar na tela ----------

def localizar(alvo: str) -> tuple[int, int, str] | None:
    """Pergunta ao Gemini onde está o alvo na tela. Devolve (x, y) em pixels e o que ele viu lá."""
    import io

    from google.genai import types
    from PIL import ImageGrab
    _pixels_reais()
    imagem = ImageGrab.grab(all_screens=False)
    largura, altura = imagem.size
    imagem.thumbnail((1600, 1600))
    saida = io.BytesIO()
    imagem.save(saida, format="PNG", optimize=True)
    pedido = (f"Esta é a tela do computador do usuário. Encontre: {alvo}.\n"
              'Responda só com JSON: {"achou": true|false, "ponto": [y, x], "descricao": "o que está nesse ponto"}. '
              "O ponto é o centro do elemento, com y e x normalizados de 0 a 1000. "
              "Se não houver nada que corresponda com segurança, use achou=false.")
    r = ia.gerar_gemini([types.Part.from_bytes(data=saida.getvalue(), mime_type="image/png"), pedido],
                        types.GenerateContentConfig(response_mime_type="application/json"))
    try:
        dados = json.loads(r.text or "{}")
        if not dados.get("achou"):
            return None
        y, x = (float(v) for v in dados["ponto"])
    except (ValueError, KeyError, TypeError):
        return None
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None
    return round(x / 1000 * largura), round(y / 1000 * altura), str(dados.get("descricao", alvo))


# ---------- ferramentas ----------

def clicar_na_tela(alvo: str, duplo: bool = False, direito: bool = False) -> str:
    if not _windows():
        return "Agir na tela só funciona no Windows."
    _sair_da_frente()
    achado = localizar(alvo)
    if not achado:
        return f"Não encontrei '{alvo}' na tela. Nada foi clicado."
    x, y, descricao = achado
    _pixels_reais()
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(0.1)
    _clique(duplo=duplo, direito=direito)
    tipo = "Dei um duplo clique" if duplo else "Cliquei com o botão direito" if direito else "Cliquei"
    return f"{tipo} em {descricao} (posição {x}, {y}, janela '{_janela_em_uso() or config.NOME}')."


def digitar_texto(texto: str, enter: bool = False) -> str:
    if not _windows():
        return "Agir na tela só funciona no Windows."
    if not texto:
        return "Nada para digitar."
    _sair_da_frente()
    janela = _janela_em_uso()
    if janela is None:
        return "O painel continua na frente; não digitei nada. Clique no programa certo e peça de novo."
    _escrever(texto)
    if enter:
        _enviar(_tecla(0x0D), _tecla(0x0D, flags=0x0002))
    return f"Digitei {len(texto)} caractere(s){' e apertei Enter' if enter else ''} em '{janela}'."


def apertar_teclas(combinacao: str) -> str:
    if not _windows():
        return "Agir na tela só funciona no Windows."
    try:
        codigos = interpretar_teclas(combinacao)
    except ValueError as e:
        return f"Tecla desconhecida: {e}. Use nomes como ctrl, alt, shift, win, enter, esc, tab, f5 ou letras."
    _sair_da_frente()
    janela = _janela_em_uso()
    if janela is None:
        return "O painel continua na frente; não apertei nada. Clique no programa certo e peça de novo."
    _enviar(*[_tecla(c) for c in codigos])
    _enviar(*[_tecla(c, flags=0x0002) for c in reversed(codigos)])
    return f"Apertei {combinacao} em '{janela}'."


FERRAMENTAS = [
    Ferramenta("clicar_na_tela",
               "Clica num elemento visível na tela do usuário descrito em palavras (ex.: 'botão Salvar', "
               "'campo de busca do Chrome', 'ícone da lixeira'). Tira uma foto da tela, o Gemini acha o "
               "elemento e o mouse clica no centro dele. Use só quando o usuário pedir para clicar ou "
               "operar um programa. Descreva o alvo de forma específica.",
               clicar_na_tela,
               {"alvo": {"type": "string", "description": "O que clicar, descrito como aparece na tela"},
                "duplo": {"type": "boolean", "description": "Duplo clique (abrir arquivo, por exemplo)"},
                "direito": {"type": "boolean", "description": "Clique com o botão direito"}},
               ["alvo"], confirmar=True),
    Ferramenta("digitar_texto",
               "Digita um texto no programa que está em uso (onde está o cursor), como se fosse o teclado. "
               "Use depois de clicar no campo certo, quando o usuário pedir para escrever algo num programa.",
               digitar_texto,
               {"texto": {"type": "string"},
                "enter": {"type": "boolean", "description": "Apertar Enter no fim"}},
               ["texto"], confirmar=True),
    Ferramenta("apertar_teclas",
               "Aperta um atalho de teclado no programa em uso, como 'ctrl+s', 'alt+tab', 'ctrl+shift+t', "
               "'f5' ou 'enter'.",
               apertar_teclas,
               {"combinacao": {"type": "string", "description": "Teclas separadas por +"}},
               ["combinacao"], confirmar=True),
]
