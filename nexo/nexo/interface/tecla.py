"""Atalho de teclado global: traz o painel para a frente de qualquer programa.

Usa o RegisterHotKey do Windows (sem bibliotecas extras). A combinação vem de config.TECLA,
no formato "ctrl+alt+j" (modificadores: ctrl, alt, shift, win; tecla: letra, número, f1–f24, espaco).
"""
import ctypes
import os
import threading

MODIFICADORES = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
SEM_REPETIR = 0x4000    # segurar a tecla não dispara de novo
WM_HOTKEY = 0x0312
SW_RESTORE = 9


def interpretar(combinacao: str) -> tuple[int, int]:
    """"ctrl+alt+j" -> (modificadores, código da tecla). Erro de digitação vira ValueError."""
    modificadores, tecla = 0, None
    for parte in (p.strip().lower() for p in combinacao.split("+")):
        if parte in MODIFICADORES:
            modificadores |= MODIFICADORES[parte]
        elif len(parte) == 1 and parte.isalnum():
            tecla = ord(parte.upper())
        elif parte[:1] == "f" and parte[1:].isdigit() and 1 <= int(parte[1:]) <= 24:
            tecla = 0x6F + int(parte[1:])
        elif parte in ("espaco", "espaço", "space"):
            tecla = 0x20
        else:
            raise ValueError(f"Tecla desconhecida no atalho: {parte!r}")
    if tecla is None or not modificadores:
        raise ValueError(f"O atalho precisa de um modificador e uma tecla (ex.: ctrl+alt+j), veio {combinacao!r}")
    return modificadores | SEM_REPETIR, tecla


def legivel(combinacao: str) -> str:
    return "+".join(p.strip().capitalize() for p in combinacao.split("+"))


def escutar(combinacao: str, ao_apertar) -> bool:
    """Registra o atalho numa thread com fila de mensagens própria.

    Devolve False fora do Windows ou se outro programa já usa a combinação.
    """
    if os.name != "nt":
        return False
    modificadores, tecla = interpretar(combinacao)
    pronto, resultado = threading.Event(), {"ok": False}

    def laco():
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        # Sem janela: a mensagem do atalho chega na fila desta thread.
        resultado["ok"] = bool(user32.RegisterHotKey(None, 1, modificadores, tecla))
        pronto.set()
        if not resultado["ok"]:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    ao_apertar()
                except Exception as e:   # um erro aqui não pode matar o atalho
                    print(f"[atalho] {type(e).__name__}: {e}")

    threading.Thread(target=laco, daemon=True, name="atalho-global").start()
    pronto.wait(5)
    return resultado["ok"]


# ---------- janela do painel ----------

def janela(titulo: str) -> int | None:
    """A janela visível cujo título é exatamente o nome do assistente (a janela de app do Chrome)."""
    if os.name != "nt":
        return None
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    achada: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            tamanho = user32.GetWindowTextLengthW(hwnd)
            if tamanho == len(titulo):
                texto = ctypes.create_unicode_buffer(tamanho + 1)
                user32.GetWindowTextW(hwnd, texto, tamanho + 1)
                if texto.value == titulo:
                    achada.append(hwnd)
                    return False
        return True

    user32.EnumWindows(cada, 0)
    return achada[0] if achada else None


def em_frente(hwnd: int) -> bool:
    return os.name == "nt" and ctypes.windll.user32.GetForegroundWindow() == hwnd


def trazer(hwnd: int) -> bool:
    """Restaura se estiver minimizada e põe na frente. Quem recebeu o atalho tem permissão para isso."""
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    return bool(user32.SetForegroundWindow(hwnd))
