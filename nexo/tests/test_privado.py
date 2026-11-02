"""Modo privado: com ele ligado, nenhum texto sai para Claude, Gemini, DeepSeek, NVIDIA ou MyHub."""
import os
from unittest import mock

from nexo import ia, myhub, voz
from nexo.conversa import Conversa
from nexo.ferramentas import Ferramenta

from test_cerebro import BaseCerebro

NUVEM = ("claude", "gemini", "deepseek", "nvidia")


class BasePrivado(BaseCerebro):
    def setUp(self):
        super().setUp()
        ia._cache_respostas.clear()
        ia.definir_privado(True)
        # Qualquer caminho para a nuvem fica registrado aqui; os testes exigem que continue vazio.
        self.nuvem = mock.Mock(side_effect=AssertionError("chamou a nuvem"))
        for p in (mock.patch.dict(ia._clientes, clear=True),
                  mock.patch.dict(ia._recusadas, clear=True),
                  mock.patch.object(ia.request, "urlopen", self.nuvem)):
            p.start()
            self.addCleanup(p.stop)

    def provedores(self, ollama):
        """Provedores falsos: os da nuvem se dizem configurados e anotam se forem chamados."""
        self.chamadas_nuvem = []

        def nuvem(nome):
            def chamar(*_):
                self.chamadas_nuvem.append(nome)
                return f"resposta de {nome}"
            return chamar
        provs = {nome: (nuvem(nome), lambda: True) for nome in NUVEM}
        provs["ollama"] = (ollama, lambda: True)
        return mock.patch.dict(ia.PROVEDORES, provs)


class TestBarreira(BasePrivado):
    def test_nenhum_cliente_da_nuvem_e_criado(self):
        for nome in ("claude", "gemini", "gemini-reserva", "gemini-agente"):
            with self.assertRaises(ia.ModoPrivado):
                ia.cliente(nome)
        self.assertEqual(ia._clientes, {})

    def test_deepseek_e_nvidia_nao_saem_do_pc(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "x", "NVIDIA_API_KEY": "x"}):
            with self.assertRaises(ia.ModoPrivado):
                ia.chamar_deepseek({"messages": []})
            with self.assertRaises(ia.ModoPrivado):
                ia.chamar_nvidia({"messages": []})
        self.nuvem.assert_not_called()

    def test_transcricao_fica_no_pc(self):
        with mock.patch.object(voz, "transcrever_local", return_value="que horas são") as local, \
             mock.patch.object(voz, "_transcrever_gemini", side_effect=AssertionError("foi ao Gemini")):
            self.assertEqual(voz.transcrever(b"RIFF"), "que horas são")
        local.assert_called_once_with(b"RIFF")
        self.assertEqual(ia._clientes, {})

    def test_sem_whisper_a_transcricao_e_barrada(self):
        with mock.patch.object(voz, "whisper_disponivel", return_value=False):
            with self.assertRaises(ia.ModoPrivado):
                voz.transcrever(b"RIFF")
        self.assertEqual(ia._clientes, {})

    def test_myhub_e_barrado(self):
        with mock.patch.object(myhub, "uso_hoje", side_effect=AssertionError("chegou ao MyHub")):
            with self.assertRaises(myhub.ErroMyHub):
                myhub.perguntar("oi")

    def test_preaquecer_nao_toca_na_nuvem(self):
        with mock.patch.object(ia, "cliente") as cliente, mock.patch.object(ia, "_ping_ollama"):
            ia._preaquecer_worker()
        cliente.assert_not_called()

    def test_disponiveis_so_tem_o_ollama(self):
        with self.provedores(lambda *_: "local"):
            self.assertEqual(ia.disponiveis(), ["ollama"])


