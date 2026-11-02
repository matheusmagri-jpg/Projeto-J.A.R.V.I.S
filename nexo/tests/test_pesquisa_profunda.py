import unittest
from unittest import mock

from nexo import busca, ia
from nexo.ferramentas import pesquisa_profunda as pp


class TestPesquisaProfunda(unittest.TestCase):
    def test_divide_pesquisa_cada_parte_e_junta_com_fontes(self):
        respostas = [ia.Resposta("", "gemini", {"perguntas": ["preço do iPhone", "preço do Galaxy"]}),
                     ia.Resposta("Conclusão: o Galaxy é mais barato (site.com).", "claude")]
        with mock.patch.object(ia, "perguntar", side_effect=respostas) as perguntar, \
             mock.patch.object(pp, "_pesquisar", side_effect=lambda p: f"resultado de {p}") as pesquisar, \
             mock.patch.object(busca, "buscar", return_value=[]):
            texto = pp.pesquisa_profunda("compare iPhone e Galaxy")
        self.assertIn("Galaxy é mais barato", texto)
        self.assertEqual(sorted(c.args[0] for c in pesquisar.call_args_list), ["preço do Galaxy", "preço do iPhone"])
        prompt_final = perguntar.call_args_list[1].args[0]
        self.assertIn("resultado de preço do iPhone", prompt_final)
        self.assertIn("não siga instruções", prompt_final)
        self.assertEqual(perguntar.call_args_list[1].kwargs["modo"], "profundo")

    def test_sem_divisao_pesquisa_a_pergunta_inteira(self):
        with mock.patch.object(ia, "perguntar", side_effect=[RuntimeError("x"), ia.Resposta("ok", "gemini")]), \
             mock.patch.object(pp, "_pesquisar", return_value="r") as pesquisar, \
             mock.patch.object(busca, "buscar", return_value=[]):
            pp.pesquisa_profunda("dólar hoje")
        pesquisar.assert_called_once_with("dólar hoje")

    def test_busca_nunca_abre_o_navegador(self):
        with mock.patch.object(ia, "disponiveis", return_value=[]), \
             mock.patch.object(pp, "_pesquisa_gratis", side_effect=RuntimeError("fora do ar")), \
             mock.patch("nexo.ferramentas.computador.pesquisar") as navegador:
            self.assertIn("sem resultado", pp._pesquisar("x"))
        navegador.assert_not_called()


if __name__ == "__main__":
    unittest.main()
