import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from nexo import cerebro, ia
from nexo.conversa import Turno
from nexo.interface import servidor

from test_cerebro import BaseCerebro


class TestGrafo(BaseCerebro):
    def test_nos_e_ligacoes(self):
        g = cerebro.grafo()
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("00-mapa", ids)
        self.assertIn({"source": "Sexta-Feira", "target": "Claude e Gemini juntos"}, g["links"])
        tipos = {n["id"]: n["tipo"] for n in g["nodes"]}
        self.assertEqual((tipos["00-mapa"], tipos["Sexta-Feira"], tipos["ALMA"]), ("mapa", "projeto", "nucleo"))
        # só ligações para notas que existem, e nenhuma nota ligada a si mesma
        for l in g["links"]:
            self.assertIn(l["target"], ids)
            self.assertNotEqual(l["source"], l["target"])

    def test_assinatura_muda_com_nota_nova(self):
        antes = cerebro.assinatura()
        cerebro.criar_nota("ideia", "Nova ideia", "texto")
        self.assertNotEqual(antes, cerebro.assinatura())


class TestServidor(BaseCerebro):
    def setUp(self):
        super().setUp()
        self.nucleo = servidor.Nucleo(falar=False)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), servidor._manipulador(self.nucleo))
        self.http.daemon_threads = True
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        super().tearDown()

    def pedir(self, caminho, dados=None, cabecalhos=None):
        corpo = None if dados is None else json.dumps(dados).encode()
        req = urllib.request.Request(self.base + caminho, data=corpo, headers=cabecalhos or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_pagina_e_grafo(self):
        status, corpo = self.pedir("/")
        self.assertEqual(status, 200)
        self.assertIn("JARVIS".encode(), corpo)
        status, corpo = self.pedir("/api/grafo")
        self.assertGreater(len(json.loads(corpo)["nodes"]), 10)

    def test_post_sem_cabecalho_e_recusado(self):
        status, _ = self.pedir("/api/mensagem", {"texto": "oi"})
        self.assertEqual(status, 403)

    def test_host_estranho_e_recusado(self):
        status, _ = self.pedir("/api/grafo", cabecalhos={"Host": "site-malicioso.com"})
        self.assertEqual(status, 403)

    def test_ajustes(self):
        status, _ = self.pedir("/api/ajustes", {"modo": "profundo", "privado": True}, {"X-Nexo": "1"})
        self.assertEqual(status, 202)
        self.assertEqual((self.nucleo.conversa.modo, self.nucleo.conversa.privado), ("profundo", True))

    def test_escolher_a_voz(self):
        import tempfile
        from pathlib import Path
        from nexo import voz
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        with mock.patch.object(voz, "VOZ_ESCOLHIDA", Path(pasta.name) / "voz.json"), \
                mock.patch.object(voz, "preaquecer") as preaquecer:
            estado = json.loads(self.pedir("/api/estado")[1])
            self.assertEqual(estado["voz"], "jarvis")
            self.assertIn({"id": "julius", "nome": "Julius"}, estado["vozes"])

            self.assertEqual(self.pedir("/api/ajustes", {"voz": "julius"}, {"X-Nexo": "1"})[0], 202)
            self.assertEqual(json.loads(self.pedir("/api/estado")[1])["voz"], "julius")
            preaquecer.assert_not_called()   # painel mudo não gasta geração
            self.nucleo.falar = True
            self.assertEqual(self.pedir("/api/ajustes", {"voz": "jarvis"}, {"X-Nexo": "1"})[0], 202)
            preaquecer.assert_called_once()

            self.assertEqual(self.pedir("/api/ajustes", {"voz": "outra"}, {"X-Nexo": "1"})[0], 400)
            self.assertEqual(json.loads(self.pedir("/api/estado")[1])["voz"], "jarvis")

    def test_interruptor_mestre(self):
        eventos = []
        self.nucleo.emitir = lambda tipo, dados=None: eventos.append((tipo, dados or {}))
        self.nucleo.continuo = True
        with mock.patch("nexo.proativo.parar_vigia") as parar, \
                mock.patch("nexo.proativo.reservar_vigia", return_value=True), \
                mock.patch("nexo.proativo.Vigia") as vigia:
            status, _ = self.pedir("/api/ajustes", {"ligado": False}, {"X-Nexo": "1"})
            self.assertEqual(status, 202)
            self.assertFalse(self.nucleo.ligado)
            self.assertFalse(self.nucleo.continuo)
            parar.assert_called_once()   # a vigia de outro processo é encerrada
            self.assertIn(("energia", {"ligado": False}), eventos)
            # desligado: não conversa, não escuta e não religa a escuta contínua
            self.assertEqual(self.pedir("/api/mensagem", {"texto": "oi"}, {"X-Nexo": "1"})[0], 409)
            self.assertEqual(self.pedir("/api/ouvir", {}, {"X-Nexo": "1"})[0], 409)
            self.pedir("/api/ajustes", {"continuo": True}, {"X-Nexo": "1"})
            self.assertFalse(self.nucleo.continuo)
            _, corpo = self.pedir("/api/estado")
            self.assertFalse(json.loads(corpo)["ligado"])

            self.pedir("/api/ajustes", {"ligado": True}, {"X-Nexo": "1"})
            self.assertTrue(self.nucleo.ligado)
            vigia.return_value.rodar.assert_called()   # a vigia volta, agora dentro do painel
            self.assertIn(("energia", {"ligado": True}), eventos)

            # desligar de novo para a vigia do próprio painel, sem matar processo nenhum
            self.pedir("/api/ajustes", {"ligado": False}, {"X-Nexo": "1"})
            self.assertFalse(vigia.return_value.ativo)
            parar.assert_called_once()

    def test_acesso_rapido_abre_so_sites_conhecidos(self):
        with mock.patch("webbrowser.open") as abrir:
            status, _ = self.pedir("/api/abrir", {"site": "cbtech-local"}, {"X-Nexo": "1"})
            self.assertEqual(status, 202)
            status, _ = self.pedir("/api/abrir", {"site": "https://site-malicioso.com"}, {"X-Nexo": "1"})
            self.assertEqual(status, 404)
            for _ in range(20):
                if abrir.called:
                    break
                threading.Event().wait(0.05)
        abrir.assert_called_once_with("http://localhost:8080/CBTECH/")

    def test_turno_emite_eventos(self):
        eventos = []
        self.nucleo.emitir = lambda tipo, dados=None: eventos.append((tipo, dados or {}))
        turno = Turno("Veja [[NEXO]], senhor.", "gemini", ["ler_nota(titulo='NEXO')"])
        with mock.patch.object(self.nucleo.conversa, "enviar", return_value=turno):
            self.nucleo.turno("o que é o NEXO?")
        tipos = [t for t, _ in eventos]
        self.assertEqual(tipos[0], "mensagem")
        self.assertIn(("acender", {"notas": ["NEXO"]}), eventos)
        self.assertEqual(eventos[-1], ("estado", {"estado": "parado"}))

    def test_turno_sem_ia_avisa(self):
        eventos = []
        self.nucleo.emitir = lambda tipo, dados=None: eventos.append((tipo, dados or {}))
        with mock.patch.object(self.nucleo.conversa, "enviar", side_effect=ia.SemIA("sem chave")):
            self.nucleo.turno("oi")
        self.assertTrue(any(t == "mensagem" and d.get("provedor") == "erro" for t, d in eventos))

    def test_confirmacao_pela_tela(self):
        eventos = []
        self.nucleo.emitir = lambda tipo, dados=None: eventos.append((tipo, dados or {}))
        resultado = {}
        t = threading.Thread(target=lambda: resultado.setdefault("ok", self.nucleo._confirmar("Desligar?")))
        t.start()
        while not any(tipo == "confirmar" for tipo, _ in eventos):
            pass
        ident = next(d["id"] for tipo, d in eventos if tipo == "confirmar")
        status, _ = self.pedir("/api/confirmar", {"id": ident, "resposta": True}, {"X-Nexo": "1"})
        t.join(5)
        self.assertEqual((status, resultado["ok"]), (202, True))