class TestRoteador(BasePrivado):
    def test_todos_os_modos_respondem_so_pelo_ollama(self):
        with self.provedores(lambda *_: '{"ok": true}'):
            for modo in ("rapido", "profundo", "dupla"):
                r = ia.perguntar(f"pergunta {modo}", modo=modo)
                self.assertEqual(r.provedor, "ollama")
            r = ia.perguntar("organize", modo="profundo", esquema={"type": "object"})
            self.assertEqual((r.provedor, r.dados), ("ollama", {"ok": True}))
        self.assertEqual(self.chamadas_nuvem, [])

    def test_ollama_falhou_da_erro_claro_sem_cair_para_a_nuvem(self):
        def falha(*_):
            raise RuntimeError("Não consegui conectar ao Ollama")
        with self.provedores(falha):
            with self.assertRaises(ia.ModoPrivado) as erro:
                ia.perguntar("oi", modo="rapido")
        self.assertIn("nada foi enviado à nuvem", str(erro.exception))
        self.assertEqual(self.chamadas_nuvem, [])

    def test_desligado_volta_a_usar_a_nuvem(self):
        ia.definir_privado(False)
        with self.provedores(lambda *_: "local"):
            self.assertEqual(ia.perguntar("oi", modo="rapido").provedor, "gemini")


class TestConversaPrivada(BasePrivado):
    def conversa(self, ferramentas=None):
        return Conversa(modo="rapido", ferramentas_disponiveis=ferramentas or {})

    def test_painel_responde_pelo_ollama_sem_tocar_na_nuvem(self):
        nuvem = mock.Mock(side_effect=AssertionError("chamou a nuvem"))
        with self.provedores(lambda *_: "local"), \
                mock.patch.object(ia, "_ollama", return_value="Pois não, senhor.") as ollama, \
                mock.patch.object(ia, "chamar_deepseek", nuvem), mock.patch.object(ia, "chamar_nvidia", nuvem), \
                mock.patch.object(ia, "gerar_gemini", nuvem):
            for modo in ("rapido", "profundo"):
                c = self.conversa()
                c.modo = modo
                t = c.enviar("oi")
                self.assertEqual((t.texto, t.provedor), ("Pois não, senhor.", "ollama"))
        self.assertEqual(ollama.call_count, 2)
        nuvem.assert_not_called()
        self.assertEqual(ia._clientes, {})

    def test_nao_achou_nao_vai_ao_myhub(self):
        consultar = mock.Mock(return_value="Resposta do MyHub")
        ferramentas = {"consultar_myhub": Ferramenta("consultar_myhub", "MyHub", consultar)}
        with self.provedores(lambda *_: "local"), \
                mock.patch.object(ia, "_ollama", return_value="Não encontrei isso, senhor."):
            t = self.conversa(ferramentas).enviar("em quem o Max votou?")
        self.assertEqual(t.provedor, "ollama")
        consultar.assert_not_called()

    def test_ollama_falhou_na_conversa_da_erro_claro(self):
        with self.provedores(lambda *_: "local"), \
                mock.patch.object(ia, "_ollama", side_effect=RuntimeError("Ollama HTTP 500")):
            with self.assertRaises(ia.ModoPrivado) as erro:
                self.conversa().enviar("oi")
        self.assertIn("nada foi enviado à nuvem", str(erro.exception))
        self.assertEqual(self.chamadas_nuvem, [])


class TestEstado(BaseCerebro):
    def test_desligado_por_padrao_e_arquivo_estragado_conta_como_desligado(self):
        self.assertFalse(ia.privado_ativo())
        (ia._arquivo_privado()).parent.mkdir(parents=True, exist_ok=True)
        ia._arquivo_privado().write_text("{", encoding="utf-8")
        self.assertFalse(ia.privado_ativo())

    def test_vale_entre_conversas_e_nova_conversa_nao_desliga(self):
        Conversa(privado=True, ferramentas_disponiveis={})
        self.assertTrue(Conversa(ferramentas_disponiveis={}).privado)
        c = Conversa(ferramentas_disponiveis={})
        c.privado = False
        self.assertFalse(ia.privado_ativo())
