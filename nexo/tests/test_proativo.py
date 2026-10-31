import datetime as dt
import os
from unittest import mock

from nexo import cerebro, config, ia, proativo

from test_cerebro import BaseCerebro

AGORA = dt.datetime(2026, 10, 27, 9, 0)


class BaseProativo(BaseCerebro):
    def setUp(self):
        super().setUp()
        self.relogio = [AGORA]
        p = mock.patch.object(cerebro, "agora", side_effect=lambda: self.relogio[0])
        p.start()
        self.addCleanup(p.stop)
        n = mock.patch.object(proativo, "notificar", return_value=True)
        n.start()
        self.addCleanup(n.stop)

    def andar(self, **delta):
        self.relogio[0] += dt.timedelta(**delta)


class TestLembretes(BaseProativo):
    def test_lembrete_por_minutos_vence_na_hora(self):
        self.assertIn("às 09:30", proativo.lembrar("ligar para a Ana", minutos=30))
        self.assertEqual(proativo.lembretes_vencidos(), [])
        self.andar(minutes=30)
        vencidos = proativo.lembretes_vencidos()
        self.assertEqual([l["texto"] for l in vencidos], ["ligar para a Ana"])
        self.assertEqual(proativo.lembretes_vencidos(), [])  # não repete

    def test_horario_que_ja_passou_vai_para_amanha(self):
        self.assertIn("amanhã às 08:00", proativo.lembrar("academia", horario="8h"))
        self.assertIn("hoje às 14:30", proativo.lembrar("reunião", horario="14:30"))
        self.assertIn("reunião", proativo.listar_lembretes())

    def test_sem_quando_da_erro(self):
        with self.assertRaises(ValueError):
            proativo.lembrar("algo")


class TestHabitos(BaseProativo):
    def test_marcar_habito(self):
        r = proativo.marcar_habito("saúde")
        self.assertIn("Marquei 'Saúde'", r)
        self.assertNotIn("Saúde", proativo.habitos_pendentes())
        self.assertIn("- [x] Saúde", (config.CEREBRO / "HABITOS.md").read_text(encoding="utf-8"))

    def test_virada_arquiva_e_recomeca(self):
        proativo.marcar_habito("saúde")
        habitos = config.CEREBRO / "HABITOS.md"
        ontem = (AGORA - dt.timedelta(days=1)).timestamp()
        os.utime(habitos, (ontem, ontem))
        self.assertTrue(proativo.virar_dia_habitos("2026-10-26"))
        texto = habitos.read_text(encoding="utf-8")
        self.assertIn("## Histórico\n- 2026-10-26: 1/4", texto)
        self.assertEqual(len(proativo.habitos_pendentes()), 4)
        self.assertEqual(cerebro.checar()["links_quebrados"], [])

    def test_virada_nao_arquiva_lista_de_hoje(self):
        habitos = config.CEREBRO / "HABITOS.md"
        os.utime(habitos, (AGORA.timestamp(), AGORA.timestamp()))   # mexida "hoje"
        self.assertFalse(proativo.virar_dia_habitos("2026-10-26"))


class TestBatimento(BaseProativo):
    def test_avisa_entrada_nova_uma_vez(self):
        self.assertEqual(proativo.batimento(), [])
        cerebro.guardar("ideia nova")
        avisos = proativo.batimento()
        self.assertTrue(any("caixa de entrada" in a for a in avisos))
        self.assertEqual(proativo.batimento(), [])

    def test_cobra_habitos_depois_das_18h_uma_vez(self):
        self.assertEqual(proativo.batimento(), [])
        self.andar(hours=10)  # 19h
        avisos = proativo.batimento()
        self.assertTrue(any("faltam hoje" in a for a in avisos))
        self.assertEqual(proativo.batimento(), [])


