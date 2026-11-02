from unittest import mock

import numpy as np

from nexo import busca, cerebro, semantica

from test_cerebro import BaseCerebro


def vetor_falso(textos, tarefa):
    """Vetores de brinquedo: 'carro' e 'veículo' apontam para o mesmo lado; o resto, para outro."""
    saida = []
    for t in textos:
        t = t.lower()
        v = np.array([1.0, 0.0, 0.0]) if ("carro" in t or "veículo" in t) else np.array([0.0, 1.0, 0.0])
        saida.append(v.astype(np.float32))
    return saida


class TestSemantica(BaseCerebro):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(semantica, "disponivel", return_value=True),
                  mock.patch.object(semantica, "_vetores", side_effect=vetor_falso)):
            p.start()
            self.addCleanup(p.stop)
        cerebro.criar_nota("ideia", "Comprar carro", "Pensar num carro usado até março.")

    def test_acha_por_significado_o_que_as_palavras_nao_acham(self):
        self.assertEqual(busca.buscar("veículo", semantica=False), [])
        achados = busca.buscar("veículo")                 # palavras não acham nada: entra o significado
        # O índice "Ideias" também cita "Comprar carro" e empata no vetor de brinquedo: a ordem não importa.
        self.assertIn("Comprar carro", [r.titulo for r in achados])

    def test_so_regera_vetor_de_nota_alterada(self):
        semantica.atualizar()
        self.assertEqual(semantica.atualizar(), 0)
        caminho = cerebro.encontrar("Comprar carro")
        caminho.write_text(caminho.read_text(encoding="utf-8") + "\nMais um detalhe.", encoding="utf-8")
        import os
        os.utime(caminho, (caminho.stat().st_atime, caminho.stat().st_mtime + 5))
        self.assertEqual(semantica.atualizar(), 1)

    def test_falha_da_api_nao_derruba_a_busca(self):
        with mock.patch.object(semantica, "_vetores", side_effect=OSError("sem internet")):
            self.assertEqual(semantica.buscar("veículo"), [])
            self.assertEqual(busca.buscar("veículo"), [])

    def test_indisponivel_no_modo_privado(self):
        with mock.patch.object(semantica, "disponivel", return_value=False), \
             mock.patch.object(semantica, "_vetores", side_effect=AssertionError("foi à nuvem")):
            self.assertEqual(semantica.buscar("veículo"), [])
