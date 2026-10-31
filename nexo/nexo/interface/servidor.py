"""Interface do NEXO: servidor local com o anel de estado, a conversa e o grafo do cérebro ao vivo.

Só escuta em 127.0.0.1. Toda ação (POST) exige o cabeçalho X-Nexo: um site aberto no
navegador não consegue enviar esse cabeçalho para cá sem uma autorização CORS que este
servidor nunca dá, então não tem como mandar o NEXO fazer nada.

Eventos para a página (Server-Sent Events em /api/eventos):
  estado    {"estado": parado|ouvindo|pensando|falando}
  mensagem  {"de": "voce"|"nexo", "texto", "provedor"?, "acoes"?}
  acao      {"descricao", "erro", "notas"}        -> as notas acendem no grafo
  acender   {"notas"}                             -> notas citadas na resposta
  confirmar {"id", "pergunta"}                    -> a página mostra Sim/Não
  grafo     {}                                    -> o cérebro mudou; a página recarrega o grafo
  aviso     {"texto"}
"""
import json
import os
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import atalhos, cerebro, config, ia
from ..conversa import Conversa

PAGINA = Path(__file__).with_name("pagina.html")
HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}
# Sites do Acesso Rápido. A página só manda a chave; o endereço fica aqui, então ela não abre outra coisa.
SITES = {
    "briefing": "http://localhost:8080/jarvis/dashboard.html",   # pelo Apache: aberto como arquivo não lê o data.json
    "cbtech-local": "http://localhost:8080/CBTECH/",
    "cbtech-site": "https://www.cbtechsoftware.com.br/Matheus/",
    "habblaud": "https://habblaud.localhost/",
}


