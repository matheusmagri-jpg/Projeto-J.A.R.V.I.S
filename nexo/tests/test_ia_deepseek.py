import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from google.genai import errors

from nexo import config, ia

from test_cerebro import isolar_dados


def setUpModule():
    isolar_dados()


class TestDeepSeek(unittest.TestCase):
    def test_tem_deepseek_quando_chave_existe(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "abc123"}, clear=False):
            self.assertTrue(ia.tem_deepseek())
            self.assertIn("deepseek", ia.PROVEDORES)

    def test_deepseek_chama_api_openai_compat(self):
        payload = {"choices": [{"message": {"content": "Resposta final"}}]}
        fake_response = mock.Mock()
        fake_response.read.return_value = b'{"choices": [{"message": {"content": "Resposta final"}}]}'
        fake_response.__enter__ = mock.Mock(return_value=fake_response)
        fake_response.__exit__ = mock.Mock(return_value=None)

        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret"}, clear=False), \
             mock.patch("nexo.ia.request.urlopen", return_value=fake_response) as urlopen:
            resposta = ia._deepseek("Pergunta", "Sistema", None, "rapido")

        self.assertEqual(resposta, "Resposta final")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.headers["Authorization"], "Bearer secret")


class TestNvidia(unittest.TestCase):
    def test_modelo_muda_com_o_modo_e_raciocinio_sai_do_texto(self):
        r = mock.Mock()
        r.read.return_value = '{"choices": [{"message": {"content": "<think>hmm</think> Pronto"}}]}'.encode()
        r.__enter__ = mock.Mock(return_value=r)
        r.__exit__ = mock.Mock(return_value=None)
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "secret"}), \
             mock.patch("nexo.ia.request.urlopen", return_value=r) as urlopen:
            self.assertEqual(ia._nvidia("Pergunta", None, None, "profundo"), "Pronto")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.headers["Authorization"], "Bearer secret")
        self.assertEqual(json.loads(req.data)["model"], config.NVIDIA_MODELOS["profundo"])

    def test_nvidia_fica_na_ordem_dos_dois_modos(self):
        self.assertIn("nvidia", ia.ORDEM["rapido"])
        self.assertIn("nvidia", ia.ORDEM["profundo"])


class TestContasGemini(unittest.TestCase):
    def setUp(self):
        ia._esgotados.clear()
        self.addCleanup(ia._esgotados.clear)
        env = mock.patch.dict(os.environ, {"GEMINI_API_KEY": "a", "GEMINI_AGENT_PLATFORM_KEY": "b",
                                           "GEMINI_API_KEY_RESERVA": "c"})
        env.start()
        self.addCleanup(env.stop)

    def _clientes(self, chamadas, erros):
        def cliente(conta):
            def gerar(model, contents, config):
                chamadas.append((conta, model))
                if (conta, model) in erros:
                    raise erros[(conta, model)]
                return f"{conta}/{model}"
            return SimpleNamespace(models=SimpleNamespace(generate_content=gerar))
        return cliente

    def test_mesmo_modelo_em_outra_conta_antes_de_cair_de_modelo(self):
        sem_cota = errors.ClientError(429, {"error": {"message": "cota"}})
        chamadas = []
        with mock.patch.object(ia, "cliente", self._clientes(chamadas, {("gemini", "forte"): sem_cota})):
            self.assertEqual(ia.gerar_gemini("x", None, ["forte", "fraco"]), "gemini-agente/forte")
        self.assertEqual(chamadas, [("gemini", "forte"), ("gemini-agente", "forte")])

    def test_modelo_que_nao_existe_na_conta_passa_para_a_proxima(self):
        inexistente = errors.ClientError(404, {"error": {"message": "não encontrado"}})
        erros = {("gemini", "m"): inexistente, ("gemini-agente", "m"): inexistente}
        with mock.patch.object(ia, "cliente", self._clientes([], erros)):
            self.assertEqual(ia.gerar_gemini("x", None, ["m"]), "gemini-reserva/m")

    def test_chave_que_nao_vale_no_servico_passa_para_a_proxima_conta(self):
        negada = errors.ClientError(403, {"error": {"message": "desativada"}})
        erros = {("gemini", "m"): negada, ("gemini-agente", "m"): negada}
        with mock.patch.object(ia, "cliente", self._clientes([], erros)):
            self.assertEqual(ia.gerar_gemini("x", None, ["m"]), "gemini-reserva/m")

    def test_profundo_comeca_pelo_modelo_mais_forte(self):
        self.assertEqual(ia.modelos_gemini("profundo")[0], config.GEMINI_MODELO_PROFUNDO)
        self.assertEqual(ia.modelos_gemini("rapido"), config.GEMINI_MODELOS)
