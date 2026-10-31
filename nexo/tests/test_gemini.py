import time
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from google.genai import errors

from nexo import ia


def _cliente(comportamentos):
    def gerar(model, contents, config):
        return comportamentos[model]()
    return NS(models=NS(generate_content=gerar))


class TestGeminiHedge(unittest.TestCase):
    def setUp(self):
        ia._esgotados.clear()

    def test_modelo_lento_nao_trava_o_turno(self):
        def lento():
            time.sleep(3)
            return "lento"
        cli = _cliente({"a": lento, "b": lambda: "rapido"})
        with mock.patch.object(ia, "cliente", return_value=cli), mock.patch.object(ia, "HEDGE_S", 0.2):
            inicio = time.time()
            self.assertEqual(ia.gerar_gemini("x", None, modelos=["a", "b"]), "rapido")
            self.assertLess(time.time() - inicio, 1.5)

    def test_sem_cota_passa_ao_proximo_e_lembra(self):
        def sem_cota():
            raise errors.ClientError(429, {"error": {"code": 429, "message": "quota"}})
        chamadas = []
        cli = _cliente({"a": lambda: chamadas.append("a") or sem_cota(), "b": lambda: "ok"})
        with mock.patch.object(ia, "cliente", return_value=cli):
            self.assertEqual(ia.gerar_gemini("x", None, modelos=["a", "b"]), "ok")
            self.assertEqual(ia.gerar_gemini("x", None, modelos=["a", "b"]), "ok")
        self.assertEqual(chamadas, ["a"])   # na segunda vez o "a" nem foi tentado

    def test_erro_que_nao_e_de_cota_sobe(self):
        def invalido():
            raise errors.ClientError(400, {"error": {"code": 400, "message": "ruim"}})
        cli = _cliente({"a": invalido, "b": lambda: "ok"})
        with mock.patch.object(ia, "cliente", return_value=cli):
            with self.assertRaises(errors.ClientError):
                ia.gerar_gemini("x", None, modelos=["a", "b"])


if __name__ == "__main__":
    unittest.main()