class Nucleo:
    """Estado compartilhado: a conversa, os ouvintes da página, voz e confirmações."""

    def __init__(self, modo: str = "rapido", privado: bool = False, falar: bool = True):
        self.ouvintes: list[queue.Queue] = []
        self.trava_turno = threading.Lock()
        self.trava_ouvintes = threading.Lock()
        self.pendentes: dict[str, dict] = {}
        self.falar = falar
        self.continuo = False
        self.ligado = True     # interruptor mestre do painel
        self.vigia = None      # a vigia que roda dentro do painel, se for ele que a reservou
        self.tecla = ""        # atalho global registrado ("Ctrl+Alt+J"), vazio se não registrou
        self.estado = "parado"
        self.limiar: float | None = None
        self.conversa = Conversa(modo=modo, privado=privado, confirmar=self._confirmar,
                                 ao_evento=self._ao_evento)

    # ---------- eventos ----------

    def emitir(self, tipo: str, dados: dict | None = None) -> None:
        mensagem = f"event: {tipo}\ndata: {json.dumps(dados or {}, ensure_ascii=False)}\n\n"
        with self.trava_ouvintes:
            for q in self.ouvintes:
                q.put(mensagem)

    def mudar_estado(self, estado: str) -> None:
        self.estado = estado
        self.emitir("estado", {"estado": estado})

    def _ao_evento(self, tipo: str, dados: dict) -> None:
        if tipo == "pensando":
            self.mudar_estado("pensando")
        elif tipo == "acao":
            self.emitir("acao", dados)

    # ---------- energia ----------

    def iniciar_vigia(self) -> bool:
        """Roda a vigia dentro do painel, se nenhuma outra estiver rodando no PC."""
        from .. import proativo
        if self.vigia is not None:
            return True
        if not proativo.reservar_vigia():
            return False
        self.vigia = proativo.Vigia(self.avisar_proativo)
        threading.Thread(target=self.vigia.rodar, daemon=True).start()
        return True

    def energia(self, ligar: bool) -> None:
        """Interruptor mestre: desligado, o assistente não conversa, não escuta e a vigia para."""
        from .. import proativo
        if ligar == self.ligado:
            return
        self.ligado = ligar
        if ligar:
            self.iniciar_vigia()
        else:
            self.continuo = False
            if self.vigia is not None:
                self.vigia.ativo = False   # a thread sai no fim da espera atual
                self.vigia = None
            else:
                proativo.parar_vigia()     # a da inicialização do Windows, em outro processo
            for pedido in list(self.pendentes.values()):
                pedido["evento"].set()     # confirmações abertas viram "não"
        self.emitir("continuo", {"ligado": self.continuo})
        self.emitir("energia", {"ligado": ligar})

    # ---------- atalho de teclado ----------

    def atalho_teclado(self, url: str) -> None:
        """Primeiro aperto: painel na frente com o cursor no chat. Já na frente: escuta o que o usuário disser."""
        from . import tecla
        hwnd = tecla.janela(config.NOME)
        if hwnd and tecla.em_frente(hwnd):
            if self.ligado and self.estado == "parado":
                threading.Thread(target=self.ouvir_e_responder, daemon=True).start()
            return
        if hwnd:
            tecla.trazer(hwnd)
        else:
            _abrir_janela(url)   # a janela tinha sido fechada; o painel seguia rodando em segundo plano
        self.emitir("foco")

    # ---------- confirmação ----------

    def _confirmar(self, pergunta: str) -> bool:
        pedido = {"evento": threading.Event(), "resposta": False}
        ident = uuid.uuid4().hex[:8]
        self.pendentes[ident] = pedido
        self.emitir("confirmar", {"id": ident, "pergunta": pergunta})
        if self.falar:
            self._dizer(f"{pergunta} Confirme na tela.")
        pedido["evento"].wait(timeout=90)
        self.pendentes.pop(ident, None)
        self.emitir("confirmado", {"id": ident, "resposta": pedido["resposta"]})
        return pedido["resposta"]

    def responder_confirmacao(self, ident: str, resposta: bool) -> bool:
        pedido = self.pendentes.get(ident)
        if not pedido:
            return False
        pedido["resposta"] = bool(resposta)
        pedido["evento"].set()
        return True

    # ---------- voz ----------

    def _dizer(self, texto: str, ao_primeiro_som=None, esperar=None) -> None:
        from .. import voz
        anterior = self.estado
        self.mudar_estado("falando")
        try:
            voz.falar(texto, ao_primeiro_som, esperar)
        except Exception as e:
            self.emitir("aviso", {"texto": f"Não consegui falar: {type(e).__name__}"})
        self.mudar_estado(anterior if anterior != "falando" else "parado")

    def escutar(self, espera: float = 8.0) -> str:
        from .. import voz
        if self.limiar is None:
            self.limiar = voz.calibrar()
        self.mudar_estado("ouvindo")
        try:
            audio = voz.ouvir(self.limiar, espera)
            return voz.transcrever(audio) if audio else ""
        except Exception as e:
            self.emitir("aviso", {"texto": f"Não consegui ouvir: {type(e).__name__}: {e}"})
            return ""
        finally:
            if self.estado == "ouvindo":
                self.mudar_estado("parado")

    # ---------- turno ----------

    def turno(self, texto: str) -> None:
        """Processa uma mensagem do começo ao fim (roda numa thread própria)."""
        if not self.trava_turno.acquire(blocking=False):
            self.emitir("aviso", {"texto": f"Ainda estou terminando a resposta anterior, {config.TRATAMENTO}."})
            return
        try:
            inicio = time.time()
            self.emitir("mensagem", {"de": "voce", "texto": texto})
            # Enquanto a IA pensa, um reconhecimento curto (já guardado) toca na hora.
            ack, pronto = None, threading.Event()
            if self.falar and not atalhos.tem(texto):
                from .. import voz
                ack = voz.reconhecer(pronto)
            try:
                try:
                    t = self.conversa.enviar(texto)
                finally:
                    pronto.set()
                t_ia = time.time() - inicio
            except ia.SemIA as e:
                self.emitir("mensagem", {"de": "nexo", "texto": f"Desculpe, {config.TRATAMENTO}: {e}", "provedor": "erro"})
                return
            self.emitir("acender", {"notas": sorted(cerebro.extrair_links(t.texto))})
            self.emitir("mensagem", {"de": "nexo", "texto": t.texto, "provedor": t.provedor, "acoes": t.acoes})
            if self.falar:
                self._dizer(t.texto, esperar=ack, ao_primeiro_som=lambda: self._tempo(texto, t.provedor, t_ia, time.time() - inicio, ack is not None))
        finally:
            self.mudar_estado("parado")
            self.trava_turno.release()

    @staticmethod
    def _tempo(pergunta: str, provedor: str, t_ia: float, t_som: float, com_ack: bool) -> None:
        """Uma linha por resposta em dados/tempos.log: quanto a IA levou e quando o som começou."""
        try:
            with open(config.DADOS / "tempos.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} IA={t_ia:.1f}s resposta-falada={t_som:.1f}s "
                        f"via={provedor} ack={'sim' if com_ack else 'não'} | {pergunta[:50]}\n")
        except OSError:
            pass

    def ouvir_e_responder(self) -> None:
        frase = self.escutar()
        if frase:
            self.turno(frase)
        else:
            self.emitir("aviso", {"texto": f"Não ouvi nada, {config.TRATAMENTO}."})

    def laco_continuo(self) -> None:
        """Escuta sempre; atende frases que começam com o nome da assistente."""
        from .. import voz
        falhas = 0
        while self.continuo:
            if self.trava_turno.locked():
                time.sleep(0.3)
                continue
            # Um erro do microfone (dispositivo trocado, ocupado) não pode matar a thread em silêncio:
            # o botão ficaria ligado sem ninguém escutando.
            try:
                pedido = voz.proxima_chamada(lambda espera: self.escutar(espera=30),
                                             parar=lambda: not self.continuo or self.trava_turno.locked())
                falhas = 0
            except Exception as e:
                falhas += 1
                self.emitir("aviso", {"texto": f"A escuta contínua falhou ({type(e).__name__}: {e}); tentando de novo."})
                if falhas >= 5:
                    self.continuo = False
                    self.emitir("aviso", {"texto": f"Desliguei a escuta contínua, {config.TRATAMENTO}: o microfone não respondeu."})
                    self.emitir("continuo", {"ligado": False})
                    return
                time.sleep(2)
                continue
            if pedido is None or not self.continuo:
                continue
            self.emitir("aviso", {"texto": f"Ouvi meu nome, {config.TRATAMENTO}."})
            # Um erro na resposta também não pode matar a escuta: o botão seguiria marcado sem ninguém ouvindo.
            try:
                if not pedido:
                    self._dizer(f"Pois não, {config.TRATAMENTO}?")
                    pedido = self.escutar()
                if pedido:
                    self.turno(pedido)
            except Exception as e:
                self.emitir("aviso", {"texto": f"Não consegui responder ({type(e).__name__}: {e}); sigo escutando."})

    # ---------- dados do HUD ----------

    _clima: tuple[float, dict | None] = (0.0, None)

    def painel(self) -> dict:
        """Clima (guardado por 20 min), hábitos, lembretes, caixa de entrada e fontes, para o HUD."""
        from .. import conhecimento, proativo
        from ..ferramentas.internet import clima_dados
        instante, clima = self._clima
        if time.time() - instante > 20 * 60:
            try:
                clima = clima_dados(proativo.CIDADE)
            except Exception:
                clima = clima  # mantém o último que deu certo
            self._clima = (time.time(), clima)
        return {
            "galo": self.galo(),
            "nome": config.NOME,
            "tratamento": config.TRATAMENTO,
            "clima": clima,
            "habitos": proativo.habitos_hoje(),
            "lembretes": proativo.lembretes_pendentes()[:5],
            "entrada": len(cerebro.pendentes()),
            "fontes": len(conhecimento.fontes()),
        }

    @staticmethod
    def galo() -> dict | None:
        """Tabela e próximos jogos do Galo (guardados por 30 min em futebol.galo_recente)."""
        from .. import futebol
        return futebol.galo_recente()

    @staticmethod
    def sistema() -> dict:
        import psutil
        ram = psutil.virtual_memory()
        disco = psutil.disk_usage(str(config.RAIZ.anchor or "/"))
        bateria = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        return {
            "cpu": psutil.cpu_percent(interval=None),
            "ram": ram.percent, "ram_livre_gb": round(ram.available / 2**30, 1),
            "disco": disco.percent, "disco_livre_gb": round(disco.free / 2**30),
            "bateria": round(bateria.percent) if bateria else None,
            "carregando": bool(bateria and bateria.power_plugged),
            "ligado_seg": int(time.time() - psutil.boot_time()),
        }

    def avisar_proativo(self, texto: str) -> None:
        """Aviso da proatividade: notificação do Windows, mensagem na tela e, se ligado, voz."""
        from .. import proativo
        proativo.notificar(config.NOME, texto)
        self.emitir("mensagem", {"de": "nexo", "texto": texto, "provedor": "proativo"})
        if self.falar and not self.trava_turno.locked():
            self._dizer(texto)

    def vigiar_cerebro(self) -> None:
        """Avisa a página quando alguma nota muda (criada pelo NEXO, pelo Claude Code ou no Obsidian)."""
        anterior = cerebro.assinatura()
        while True:
            time.sleep(2)
            atual = cerebro.assinatura()
            if atual != anterior:
                anterior = atual
                self.emitir("grafo")


