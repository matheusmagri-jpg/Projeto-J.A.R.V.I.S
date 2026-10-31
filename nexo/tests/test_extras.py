import unittest
from types import SimpleNamespace as NS
from unittest import mock

from nexo import ferramentas, ia
from nexo.ferramentas import extras


class TestPesquisa(unittest.TestCase):
    def test_usa_claude_quando_disponivel(self):
        with mock.patch.object(ia, "disponiveis", return_value=["claude", "gemini"]), \
             mock.patch.object(extras, "_pesquisa_claude", return_value="Resposta do Claude"), \
             mock.patch.object(extras, "_pesquisa_gemini") as gemini:
            self.assertEqual(extras.pesquisar_na_internet("dólar hoje"), "Resposta do Claude")
        gemini.assert_not_called()

    def test_cai_para_gemini_e_depois_para_o_navegador(self):
        with mock.patch.object(ia, "disponiveis", return_value=["claude", "gemini"]), \
             mock.patch.object(extras, "_pesquisa_claude", side_effect=RuntimeError("sem crédito")), \
             mock.patch.object(extras, "_pesquisa_gemini", return_value="Resposta do Gemini"):
            self.assertEqual(extras.pesquisar_na_internet("x"), "Resposta do Gemini")
        with mock.patch.object(ia, "disponiveis", return_value=["claude", "gemini"]), \
             mock.patch.object(extras, "_pesquisa_claude", side_effect=RuntimeError("sem crédito")), \
             mock.patch.object(extras, "_pesquisa_gemini", side_effect=RuntimeError("cota")), \
             mock.patch.object(extras, "_pesquisa_gratis", side_effect=RuntimeError("busca grátis sem resultados")), \
             mock.patch("nexo.myhub.logado", return_value=False), \
             mock.patch("nexo.myhub.consultar") as myhub, \
             mock.patch("nexo.ferramentas.computador.pesquisar") as navegador:
            r = extras.pesquisar_na_internet("x")
        navegador.assert_called_once_with("x", "google")
        myhub.assert_not_called()
        self.assertIn("abri a pesquisa no navegador", r)

    def test_tenta_o_myhub_antes_do_navegador(self):
        with mock.patch.object(ia, "disponiveis", return_value=[]), \
             mock.patch.object(extras, "_pesquisa_gratis", side_effect=RuntimeError("sem resultados")), \
             mock.patch("nexo.myhub.logado", return_value=True), \
             mock.patch("nexo.myhub.consultar", return_value="Resposta do GPT-6 Luna pelo MyHub: 6º lugar.") as myhub, \
             mock.patch("nexo.ferramentas.computador.pesquisar") as navegador:
            r = extras.pesquisar_na_internet("colocação do Galo")
        myhub.assert_called_once_with("colocação do Galo")
        navegador.assert_not_called()
        self.assertIn("6º lugar", r)

    def test_usa_a_busca_gratis_antes_do_navegador(self):
        with mock.patch.object(ia, "disponiveis", return_value=["claude", "gemini"]), \
             mock.patch.object(extras, "_pesquisa_claude", side_effect=RuntimeError("sem crédito")), \
             mock.patch.object(extras, "_pesquisa_gemini", side_effect=RuntimeError("cota")), \
             mock.patch.object(extras, "_pesquisa_gratis", return_value="Resposta grátis"), \
             mock.patch("nexo.ferramentas.computador.pesquisar") as navegador:
            self.assertEqual(extras.pesquisar_na_internet("x"), "Resposta grátis")
        navegador.assert_not_called()


