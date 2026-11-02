"""Miniatura do Habblaud no painel.

O Habblaud responde com X-Frame-Options: DENY, então o painel não consegue mostrá-lo num iframe.
Este proxy local (porta do painel + 1) repassa só leituras (GET/HEAD) ao Habblaud e troca o DENY por
um frame-ancestors que aceita apenas o painel. Sem POST: a miniatura não consegue mudar nada no Habblaud.
"""
from __future__ import annotations

import html
import http.client
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .. import config

# O Docker Desktop não abre sozinho com o Windows: sem ele o container do Habblaud fica parado e a
# miniatura só mostrava "fora do ar". Agora o painel liga o Docker e o container quando precisa.
DOCKER_DESKTOP = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
PASTA_HABBLAUD = config.RAIZ.parent / "habblaud"
_ligando = threading.Lock()
_estado = "Ligando o Habblaud…"


def _responde() -> bool:
    destino = urlsplit(config.HABBLAUD_URL)
    conexao = http.client.HTTPConnection(destino.hostname, destino.port or 80, timeout=3)
    try:
        conexao.request("HEAD", "/")
        return conexao.getresponse().status < 500
    except OSError:
        return False
    finally:
        conexao.close()


def _docker(*args: str, timeout: float = 60, cwd: Path | None = None) -> bool:
    try:
        return subprocess.run(["docker", *args], capture_output=True, timeout=timeout, cwd=cwd,
                              **config.SEM_JANELA).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ligar() -> None:
    """Liga o Docker Desktop e o container do Habblaud se ele não responder. Só um por vez; volta logo se já está ligando."""
    global _estado
    if not _ligando.acquire(blocking=False):
        return
    try:
        if _responde():
            return
        if not _docker("info", timeout=20):
            if not DOCKER_DESKTOP.exists():
                _estado = "Docker Desktop não encontrado; instale-o para ver o Habblaud."
                return
            _estado = "Ligando o Docker Desktop (leva até um minuto)…"
            subprocess.Popen([str(DOCKER_DESKTOP)], **config.SEM_JANELA)
            limite = time.monotonic() + 240
            while not _docker("info", timeout=20):
                if time.monotonic() > limite:
                    _estado = "O Docker Desktop não respondeu. Abra-o à mão e recarregue o painel."
                    return
                time.sleep(3)
        _estado = "Ligando o container do Habblaud…"
        if not _docker("start", "habblaud"):
            # Container apagado: o compose da pasta recria (e monta a imagem, se faltar).
            if not (PASTA_HABBLAUD / "docker-compose.yml").exists() or not _docker(
                    "compose", "up", "-d", timeout=900, cwd=PASTA_HABBLAUD):
                _estado = "Não consegui subir o Habblaud: rode npm run docker:up na pasta habblaud."
                return
        limite = time.monotonic() + 60
        while not _responde() and time.monotonic() < limite:
            time.sleep(1)
        _estado = "Ligando o Habblaud…"
    finally:
        _ligando.release()


def _ligar_em_fundo() -> None:
    threading.Thread(target=ligar, daemon=True).start()


ESPERA = """<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="3">
<body style="margin:0;background:#12151d;color:#7fa8b8;font:600 28px system-ui,sans-serif;letter-spacing:.06em">
<p style="padding:40px">{}</p>"""

# Sem If-None-Match/If-Modified-Since: sempre resposta completa, para nenhuma cópia antiga do navegador
# (como a versão que escondia a interface) ficar valendo por um 304.
REPASSAR = ("Accept", "Accept-Language", "Cache-Control", "Last-Event-ID")
DESCARTAR = {"x-frame-options", "connection", "keep-alive", "transfer-encoding", "content-length", "date", "server"}


def _manipulador(porta_painel: int):
    destino = urlsplit(config.HABBLAUD_URL)
    hosts = {"127.0.0.1", "localhost"}
    moldura = f"frame-ancestors http://127.0.0.1:{porta_painel} http://localhost:{porta_painel}"

    class Manipulador(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _texto(self, codigo: int, texto: str) -> None:
            corpo = texto.encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if self.headers.get("Host", "").rsplit(":", 1)[0] not in hosts:
                return self._texto(403, "host")
            conexao = http.client.HTTPConnection(destino.hostname, destino.port or 80, timeout=5)
            try:
                cabecalhos = {k: self.headers[k] for k in REPASSAR if self.headers.get(k)}
                conexao.request(self.command, self.path, headers=cabecalhos)
                resposta = conexao.getresponse()
            except OSError:
                conexao.close()
                _ligar_em_fundo()
                if self.path != "/":
                    return self._texto(502, "Habblaud fora do ar.")
                # A página de espera se recarrega sozinha até o Habblaud responder.
                corpo = ESPERA.format(html.escape(_estado)).encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", moldura)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(corpo)
                return
            try:
                self.send_response(resposta.status)
                for chave, valor in resposta.getheaders():
                    if chave.lower() not in DESCARTAR:
                        self.send_header(chave, valor)
                self.send_header("Content-Security-Policy", moldura)
                if resposta.getheader("Content-Length"):
                    self.send_header("Content-Length", resposta.getheader("Content-Length"))
                self.end_headers()
                if self.command == "HEAD":
                    return
                conexao.sock.settimeout(None)   # o stream de eventos fica aberto
                # HTTP/1.0: sem Content-Length, o fim da conexão marca o fim do corpo (serve ao stream).
                while bloco := resposta.read1(65536):
                    self.wfile.write(bloco)
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                conexao.close()

        def do_POST(self):
            self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1_000_000))
            self._texto(405, "A miniatura só lê o Habblaud.")

        do_PUT = do_PATCH = do_DELETE = do_POST

    return Manipulador


def iniciar(porta: int, porta_painel: int) -> bool:
    """Sobe o proxy em segundo plano. False se a porta já estiver em uso."""
    try:
        servidor = ThreadingHTTPServer(("127.0.0.1", porta), _manipulador(porta_painel))
    except OSError:
        return False
    servidor.daemon_threads = True
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    _ligar_em_fundo()
    return True
