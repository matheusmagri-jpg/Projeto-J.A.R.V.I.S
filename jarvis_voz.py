#!/usr/bin/env python3
"""Fala um texto com a voz do JARVIS em pt-BR (ElevenLabs ou Fish Audio).

Uso:
  python jarvis_voz.py "Bom dia, senhor."
  python jarvis_voz.py --arquivo briefing.txt
  python jarvis_voz.py --motor fish "Às suas ordens, senhor."

Variáveis de ambiente:
  ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
  FISH_API_KEY, FISH_VOICE_ID   (reference_id do modelo de voz no fish.audio)
"""
import argparse
import os
import platform
import re
import subprocess
import sys

import requests


def para_fala(texto: str) -> str:
    """Texto para ouvir: "R$ 150,50" vira "150,50 reais", "%" vira "por cento"."""
    t = re.sub(r"R\$\s?([\d.]+)(,\d+)?", lambda m: m.group(1) + (m.group(2) if m.group(2) and m.group(2) != ",00" else "") + " reais", texto)
    t = re.sub(r"(\d+(?:,\d+)?)\s?%", r"\1 por cento", t)
    t = re.sub(r"\(ex\.:\s*", ", por exemplo, ", t)
    t = t.replace("(", "").replace(")", "").replace("—", ",").replace("–", ",").replace(";", ".")
    t = re.sub(r"\b1 reais", "1 real", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([,.])", r"\1", t)
    return re.sub(r",\s*,", ",", t).strip()


def tts_elevenlabs(texto: str) -> bytes:
    voz = os.environ["ELEVENLABS_VOICE_ID"]
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voz}",
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Accept": "audio/mpeg"},
        json={
            "text": para_fala(texto),
            "model_id": "eleven_multilingual_v2",
            # Estável e contido: o tom calmo de mordomo vem de pouca variação.
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.85, "style": 0.2, "use_speaker_boost": True, "speed": 0.92},
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.content


def tts_fish(texto: str) -> bytes:
    r = requests.post(
        "https://api.fish.audio/v1/tts",
        headers={"Authorization": f"Bearer {os.environ['FISH_API_KEY']}", "model": os.environ.get("FISH_MODELO", "s2.1-pro-free")},
        json={"text": para_fala(texto), "reference_id": os.environ.get("FISH_VOICE_ID", "fee533e18ed246f7bcbe4f2764fe900b"), "format": "mp3"},
        timeout=120,
    )
    r.raise_for_status()
    return r.content


def tocar(caminho: str) -> None:
    sistema = platform.system()
    if sistema == "Darwin":
        subprocess.run(["afplay", caminho])
    elif sistema == "Windows":
        os.startfile(caminho)  # abre no player padrão
    else:
        for cmd in (["mpg123", "-q", caminho], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", caminho]):
            try:
                subprocess.run(cmd)
                return
            except FileNotFoundError:
                continue
        print(f"Áudio salvo em {caminho} (instale mpg123 ou ffplay para tocar).")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("texto", nargs="?")
    p.add_argument("--arquivo")
    p.add_argument("--motor", choices=["elevenlabs", "fish"], default=os.environ.get("JARVIS_MOTOR", "elevenlabs"))
    p.add_argument("--saida", default="jarvis.mp3")
    p.add_argument("--nao-tocar", action="store_true")
    a = p.parse_args()

    texto = open(a.arquivo, encoding="utf-8").read() if a.arquivo else a.texto
    if not texto:
        sys.exit("Passe um texto ou --arquivo.")

    audio = tts_fish(texto) if a.motor == "fish" else tts_elevenlabs(texto)
    with open(a.saida, "wb") as f:
        f.write(audio)
    if not a.nao_tocar:
        tocar(a.saida)


if __name__ == "__main__":
    main()
