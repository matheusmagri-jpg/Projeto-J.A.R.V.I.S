import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nexo import agente, busca, cerebro, config, ia, sessao

MODELO = Path(__file__).resolve().parent.parent / "cerebro"


class BaseCerebro(unittest.TestCase):
    """Cada teste roda numa cópia do cérebro, nunca no de verdade."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(MODELO, self.tmp / "cerebro")
        self.patches = [mock.patch.object(config, "CEREBRO", self.tmp / "cerebro"),
                        mock.patch.object(config, "DADOS", self.tmp / "dados")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestCerebro(BaseCerebro):
    def test_cerebro_inicial_saudavel(self):
        self.assertEqual(cerebro.checar(), {"links_quebrados": [], "notas_soltas": [], "sem_metadados": []})

    def test_criar_nota_liga_ao_indice(self):
        cerebro.criar_nota("pessoa", "Ana Souza", "Editora dos vídeos.", ligar=["Sexta-Feira"])
        indice = cerebro.ler("Pessoas.md")
        self.assertIn("Ana Souza", indice.links)
        nota = cerebro.ler("pessoas/Ana Souza.md")
        self.assertEqual(nota.meta["tipo"], "pessoa")
        self.assertIn("Sexta-Feira", nota.links)
        self.assertEqual(cerebro.checar()["links_quebrados"], [])

    def test_criar_nota_nao_repete_titulo(self):
        cerebro.criar_nota("ideia", "Títulos", "# Boas Práticas de Títulos\n\n1. Seja curto.")
        corpo = cerebro.ler("ideias/Títulos.md").corpo
        self.assertEqual(corpo.count("\n# ") + corpo.startswith("# "), 1)
        self.assertIn("1. Seja curto.", corpo)

    def test_criar_nota_existente_acrescenta(self):
        cerebro.criar_nota("ideia", "Canal de cortes", "Primeira versão.")
        cerebro.criar_nota("ideia", "Canal de cortes", "Segunda versão.")
        corpo = cerebro.ler("ideias/Canal de cortes.md").corpo
        self.assertIn("Primeira versão.", corpo)
        self.assertIn("Segunda versão.", corpo)
        self.assertEqual(cerebro.ler("Ideias.md").corpo.count("[[Canal de cortes]]"), 1)

    def test_conflito_quando_nota_muda(self):
        nota = cerebro.ler("MEMORIA.md")
        (config.CEREBRO / "MEMORIA.md").write_text("editado no Obsidian", encoding="utf-8")
        with self.assertRaises(cerebro.Conflito):
            cerebro.escrever("MEMORIA.md", "nova", hash_esperado=nota.hash)

    def test_alma_protegida(self):
        with self.assertRaises(PermissionError):
            cerebro.escrever("ALMA.md", "outra alma")

    def test_guardar_e_diario(self):
        cerebro.guardar("Lembrar de gravar o vídeo sobre a Sexta-Feira")
        self.assertEqual(len(cerebro.pendentes()), 1)
        p = cerebro.registrar_diario("teste\nsegunda linha")
        texto = p.read_text(encoding="utf-8")
        self.assertIn("(nexo) teste", texto)
        self.assertIn("  segunda linha", texto)
        self.assertEqual(cerebro.checar()["links_quebrados"], [])

    def test_nome_arquivo_remove_caracteres_proibidos(self):
        self.assertEqual(cerebro.nome_arquivo('a/b:c?"d"'), "a b c d")


class TestBusca(BaseCerebro):
    def test_busca_sem_acento_e_prefixo(self):
        r = busca.buscar("decisao gemini")
        self.assertEqual(r[0].titulo, "Claude e Gemini juntos")
        self.assertTrue(busca.buscar("briefing"))

    def test_indice_incremental(self):
        self.assertGreater(busca.indexar(), 0)
        self.assertEqual(busca.indexar(), 0)
        cerebro.criar_nota("ideia", "Robô de xadrez", "Projeto para o fim de semana.")
        self.assertGreaterEqual(busca.indexar(), 1)
        self.assertEqual(busca.buscar("xadrez")[0].titulo, "Robô de xadrez")


class TestIA(unittest.TestCase):
    def setUp(self):
        ia._cache_respostas.clear()

    def test_rapido_cai_para_claude_quando_gemini_falha(self):
        def falha(*_):
            raise RuntimeError("cota")
        provs = {
            "ollama": (lambda *_: "nao deve usar", lambda: False),
            "gemini": (falha, lambda: True),
            "claude": (lambda *_: "ok", lambda: True),
        }
        with mock.patch.dict(ia.PROVEDORES, provs):
            r = ia.perguntar("oi", modo="rapido")
        self.assertEqual((r.texto, r.provedor), ("ok", "claude"))

    def test_ordem_tem_ollama_primeiro(self):
        self.assertEqual(ia.ORDEM["rapido"][0], "ollama")
        self.assertEqual(ia.ORDEM["profundo"][0], "ollama")

    def test_cache_reduz_chamadas_repetidas(self):
        chamadas = []

        def ollama(*_):
            chamadas.append(1)
            return "resposta local"

        provs = {
            "ollama": (ollama, lambda: True),
            "gemini": (lambda *_: "g", lambda: True),
            "claude": (lambda *_: "c", lambda: True),
        }
        with mock.patch.dict(ia.PROVEDORES, provs):
            r1 = ia.perguntar("teste repetido", modo="rapido")
            r2 = ia.perguntar("teste repetido", modo="rapido")
        self.assertEqual((r1.texto, r2.texto), ("resposta local", "resposta local"))
        self.assertEqual(len(chamadas), 1)

    def test_dupla_junta_respostas(self):
        pedidos = []

        def claude(prompt, *_):
            pedidos.append(prompt)
            return "final" if "Duas IAs" in prompt else "c"
        provs = {
            "ollama": (lambda *_: "nao deve usar", lambda: False),
            "gemini": (lambda *_: "g", lambda: True),
            "claude": (claude, lambda: True),
        }
        with mock.patch.dict(ia.PROVEDORES, provs):
            r = ia.perguntar("oi", modo="dupla")
        self.assertEqual((r.texto, r.provedor), ("final", "claude+gemini"))
        self.assertIn('<resposta ia="gemini">\ng', pedidos[-1])

    def test_sem_chave(self):
        provs = {
            "ollama": (None, lambda: False),
            "gemini": (None, lambda: False),
            "claude": (None, lambda: False),
        }
        with mock.patch.dict(ia.PROVEDORES, provs), self.assertRaises(ia.SemIA):
            ia.perguntar("oi")


class TestSessao(BaseCerebro):
    def test_resumo_so_de_mensagens_novas(self):
        transcript = self.tmp / "s.jsonl"
        linhas = [{"type": "user", "message": {"content": "decidi usar FTS5"}},
                  {"type": "assistant", "message": {"content": [{"type": "text", "text": "feito"}]}}]
        transcript.write_text("\n".join(json.dumps(l) for l in linhas), encoding="utf-8")
        resposta = ia.Resposta("- Decisão: usar FTS5 na [[Sexta-Feira]]", "gemini")
        with mock.patch.object(ia, "disponiveis", return_value=["gemini"]), \
             mock.patch.object(ia, "perguntar", return_value=resposta) as chamada:
            sessao.resumir(str(transcript), "abc")
            sessao.resumir(str(transcript), "abc")  # nada novo: não resume de novo
        self.assertEqual(chamada.call_count, 1)
        diario = (config.CEREBRO / "diario" / f"{cerebro.agora():%Y-%m-%d}.md").read_text(encoding="utf-8")
        self.assertIn("usar FTS5", diario)


class TestAgenteCacheSemantico(BaseCerebro):
    def setUp(self):
        super().setUp()
        agente._cache_semantico.clear()

    def test_reaproveita_resposta_para_perguntas_parecidas(self):
        resposta = ia.Resposta("A edição fica com a Ana.", "ollama")
        with mock.patch.object(ia, "perguntar", return_value=resposta) as chamar_ia:
            r1 = agente.responder("quem edita meus videos?", modo="rapido", registrar=False)
            r2 = agente.responder("quem edita meus vídeos", modo="rapido", registrar=False)
        self.assertEqual((r1.texto, r2.texto), ("A edição fica com a Ana.", "A edição fica com a Ana."))
        self.assertEqual(chamar_ia.call_count, 1)


if __name__ == "__main__":
    unittest.main()
