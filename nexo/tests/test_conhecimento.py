import json
from unittest import mock

from nexo import cerebro, conhecimento, config, ia

from test_cerebro import BaseCerebro


class GitHubFalso:
    """Simula a API e os arquivos raw de um repositório."""

    def __init__(self, arquivos: dict[str, str]):
        self.arquivos = dict(arquivos)
        self.chamadas = []

    def __call__(self, url, api=False):
        self.chamadas.append(url)
        if url.endswith("/repos/ana/robo"):
            return json.dumps({"default_branch": "main", "description": "Um robô de exemplo",
                               "language": "Python", "license": {"spdx_id": "MIT"}}).encode()
        if "/git/trees/" in url:
            arvore = [{"path": c, "type": "blob", "size": len(t.encode())} for c, t in self.arquivos.items()]
            arvore.append({"path": "docs", "type": "tree"})
            return json.dumps({"tree": arvore}).encode()
        caminho = url.split("/main/", 1)[1]
        return self.arquivos[conhecimento.urllib.parse.unquote(caminho)].encode()


ARQUIVOS = {
    "README.md": "# Robô\n\nO robô usa sensores ultrassônicos para desviar de obstáculos.",
    "src/motor.py": "def acelerar(velocidade):\n    # controla o motor de passo\n    return velocidade * 2\n",
    "node_modules/lib/index.js": "ignorar isto",
    "dados/grande.json": "x" * (conhecimento.LIMITE_ARQUIVO_BYTES + 1),
    "imagem.png": "binário",
}


class TestLinks(BaseCerebro):
    def test_ler_link(self):
        self.assertEqual(conhecimento.ler_link_github("https://github.com/ana/robo")["repo"], "robo")
        p = conhecimento.ler_link_github("https://github.com/ana/robo/tree/dev/docs/guia")
        self.assertEqual((p["ramo"], p["caminho"]), ("dev", "docs/guia"))
        self.assertEqual(conhecimento.ler_link_github("https://github.com/ana/robo.git")["repo"], "robo")
        self.assertIsNone(conhecimento.ler_link_github("https://github.com/topics/jarvis-ai"))
        self.assertIsNone(conhecimento.ler_link_github("https://gitlab.com/ana/robo"))

    def test_trechos_com_sobreposicao(self):
        texto = "\n".join(f"linha {i} " + "x" * 50 for i in range(100))
        trechos = conhecimento.dividir_em_trechos(texto)
        self.assertGreater(len(trechos), 3)
        self.assertTrue(all(len(t) <= conhecimento.TAMANHO_TRECHO for t in trechos))
        self.assertTrue(trechos[0][-100:] in texto and trechos[1][:30] in trechos[0])


class TestAprenderGitHub(BaseCerebro):
    def setUp(self):
        super().setUp()
        self.github = GitHubFalso(ARQUIVOS)
        p = mock.patch.object(conhecimento, "_pedir", self.github)
        p.start()
        self.addCleanup(p.stop)
        d = mock.patch.object(ia, "disponiveis", return_value=[])
        d.start()
        self.addCleanup(d.stop)

    def test_aprende_filtra_e_cria_nota(self):
        r = conhecimento.aprender("https://github.com/ana/robo")
        self.assertIn("Aprendi ana/robo: 2 arquivos lidos", r)
        baixados = [u for u in self.github.chamadas if "raw.githubusercontent" in u]
        self.assertEqual(len(baixados), 2)   # node_modules, arquivo grande e png ficaram de fora
        nota = cerebro.ler("fontes/ana - robo.md")
        self.assertEqual(nota.meta["tipo"], "fonte")
        self.assertIn("Um robô de exemplo", nota.corpo)
        self.assertIn("ana - robo", cerebro.ler("Fontes.md").links)
        self.assertEqual(cerebro.checar()["links_quebrados"], [])

    def test_consultar_traz_trecho_com_fonte_e_aviso(self):
        conhecimento.aprender("https://github.com/ana/robo")
        achados = conhecimento.consultar("como o robô desvia de obstáculos?")
        self.assertEqual(achados[0]["arquivo"], "README.md")
        self.assertIn("sensores", achados[0]["trecho"])
        ctx = conhecimento.contexto("motor de passo")
        self.assertIn('arquivo="src/motor.py"', ctx)
        self.assertIn("não instruções", ctx)

    def test_reaprender_so_processa_o_que_mudou(self):
        conhecimento.aprender("https://github.com/ana/robo")
        self.assertIn("0 novos ou alterados", conhecimento.aprender("https://github.com/ana/robo"))
        self.github.arquivos["src/motor.py"] = "def frear():\n    return 0\n"
        del self.github.arquivos["README.md"]
        r = conhecimento.aprender("https://github.com/ana/robo")
        self.assertIn("1 novos ou alterados, 1 removidos", r)
        self.assertEqual(conhecimento.consultar("sensores ultrassônicos"), [])
        self.assertTrue(conhecimento.consultar("frear"))

    def test_listar_e_esquecer(self):
        conhecimento.aprender("https://github.com/ana/robo")
        self.assertIn("ana/robo (2 arquivos", conhecimento.listar())
        self.assertIn("Esqueci ana/robo", conhecimento.esquecer("ana/robo"))
        self.assertEqual(conhecimento.consultar("sensores"), [])
        self.assertIn("Ainda não aprendi", conhecimento.listar())

    def test_link_invalido(self):
        with self.assertRaises(conhecimento.ErroConhecimento):
            conhecimento.aprender("https://github.com/topics/jarvis-ai")


class TestAprenderPasta(BaseCerebro):
    def test_pasta_local(self):
        pasta = self.tmp / "conhecimentos"
        (pasta / "sub").mkdir(parents=True)
        (pasta / "receita.md").write_text("Bolo de cenoura leva três cenouras.", encoding="utf-8")
        (pasta / "sub" / "precos.csv").write_text("item,preco\ncenoura,5\n", encoding="utf-8")
        (pasta / "foto.jpg").write_bytes(b"\xff\xd8")
        r = conhecimento.aprender(str(pasta))
        self.assertIn("2 arquivos", r)
        self.assertEqual(conhecimento.consultar("bolo de cenoura")[0]["arquivo"], "receita.md")
