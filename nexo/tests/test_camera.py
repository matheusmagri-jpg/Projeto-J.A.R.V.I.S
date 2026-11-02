import io
import json
import unittest
from unittest import mock
from urllib import error

from nexo import ia
from nexo.ferramentas import camera


class TestCamera(unittest.TestCase):
    def test_privado_usa_o_modelo_local_e_nao_o_gemini(self):
        resposta = io.BytesIO(json.dumps({"message": {"content": "Uma caneca azul."}}).encode())
        with mock.patch.object(camera, "foto_jpg", return_value=b"jpg"), \
             mock.patch.object(ia, "privado_ativo", return_value=True), \
             mock.patch.object(ia, "gerar_gemini", side_effect=AssertionError("foi ao Gemini")), \
             mock.patch.object(camera.request, "urlopen", return_value=resposta) as abrir:
            self.assertEqual(camera.ver_camera("o que é isto?"), "Uma caneca azul.")
        corpo = json.loads(abrir.call_args.args[0].data)
        self.assertEqual(corpo["messages"][0]["images"], ["anBn"])     # base64 de b"jpg"

    def test_modelo_local_ausente_explica_como_instalar(self):
        erro404 = error.HTTPError("u", 404, "not found", {}, io.BytesIO(b""))
        with mock.patch.object(camera, "foto_jpg", return_value=b"jpg"), \
             mock.patch.object(ia, "privado_ativo", return_value=True), \
             mock.patch.object(camera.request, "urlopen", side_effect=erro404):
            self.assertIn("ollama pull", camera.ver_camera("?"))

    def test_sem_webcam_responde_sem_quebrar(self):
        with mock.patch.object(camera, "foto_jpg", side_effect=RuntimeError("não achei a webcam")):
            self.assertIn("não achei a webcam", camera.ver_camera("?"))

    def test_pede_confirmacao(self):
        self.assertTrue(camera.FERRAMENTAS[0].confirmar)


if __name__ == "__main__":
    unittest.main()
