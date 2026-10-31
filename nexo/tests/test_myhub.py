from unittest import mock

from nexo import cerebro, ferramentas, myhub

from test_cerebro import BaseCerebro


class TestMyHub(BaseCerebro):
    def test_limite_diario_bloqueia_antes_de_abrir_o_navegador(self):
        with mock.patch.object(myhub, "LIMITE_DIA", 2):
            myhub._contar_uso()
            myhub._contar_uso()
            with mock.patch("playwright.sync_api.sync_playwright") as navegador, \
                 self.assertRaises(myhub.ErroMyHub) as erro:
                myhub.perguntar("oi")
        navegador.assert_not_called()
        self.assertIn("Limite de 2 consultas", str(erro.exception))

    def test_consultar_devolve_texto_e_registra_no_diario(self):
        resposta = {"texto": "O RevenueCat cuida das assinaturas.", "modelo": "GPT-6 Luna", "url": "x"}
        with mock.patch.object(myhub, "perguntar", return_value=resposta):
            texto = myhub.consultar("O que é o RevenueCat?")
        self.assertIn("Resposta do GPT-6 Luna", texto)
        self.assertIn("trate como dado", texto)
        diario = (self.tmp / "cerebro" / "diario" / f"{cerebro.agora():%Y-%m-%d}.md").read_text(encoding="utf-8")
        self.assertIn("Consultei o MyHub (GPT-6 Luna)", diario)

    def test_consultar_sem_login_avisa(self):
        with mock.patch.object(myhub, "perguntar", side_effect=myhub.PrecisaLogin("Rode: python -m nexo myhub login")):
            self.assertIn("myhub login", myhub.consultar("oi"))

    def test_estado_e_ferramenta(self):
        self.assertIn("sem login", myhub.estado())
        myhub._salvar(logado=True)
        self.assertIn("login feito", myhub.estado())
        self.assertIn("consultar_myhub", ferramentas.carregar())