class TestBomDiaEReflexao(BaseProativo):
    def test_contexto_e_bom_dia(self):
        proativo.lembrar("reunião", horario="15:00")
        cerebro.guardar("pendente")
        with mock.patch("nexo.ferramentas.internet.clima", return_value="Brasília: 22 graus."), \
             mock.patch.object(ia, "perguntar", return_value=ia.Resposta("Bom dia, senhor.", "gemini")) as p:
            texto = proativo.bom_dia()
        self.assertEqual(texto, "Bom dia, senhor.")
        prompt = p.call_args.args[0]
        self.assertIn("reunião às 15:00", prompt)
        self.assertIn("Brasília: 22 graus.", prompt)
        self.assertIn('"caixa_de_entrada": 1', prompt)
        diario = (config.CEREBRO / "diario" / "2026-10-27.md").read_text(encoding="utf-8")
        self.assertIn("Bom dia: Bom dia, senhor.", diario)

    def test_reflexao_promove_para_memoria_sem_tocar_alma(self):
        self.relogio[0] = AGORA - dt.timedelta(days=1)
        cerebro.registrar_diario("Decidi gravar a série de vídeos às sextas.")
        self.relogio[0] = AGORA
        alma = (config.CEREBRO / "ALMA.md").read_text(encoding="utf-8")
        dados = {"decisoes": ["Gravar a série de vídeos às sextas."], "licoes": [], "fatos": [],
                 "sugestoes_alma": ["Ser mais breve de manhã."]}
        with mock.patch.object(ia, "perguntar", return_value=ia.Resposta("{}", "claude", dados)):
            resumo = proativo.refletir()
        memoria = (config.CEREBRO / "MEMORIA.md").read_text(encoding="utf-8")
        self.assertIn("## Decisões\n- 2026-10-26: Gravar a série de vídeos às sextas.", memoria)
        self.assertEqual(alma, (config.CEREBRO / "ALMA.md").read_text(encoding="utf-8"))
        self.assertIn("Ser mais breve", resumo)
        # rodar de novo não duplica
        with mock.patch.object(ia, "perguntar", return_value=ia.Resposta("{}", "claude", dados)):
            proativo.refletir()
        memoria2 = (config.CEREBRO / "MEMORIA.md").read_text(encoding="utf-8")
        self.assertEqual(memoria2.count("Gravar a série"), 1)


class TestUmaVigiaSo(BaseCerebro):
    def test_segunda_vigia_nao_inicia(self):
        import subprocess
        import sys
        codigo = ("import sys, time; from nexo import proativo; ok = proativo.reservar_vigia(); "
                  "print(ok, flush=True); time.sleep(float(sys.argv[1]) if ok else 0)")
        ambiente = dict(os.environ, NEXO_DADOS=str(config.DADOS), PYTHONPATH=str(config.RAIZ))
        primeira = subprocess.Popen([sys.executable, "-c", codigo, "5"], env=ambiente,
                                    stdout=subprocess.PIPE, text=True, cwd=config.RAIZ)
        try:
            self.assertEqual(primeira.stdout.readline().strip(), "True")
            segunda = subprocess.run([sys.executable, "-c", codigo, "0"], env=ambiente,
                                     capture_output=True, text=True, cwd=config.RAIZ, timeout=30)
            self.assertEqual(segunda.stdout.strip(), "False")
        finally:
            primeira.kill()
            primeira.wait()


class TestVigia(BaseProativo):
    def test_passo_dispara_lembrete_bom_dia_e_virada_uma_vez(self):
        avisos = []
        proativo.lembrar("tomar água", minutos=1)
        self.andar(minutes=1)
        with mock.patch.object(proativo, "bom_dia", return_value="Bom dia!"), \
             mock.patch.object(proativo, "refletir") as refletir, \
             mock.patch.object(ia, "disponiveis", return_value=["gemini"]):
            v = proativo.Vigia(avisos.append)
            v.passo()
            v.passo()
        self.assertIn("Lembrete, senhor: tomar água", avisos)
        self.assertEqual(avisos.count("Bom dia!"), 1)
        refletir.assert_called_once_with("2026-10-26")
