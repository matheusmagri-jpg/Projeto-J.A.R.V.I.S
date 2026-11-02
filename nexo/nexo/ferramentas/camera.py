"""Ver pela webcam: "o que você está vendo?", "que objeto é este?".

Uma foto só, tirada na hora, nunca guardada em disco. Com o Gemini disponível a foto vai para ele, como na
ferramenta ver_tela. No modo privado (ou sem Gemini) vai para um modelo de visão do Ollama, no próprio PC:
NEXO_OLLAMA_VISAO (padrão llava; instale com `ollama pull llava`).
"""
from __future__ import annotations

import base64
import json
import os
from urllib import error, request

from .. import config, ia
from . import Ferramenta

MODELO_VISAO = os.environ.get("NEXO_OLLAMA_VISAO", "llava")
CAMERA = int(os.environ.get("NEXO_CAMERA", "0"))   # 0 = a primeira webcam do Windows


def foto_jpg(lado_maximo: int = 1280) -> bytes:
    import cv2
    captura = cv2.VideoCapture(CAMERA, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
    try:
        if not captura.isOpened():
            raise RuntimeError("não achei a webcam (está ligada? outro programa está usando?)")
        quadro = None
        for _ in range(8):            # os primeiros quadros saem escuros enquanto a câmera ajusta a luz
            ok, lido = captura.read()
            if ok:
                quadro = lido
        if quadro is None:
            raise RuntimeError("a webcam não entregou imagem")
    finally:
        captura.release()
    altura, largura = quadro.shape[:2]
    escala = lado_maximo / max(altura, largura)
    if escala < 1:
        quadro = cv2.resize(quadro, (int(largura * escala), int(altura * escala)))
    ok, jpg = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("não consegui converter a foto")
    return jpg.tobytes()


def _ollama_visao(jpg: bytes, pergunta: str) -> str:
    corpo = json.dumps({"model": MODELO_VISAO, "stream": False, "messages": [{
        "role": "user", "content": f"Responda em português do Brasil, curto. {pergunta}",
        "images": [base64.b64encode(jpg).decode()]}]}).encode("utf-8")
    pedido = request.Request(f"{config.OLLAMA_URL}/api/chat", data=corpo, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(pedido, timeout=config.OLLAMA_TIMEOUT) as r:
            return (json.loads(r.read()).get("message") or {}).get("content", "").strip()
    except error.HTTPError as e:
        if e.code == 404:
            return (f"O modelo de visão local ({MODELO_VISAO}) não está instalado. Para ver pela câmera sem a "
                    f"nuvem, rode: ollama pull {MODELO_VISAO}")
        raise


def ver_camera(pergunta: str = "O que você está vendo?") -> str:
    try:
        jpg = foto_jpg()
    except (RuntimeError, ImportError) as e:
        return f"Não consegui usar a câmera: {e}."
    pedido = f"Esta foto acabou de ser tirada pela webcam do computador do usuário. {pergunta}"
    if not ia.privado_ativo() and "gemini" in ia.disponiveis():
        from google.genai import types
        r = ia.gerar_gemini([types.Part.from_bytes(data=jpg, mime_type="image/jpeg"),
                             f"Responda em português, curto: {pedido}"], types.GenerateContentConfig())
        return (r.text or "").strip() or "Não consegui interpretar a imagem."
    return _ollama_visao(jpg, pedido) or "Não consegui interpretar a imagem."


FERRAMENTAS = [
    Ferramenta("ver_camera",
               "Tira uma foto com a webcam e responde sobre ela ('o que você está vendo?', 'que objeto é este?', "
               "'como estou?'). Só use quando o usuário pedir para olhar pela câmera. A foto vai ao Gemini, ou ao "
               "modelo local no modo privado, e não é guardada.",
               ver_camera, {"pergunta": {"type": "string"}}, ["pergunta"], confirmar=True),
]
