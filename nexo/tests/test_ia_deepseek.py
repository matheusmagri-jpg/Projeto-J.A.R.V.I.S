import os
import unittest
from unittest import mock

from nexo import ia


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
