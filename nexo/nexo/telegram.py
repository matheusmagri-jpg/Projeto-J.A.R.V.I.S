"""Conversar com o Jarvis pelo Telegram, de qualquer lugar.

Crie um bot com o @BotFather e ponha o token em NEXO_TELEGRAM_TOKEN. Mande qualquer mensagem ao bot: ele
responde com o número do seu chat; ponha esse número em NEXO_TELEGRAM_CHAT. Só esse chat é atendido: o bot
pode agir no PC, então mensagem de qualquer outra pessoa é ignorada.

Quem roda a vigia (o painel ou `nexo vigia`) roda o bot: uma vigia por PC garante um bot só, e o Telegram
recusa duas leituras do mesmo token ao mesmo tempo. Os avisos da vigia (lembretes, bom dia, tarefas) também
chegam aqui.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.request

from . import cerebro, config, ia

API = "https://api.telegram.org"
LIMITE_TEXTO = 4000          # o Telegram aceita 4096 caracteres por mensagem
IDADE_MAXIMA = 600           # mensagens mandadas com o PC desligado não são executadas horas depois
ESPERA_CONFIRMACAO = 120


def configurado() -> bool:
    return bool(config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT)


def _chamar(metodo: str, espera: float = 30, **parametros) -> dict:
    """Chama a API do bot. `espera` é o limite da conexão; o `timeout` do getUpdates vai nos parâmetros."""
    corpo = json.dumps(parametros).encode("utf-8")
    pedido = urllib.request.Request(f"{API}/bot{config.TELEGRAM_TOKEN}/{metodo}", data=corpo,
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=espera) as r:
        resposta = json.loads(r.read())
    if not resposta.get("ok"):
        raise RuntimeError(resposta.get("description", "erro do Telegram"))
    return resposta["result"]


def _baixar_arquivo(file_id: str) -> bytes:
    caminho = _chamar("getFile", file_id=file_id)["file_path"]
    with urllib.request.urlopen(f"{API}/file/bot{config.TELEGRAM_TOKEN}/{caminho}", timeout=60) as r:
        return r.read(20_000_000)


def enviar(texto: str, chat: str | int | None = None) -> bool:
    """Manda um texto ao chat do usuário (ou ao chat indicado). False se não deu."""
    if not config.TELEGRAM_TOKEN or not (chat or config.TELEGRAM_CHAT):
        return False
    try:
        for i in range(0, max(len(texto), 1), LIMITE_TEXTO):
            _chamar("sendMessage", chat_id=chat or config.TELEGRAM_CHAT, text=texto[i:i + LIMITE_TEXTO] or "…")
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _enviar_audio(caminho_mp3: str) -> None:
    """Resposta falada com a mesma voz do painel (sendAudio aceita o mp3 do jeito que sai do voz.py)."""
    import uuid
    limite = "nexo" + uuid.uuid4().hex
    with open(caminho_mp3, "rb") as f:
        audio = f.read()
    corpo = (f"--{limite}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{config.TELEGRAM_CHAT}\r\n"
             f"--{limite}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{config.NOME}.mp3\"\r\n"
             "Content-Type: audio/mpeg\r\n\r\n").encode("utf-8") + audio + f"\r\n--{limite}--\r\n".encode()
    pedido = urllib.request.Request(f"{API}/bot{config.TELEGRAM_TOKEN}/sendAudio", data=corpo,
                                    headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
    urllib.request.urlopen(pedido, timeout=60).read()


class Bot:
    """Lê as mensagens (uma thread) e responde uma de cada vez (outra thread)."""

    def __init__(self):
        self.ativo = True
        self.fila: queue.Queue[dict] = queue.Queue()
        self._offset = 0
        self._conversa = None
        self._esperando_confirmacao = False

    # ---------- leitura ----------

    def _ler(self) -> None:
        falhas = 0
        while self.ativo:
            try:
                atualizacoes = _chamar("getUpdates", espera=70, offset=self._offset, timeout=50)
                falhas = 0
            except (OSError, RuntimeError, ValueError) as e:
                falhas += 1
                if falhas in (1, 10):
                    print(f"[telegram] sem conexão: {type(e).__name__}: {e}")
                time.sleep(min(60, 3 * falhas))
                continue
            for a in atualizacoes:
                self._offset = a["update_id"] + 1
                msg = a.get("message")
                if msg:
                    self._receber(msg)

    def _receber(self, msg: dict) -> None:
        chat = str(msg.get("chat", {}).get("id", ""))
        if not config.TELEGRAM_CHAT:
            # Primeira configuração: diz o número do chat e não executa nada.
            enviar(f"Olá. Para eu atender este chat, coloque NEXO_TELEGRAM_CHAT={chat} no .env do Jarvis e "
                   "reinicie o painel.", chat)
            return
        if chat != str(config.TELEGRAM_CHAT):
            return                                    # outra pessoa: ignorada em silêncio
        if time.time() - msg.get("date", 0) > IDADE_MAXIMA:
            return
        self.fila.put(msg)

    # ---------- resposta ----------

    def _texto_da_mensagem(self, msg: dict) -> tuple[str, bool]:
        """(texto, veio por voz). Áudio é transcrito do mesmo jeito que a fala do painel."""
        if msg.get("text"):
            return msg["text"].strip(), False
        audio = msg.get("voice") or msg.get("audio")
        if audio:
            from . import voz
            dados = _baixar_arquivo(audio["file_id"])
            return voz.transcrever(dados, audio.get("mime_type") or "audio/ogg").strip(), True
        return "", False

    def _confirmar(self, pergunta: str) -> bool:
        enviar(f"{pergunta}\nResponda sim ou não.")
        self._esperando_confirmacao = True
        try:
            msg = self.fila.get(timeout=ESPERA_CONFIRMACAO)
        except queue.Empty:
            enviar("Sem resposta: não executei.")
            return False
        finally:
            self._esperando_confirmacao = False
        texto, _ = self._texto_da_mensagem(msg)
        from . import voz
        return voz.e_sim(texto)

    def _atender(self, msg: dict) -> None:
        from .conversa import Conversa
        if self._conversa is None:
            self._conversa = Conversa(modo="rapido", confirmar=self._confirmar)
        try:
            texto, por_voz = self._texto_da_mensagem(msg)
        except Exception as e:
            enviar(f"Não consegui entender o áudio: {type(e).__name__}.")
            return
        if not texto:
            enviar("Mande texto ou áudio, senhor.")
            return
        if texto.lower() in ("/start", "/novo", "/limpar"):
            self._conversa = Conversa(modo="rapido", confirmar=self._confirmar)
            enviar(f"Às ordens, {config.TRATAMENTO}.")
            return
        _chamar_sem_falha("sendChatAction", chat_id=config.TELEGRAM_CHAT, action="typing")
        try:
            resposta = self._conversa.enviar(texto).texto
        except (ia.SemIA, ia.ModoPrivado) as e:
            resposta = str(e)
        except Exception as e:
            resposta = f"Algo falhou: {type(e).__name__}: {e}"
        if not ia.privado_ativo():
            cerebro.registrar_diario(f"Pelo Telegram: {texto[:200]} → {resposta[:300]}", origem="telegram")
        enviar(resposta)
        if por_voz:
            try:
                from . import voz
                caminho = voz.gerar_mp3(voz.para_fala(resposta))
                if caminho:
                    _enviar_audio(caminho)
            except Exception as e:
                print(f"[telegram] áudio da resposta falhou: {type(e).__name__}: {e}")

    def _responder(self) -> None:
        while self.ativo:
            try:
                msg = self.fila.get(timeout=5)
            except queue.Empty:
                continue
            try:
                self._atender(msg)
            except Exception as e:
                print(f"[telegram] {type(e).__name__}: {e}")

    def iniciar(self) -> None:
        threading.Thread(target=self._ler, daemon=True, name="telegram-leitura").start()
        threading.Thread(target=self._responder, daemon=True, name="telegram-resposta").start()


def _chamar_sem_falha(metodo: str, **parametros) -> None:
    try:
        _chamar(metodo, espera=10, **parametros)
    except (OSError, RuntimeError, ValueError):
        pass


def iniciar() -> Bot | None:
    """Sobe o bot se houver token. Sem NEXO_TELEGRAM_CHAT ele só responde com o número do chat."""
    if not config.TELEGRAM_TOKEN:
        return None
    bot = Bot()
    bot.iniciar()
    return bot
