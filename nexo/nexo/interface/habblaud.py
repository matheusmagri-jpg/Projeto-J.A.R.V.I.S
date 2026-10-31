"""Miniatura do Habblaud no painel.

O Habblaud responde com X-Frame-Options: DENY, então o painel não consegue mostrá-lo num iframe.
Este proxy local (porta do painel + 1) repassa só leituras (GET/HEAD) ao Habblaud e troca o DENY por
um frame-ancestors que aceita apenas o painel. Sem POST: a miniatura não consegue mudar nada no Habblaud.
"""
from __future__ import annotations

import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .. import config

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
                return self._texto(502, "Habblaud fora do ar.")
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
    return True
