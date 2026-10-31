import unittest
from unittest import mock

from nexo import futebol

TABELA = {"children": [{"standings": {"entries": [
    {"team": {"id": "6086", "displayName": "Flamengo"}, "stats": [{"name": "rank", "value": 1.0}]},
    {"team": {"id": "7632", "displayName": "Atlético-MG"}, "stats": [
        {"name": "rank", "value": 6.0}, {"name": "points", "value": 50.0}, {"name": "gamesPlayed", "value": 32.0},
        {"name": "wins", "value": 14.0}, {"name": "ties", "value": 8.0}, {"name": "losses", "value": 10.0}]},
]}}]}


def _jogo(data, casa, fora, liga, terminado=False):
    return {"date": data, "league": {"name": liga}, "competitions": [{
        "status": {"type": {"completed": terminado}}, "venue": {"fullName": "Arena MRV"},
        "competitors": [{"homeAway": "home", "team": {"id": casa[0], "displayName": casa[1]}},
                        {"homeAway": "away", "team": {"id": fora[0], "displayName": fora[1]}}]}]}


AGENDA = {"events": [
    _jogo("2026-11-01T21:30Z", ("1", "Grêmio"), ("7632", "Atlético-MG"), "Copa do Brasil"),
    _jogo("2026-10-29T22:30Z", ("7632", "Atlético-MG"), ("2", "Cruzeiro"), "Brazilian Serie A"),
    _jogo("2026-10-20T22:30Z", ("7632", "Atlético-MG"), ("3", "Santos"), "Brazilian Serie A", terminado=True),
]}


class TestGalo(unittest.TestCase):
    def test_colocacao(self):
        self.assertEqual(futebol.colocacao(TABELA, "7632"),
                         {"time": "Atlético-MG", "posicao": 6, "pontos": 50, "jogos": 32,
                          "vitorias": 14, "empates": 8, "derrotas": 10})
        self.assertIsNone(futebol.colocacao(TABELA, "999"))

    def test_proximos_em_ordem_e_no_horario_de_brasilia(self):
        jogos = futebol.proximos(AGENDA, "7632")
        self.assertEqual([j["adversario"] for j in jogos], ["Cruzeiro", "Grêmio"])   # o jogo já terminado sai
        self.assertEqual(jogos[0]["quando"], "2026-10-29T19:30:00-03:00")
        self.assertEqual((jogos[0]["em_casa"], jogos[0]["competicao"]), (True, "Brasileirão"))
        self.assertEqual((jogos[1]["em_casa"], jogos[1]["competicao"]), (False, "Copa do Brasil"))

    def test_fonte_fora_do_ar_nao_derruba_a_outra(self):
        def baixar(url):
            if "standings" in url:
                raise OSError("sem internet")
            return AGENDA
        with mock.patch.object(futebol, "_baixar", side_effect=baixar):
            dados = futebol.galo()
        self.assertIsNone(dados["colocacao"])
        self.assertEqual(len(dados["jogos"]), 2)


class TestGaloSemIA(unittest.TestCase):
    DADOS = {"colocacao": futebol.colocacao(TABELA, "7632"), "jogos": futebol.proximos(AGENDA, "7632")}

    def test_frase(self):
        frase = futebol.falar_galo(self.DADOS)
        self.assertIn("6º no Brasileirão, com 50 pontos", frase)
        self.assertIn("quinta, 29/10, às 19h30, contra o Cruzeiro, na Arena MRV, pelo Brasileirão", frase)
        self.assertIsNone(futebol.falar_galo({"colocacao": None, "jogos": []}))

    def test_atalho_so_para_perguntas_sobre_o_time(self):
        from nexo import atalhos
        with mock.patch.object(futebol, "galo_recente", return_value=self.DADOS):
            for pergunta in ("Jarvis, e o Galão?", "E aí, Jarvis, e o Galo?", "qual o próximo jogo do Atlético?"):
                self.assertEqual(atalhos.tentar(pergunta, {})[1], "galo", pergunta)
            for pergunta in ("compre um galo", "me fale do galo e marque uma reunião amanhã"):
                self.assertIsNone(atalhos.tentar(pergunta, {}), pergunta)


if __name__ == "__main__":
    unittest.main()