DDG = """
<a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad=1">Anúncio</a>
<a class="result__snippet" href="#">propaganda</a>
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexemplo.com%2Fdolar&amp;rut=x">Dólar <b>hoje</b></a>
<a class="result__snippet" href="#">O dólar fecha a R$&nbsp;5,10.</a>
"""
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Notícia A - Jornal</title><link>https://news.google.com/a</link>
<pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate><description>&lt;a&gt;Resumo A&lt;/a&gt;</description></item>
</channel></rss>"""


class TestPesquisaGratis(unittest.TestCase):
    def test_duckduckgo_extrai_resultados_e_pula_anuncio(self):
        with mock.patch.object(extras, "_baixar", return_value=DDG):
            r = extras._buscar_duckduckgo("dólar")
        self.assertEqual(r, [{"titulo": "Dólar hoje", "link": "https://exemplo.com/dolar",
                              "trecho": "O dólar fecha a R$ 5,10."}])

    def test_google_noticias_le_o_rss(self):
        with mock.patch.object(extras, "_baixar", return_value=RSS):
            r = extras._buscar_google_noticias("notícia")
        self.assertEqual(r[0]["titulo"], "Notícia A - Jornal")
        self.assertEqual(r[0]["link"], "https://news.google.com/a")
        self.assertIn("Resumo A", r[0]["trecho"])

    def test_junta_as_duas_fontes(self):
        with mock.patch.object(extras, "_buscar_duckduckgo",
                               return_value=[{"titulo": "D", "link": "https://d", "trecho": "d"}]), \
             mock.patch.object(extras, "_buscar_google_noticias",
                               return_value=[{"titulo": "N", "link": "https://n", "trecho": "n"}]), \
             mock.patch.object(ia, "disponiveis", return_value=[]):
            r = extras._pesquisa_gratis("p")
        self.assertIn("[1] N — n (https://n)", r)
        self.assertIn("[2] D — d (https://d)", r)

    def test_cai_para_noticias_e_resume_com_gemini_sem_busca(self):
        with mock.patch.object(extras, "_buscar_duckduckgo", return_value=[]), \
             mock.patch.object(extras, "_buscar_google_noticias",
                               return_value=[{"titulo": "T", "link": "https://a", "trecho": "x"}]), \
             mock.patch.object(ia, "disponiveis", return_value=["gemini"]), \
             mock.patch.object(ia, "gerar_gemini", return_value=NS(text="Resumo.")) as g:
            r = extras._pesquisa_gratis("p")
        self.assertEqual(r, "Resumo.\nFontes: https://a")
        self.assertEqual(g.call_args.kwargs["modelos"], extras.GEMINI_SEM_BUSCA)
        self.assertIsNone(g.call_args.args[1].tools)

    def test_fonte_do_google_noticias_e_o_nome_do_jornal(self):
        with mock.patch.object(extras, "_buscar_duckduckgo", return_value=[]), \
             mock.patch.object(extras, "_buscar_google_noticias",
                               return_value=[{"titulo": "Manchete - UOL", "link": "https://news.google.com/x",
                                              "trecho": "x"}]), \
             mock.patch.object(ia, "disponiveis", return_value=["gemini"]), \
             mock.patch.object(ia, "gerar_gemini", return_value=NS(text="Resumo.")):
            self.assertEqual(extras._pesquisa_gratis("p"), "Resumo.\nFontes: UOL")

    def test_sem_gemini_devolve_os_trechos(self):
        with mock.patch.object(extras, "_buscar_duckduckgo", side_effect=OSError("rede")), \
             mock.patch.object(extras, "_buscar_google_noticias",
                               return_value=[{"titulo": "T", "link": "https://a", "trecho": "x"}]), \
             mock.patch.object(ia, "disponiveis", return_value=["gemini"]), \
             mock.patch.object(ia, "gerar_gemini", side_effect=RuntimeError("cota")):
            r = extras._pesquisa_gratis("p")
        self.assertIn("[1] T — x (https://a)", r)

    def test_sem_resultados_falha(self):
        with mock.patch.object(extras, "_buscar_duckduckgo", return_value=[]), \
             mock.patch.object(extras, "_buscar_google_noticias", return_value=[]):
            with self.assertRaises(RuntimeError):
                extras._pesquisa_gratis("p")

    def test_claude_extrai_fontes(self):
        resposta = NS(stop_reason="end_turn", content=[
            NS(type="server_tool_use"),
            NS(type="text", text="O dólar fechou em R$ 5,10.",
               citations=[NS(url="https://exemplo.com/a"), NS(url="https://exemplo.com/a")]),
        ])
        cliente = NS(beta=NS(messages=NS(create=lambda **kw: resposta)))
        with mock.patch.object(ia, "cliente", return_value=cliente):
            r = extras._pesquisa_claude("dólar")
        self.assertEqual(r, "O dólar fechou em R$ 5,10.\nFontes: https://exemplo.com/a")


class TestOutras(unittest.TestCase):
    def test_resumir_video_exige_link_do_youtube(self):
        self.assertIn("link de vídeo do YouTube", extras.resumir_video("https://vimeo.com/123"))
        with mock.patch.object(ia, "gerar_gemini", return_value=NS(text="Resumo.")) as g:
            self.assertEqual(extras.resumir_video("https://youtu.be/jNQXAC9IVRw"), "Resumo.")
        self.assertEqual(g.call_args.args[0].parts[0].file_data.file_uri, "https://youtu.be/jNQXAC9IVRw")

    def test_ver_tela_pede_confirmacao(self):
        self.assertTrue(ferramentas.carregar()["ver_tela"].confirmar)

    def test_midia_limita_repeticoes(self):
        with mock.patch.object(extras.ctypes, "windll", create=True) as windll, \
             mock.patch.object(extras.os, "name", "nt"):
            extras.controlar_midia("volume_mais", 999)
            self.assertEqual(windll.user32.keybd_event.call_count, 50)  # 25 apertos x (descer + subir)
            windll.reset_mock()
            extras.controlar_midia("tocar_pausar", 10)
            self.assertEqual(windll.user32.keybd_event.call_count, 2)

    def test_copiar_passa_texto_por_variavel_de_ambiente(self):
        with mock.patch.object(extras, "_powershell", return_value=NS(returncode=0)) as ps:
            extras.copiar_para_area_de_transferencia('"; Remove-Item C:\\ -Recurse; "')
        comando, ambiente = ps.call_args.args[0], ps.call_args.kwargs
        self.assertNotIn("Remove-Item", comando)
        self.assertEqual(ambiente["NEXO_COPIAR"], '"; Remove-Item C:\\ -Recurse; "')

    def test_estado_do_pc(self):
        texto = extras.estado_do_pc()
        self.assertIn("Processador em", texto)
        self.assertIn("ligado há", texto)