def _manipulador(nucleo: Nucleo):
    class Manipulador(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencioso no terminal
            pass

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "").rsplit(":", 1)[0] in HOSTS_PERMITIDOS

        def _json(self, dados, codigo: int = 200) -> None:
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            if not self._host_ok():
                return self._json({"erro": "host"}, 403)
            if self.path == "/":
                corpo = PAGINA.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            elif self.path == "/api/grafo":
                self._json(cerebro.grafo())
            elif self.path == "/api/estado":
                from .. import voz
                self._json({"estado": nucleo.estado, "modo": nucleo.conversa.modo,
                            "voz": voz.voz_atual(),
                            "vozes": [{"id": chave, "nome": v[0]} for chave, v in voz.VOZES.items()],
                            "privado": nucleo.conversa.privado, "falar": nucleo.falar,
                            "continuo": nucleo.continuo, "ligado": nucleo.ligado, "ias": ia.disponiveis(),
                            "tecla": nucleo.tecla,
                            "nome": config.NOME})
            elif self.path == "/api/painel":
                self._json(nucleo.painel())
            elif self.path == "/api/sistema":
                self._json(nucleo.sistema())
            elif self.path == "/api/eventos":
                self._eventos()
            else:
                self._json({"erro": "não encontrado"}, 404)

        def _eventos(self):
            q: queue.Queue = queue.Queue()
            with nucleo.trava_ouvintes:
                nucleo.ouvintes.append(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                self.wfile.write(b": conectado\n\n")
                self.wfile.flush()
                while True:
                    try:
                        mensagem = q.get(timeout=15)
                    except queue.Empty:
                        mensagem = ": ping\n\n"
                    self.wfile.write(mensagem.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                with nucleo.trava_ouvintes:
                    nucleo.ouvintes.remove(q)

        def do_POST(self):
            # Lê o corpo antes de qualquer resposta: recusar sem ler derruba a conexão no Windows.
            tamanho = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
            corpo = self.rfile.read(tamanho)
            if not self._host_ok() or self.headers.get("X-Nexo") != "1":
                return self._json({"erro": "proibido"}, 403)
            try:
                dados = json.loads(corpo or b"{}")
            except ValueError:
                return self._json({"erro": "json inválido"}, 400)

            def em_fundo(funcao, *args):
                threading.Thread(target=funcao, args=args, daemon=True).start()

            if not nucleo.ligado and self.path in ("/api/mensagem", "/api/ouvir"):
                return self._json({"erro": "desligado"}, 409)
            if self.path == "/api/mensagem":
                texto = str(dados.get("texto", "")).strip()
                if not texto:
                    return self._json({"erro": "vazio"}, 400)
                em_fundo(nucleo.turno, texto)
            elif self.path == "/api/ouvir":
                em_fundo(nucleo.ouvir_e_responder)
            elif self.path == "/api/confirmar":
                if not nucleo.responder_confirmacao(str(dados.get("id")), dados.get("resposta") is True):
                    return self._json({"erro": "nada a confirmar"}, 404)
            elif self.path == "/api/abrir":
                url = SITES.get(str(dados.get("site")))
                if not url:
                    return self._json({"erro": "site desconhecido"}, 404)
                import webbrowser
                em_fundo(webbrowser.open, url)
            elif self.path == "/api/ajustes":
                if "ligado" in dados:
                    nucleo.energia(bool(dados["ligado"]))
                if dados.get("modo") in ia.ORDEM:
                    nucleo.conversa.modo = dados["modo"]
                if "privado" in dados:
                    nucleo.conversa.privado = bool(dados["privado"])
                if "falar" in dados:
                    nucleo.falar = bool(dados["falar"])
                if "voz" in dados:
                    from .. import voz
                    if not voz.escolher_voz(str(dados["voz"])):
                        return self._json({"erro": "voz desconhecida"}, 400)
                    if nucleo.falar:
                        voz.preaquecer()   # as frases fixas da voz nova, para os reconhecimentos tocarem
                if "continuo" in dados:
                    ligar = bool(dados["continuo"]) and nucleo.ligado
                    if ligar and not nucleo.continuo:
                        nucleo.continuo = True
                        em_fundo(nucleo.laco_continuo)
                    nucleo.continuo = ligar
            else:
                return self._json({"erro": "não encontrado"}, 404)
            self._json({"ok": True}, 202)

    return Manipulador


def iniciar(porta: int = 8765, modo: str = "rapido", privado: bool = False, falar: bool = True,
            abrir: bool = True) -> None:
    url = f"http://127.0.0.1:{porta}/"
    if _ja_no_ar(url):
        # Segundo clique no ícone: o painel já está rodando, só reabre a janela.
        print(f"{config.NOME} já está no ar em {url}; abrindo a janela.")
        if abrir:
            _abrir_janela(url)
        return

    nucleo = Nucleo(modo=modo, privado=privado, falar=falar)
    if falar:
        from .. import voz
        voz.preaquecer()   # navegador do Fish aberto e frases fixas prontas antes da primeira fala
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), _manipulador(nucleo))
    servidor.daemon_threads = True
    from . import habblaud
    if not habblaud.iniciar(porta + 1, porta):
        print(f"A porta {porta + 1} está ocupada; a miniatura do Habblaud fica sem imagem.")
    threading.Thread(target=nucleo.vigiar_cerebro, daemon=True).start()
    # Se a vigia de inicialização já está rodando, ela cuida dos avisos (por notificação do Windows).
    if not nucleo.iniciar_vigia():
        print("A vigia já está rodando em segundo plano; os avisos chegam por notificação do Windows.")
    if config.TECLA:
        from . import tecla
        try:
            if tecla.escutar(config.TECLA, lambda: nucleo.atalho_teclado(url)):
                nucleo.tecla = tecla.legivel(config.TECLA)
                print(f"{nucleo.tecla} traz o painel para a frente de qualquer programa.")
            elif os.name == "nt":
                print(f"O atalho {tecla.legivel(config.TECLA)} já é usado por outro programa; troque em NEXO_TECLA.")
        except ValueError as e:
            print(f"Atalho de teclado ignorado: {e}")
    print(f"{config.NOME} no ar em {url}  (Ctrl+C para encerrar)")
    if abrir:
        _abrir_janela(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        nucleo.continuo = False
        nucleo.conversa.encerrar()
        servidor.server_close()
        print(f"Até logo, {config.TRATAMENTO}.")


def _ja_no_ar(url: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url + "api/estado", timeout=1.5) as r:
            return "nome" in json.loads(r.read())
    except Exception:
        return False


def _abrir_janela(url: str) -> None:
    """Abre como janela de aplicativo do Google Chrome (sem barra de endereço).

    Sem Chrome, tenta o Edge no mesmo modo; sem os dois, o navegador padrão.
    """
    import os
    import shutil
    import subprocess
    import webbrowser
    candidatos = [
        shutil.which("chrome"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for navegador in filter(None, candidatos):
        if os.path.exists(navegador):
            subprocess.Popen([navegador, f"--app={url}", "--window-size=1280,800"])
            return
    webbrowser.open(url)
