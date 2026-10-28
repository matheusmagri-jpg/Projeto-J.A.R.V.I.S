import importlib
import json
import sys
import unittest


MODULE_NAME = "gerar_briefing"


class GerarBriefingTests(unittest.TestCase):
    def test_gerar_briefing_cria_arquivo_de_texto(self):
        mod = importlib.import_module(MODULE_NAME)
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            mod.PASTA = tmp_path
            mod.revenuecat = lambda: {
                "receita": 12000,
                "receitaVar": 10.5,
                "assinantes": 250,
                "assinantesVar": 2.2,
                "ads": 3000,
                "adsVar": -5,
                "roas": 4.0,
                "roasVar": 0.3,
            }
            mod.meta_ads = lambda: {}
            mod.ler_json = lambda path: [
                ["Ana — cobrança em dobro", "Precisa de você", "bad"],
                ["Maria — como cancelo?", "Respondido (FAQ #1)", "ok"],
            ]

            emails_path = tmp_path / "emails.json"
            emails_path.write_text(json.dumps([["Ana — cobrança em dobro", "Precisa de você", "bad"], ["Maria — como cancelo?", "Respondido (FAQ #1)", "ok"]]), encoding="utf-8")
            priorities_path = tmp_path / "prioridades.json"
            priorities_path.write_text(json.dumps([["Revisar campanha de tráfego", "warn"]]), encoding="utf-8")

            original_argv = sys.argv[:]
            try:
                sys.argv = [
                    "gerar_briefing.py",
                    "--emails",
                    str(emails_path),
                    "--prioridades",
                    str(priorities_path),
                    "--sem-audio",
                ]
                mod.main()
            finally:
                sys.argv = original_argv

            briefing = (tmp_path / "briefing.txt").read_text(encoding="utf-8")
            self.assertIn("Seu resumo está pronto", briefing)
            self.assertIn("Receita", briefing)

            data = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))
            self.assertEqual(data["briefing"], briefing)


if __name__ == "__main__":
    unittest.main()
