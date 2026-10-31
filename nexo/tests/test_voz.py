import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from nexo import voz


def setUpModule():
    # Os testes não leem nem gravam a voz que o usuário escolheu de verdade.
    global _pasta_voz, _voz_escolhida
    _pasta_voz = tempfile.TemporaryDirectory()
    _voz_escolhida = mock.patch.object(voz, "VOZ_ESCOLHIDA", Path(_pasta_voz.name) / "voz.json")
    _voz_escolhida.start()


def tearDownModule():
    _voz_escolhida.stop()
    _pasta_voz.cleanup()


class TestEscolherVoz(unittest.TestCase):
    def setUp(self):
        voz.VOZ_ESCOLHIDA.unlink(missing_ok=True)
        self.addCleanup(voz.VOZ_ESCOLHIDA.unlink, missing_ok=True)
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        for p in (mock.patch.object(voz, "FALAS", Path(pasta.name)),
                  mock.patch("nexo.fishsite.disponivel", return_value=False)):
            p.start()
            self.addCleanup(p.stop)

    def test_lista_tem_as_vozes_novas_e_as_antigas(self):
        modelos = {v[1] for v in voz.VOZES.values()}
        self.assertLessEqual({voz.FISH_VOZ, "4b215a58407c4def88e0892def6421b2",
                              "733261dd2c1944009ceb33bfadd3935b", "102bccca7dc64b6b8f8494c199c5d153", None}, modelos)

    def test_padrao_e_o_jarvis_e_a_escolha_fica_guardada(self):
        self.assertEqual(voz.voz_atual(), "jarvis")
        self.assertTrue(voz.escolher_voz("julius"))
        self.assertEqual(voz.voz_atual(), "julius")

    def test_recusa_voz_fora_da_lista_e_ignora_arquivo_estragado(self):
        self.assertFalse(voz.escolher_voz("outra"))
        self.assertFalse(voz.VOZ_ESCOLHIDA.exists())
        for conteudo in ("{quebrado", "[]", '{"voz": "saiu-da-lista"}'):
            voz.VOZ_ESCOLHIDA.write_text(conteudo, encoding="utf-8")
            self.assertEqual(voz.voz_atual(), "jarvis")

    def test_api_do_fish_recebe_o_modelo_da_voz_escolhida(self):
        enviados = []

        class Resposta(io.BytesIO):
            pass

        def urlopen(pedido, timeout=None):
            enviados.append(json.loads(pedido.data)["reference_id"])
            return Resposta(b"mp3")
        voz.escolher_voz("narrador-chris")
        with mock.patch.dict("os.environ", {"FISH_API_KEY": "x"}), mock.patch.object(voz.request, "urlopen", urlopen):
            voz.gerar_mp3("Pois não, senhor?")
            voz.escolher_voz("julius")
            voz.gerar_mp3("Pois não, senhor?")   # a mesma frase em outra voz não vem do cache
        self.assertEqual(enviados, ["4b215a58407c4def88e0892def6421b2", "733261dd2c1944009ceb33bfadd3935b"])

    def test_site_do_fish_recebe_o_modelo_da_voz_escolhida(self):
        voz.escolher_voz("julius")
        with mock.patch.dict("os.environ", {}) as env, \
                mock.patch("nexo.fishsite.disponivel", return_value=True), \
                mock.patch("nexo.fishsite.gerar", return_value=b"mp3") as gerar:
            env.pop("FISH_API_KEY", None)
            voz.gerar_mp3("Pois não, senhor?")
        gerar.assert_called_once_with("Pois não, senhor?", "733261dd2c1944009ceb33bfadd3935b")

    def test_voz_do_edge_nao_chama_o_fish(self):
        voz.escolher_voz("antonio")
        with mock.patch.dict("os.environ", {"FISH_API_KEY": "x"}), \
                mock.patch("nexo.fishsite.disponivel", return_value=True):
            self.assertEqual([m[0] for m in voz.motores()], ["edge"])


class TestTextoFalado(unittest.TestCase):
    def test_limpa_markdown_e_links(self):
        texto = "**Pronto**, senhor. Veja [[Claude e Gemini juntos]] e [[USUARIO|Matheus]]: 98% em `arquivo.pdf`."
        self.assertEqual(voz.para_fala(texto),
                         "Pronto, senhor. Veja Claude e Gemini juntos e Matheus: 98 por cento em arquivo.pdf.")

    def test_listas_viram_frases(self):
        self.assertEqual(voz.para_fala("- um\n- dois"), "um dois")


class TestChamada(unittest.TestCase):
    def test_reconhece_o_nome_no_comeco(self):
        self.assertEqual(voz.chamou("Jarvis, que horas são?"), "que horas são?")
        self.assertEqual(voz.chamou("Ei Jarvis abre a calculadora"), "abre a calculadora")
        self.assertEqual(voz.chamou("Ok, Jarvis! Qual o clima?"), "Qual o clima?")
        self.assertEqual(voz.chamou("Jarvis."), "")

    def test_ignora_conversa_sem_o_nome_no_comeco(self):
        self.assertIsNone(voz.chamou("vou almoçar agora"))
        self.assertIsNone(voz.chamou("ontem falei com o Jarvis"))
        self.assertIsNone(voz.chamou("o jardim está bonito"))

    def test_sim_e_nao(self):
        self.assertTrue(voz.e_sim("Sim, pode."))
        self.assertTrue(voz.e_sim("claro"))
        self.assertFalse(voz.e_sim("Não, espera."))
        self.assertFalse(voz.e_sim(""))


AUDIOS = __import__("pathlib").Path(__file__).with_name("audios")


def _amostras(nome):
    with wave.open(str(AUDIOS / nome)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 1)


class MicrofoneComFrases:
    """Microfone simulado que "fala" as frases dadas, com silêncio entre elas."""

    def __init__(self, *nomes):
        silencio = np.zeros((voz.TAXA, 1), np.int16)
        partes = [silencio]
        for n in nomes:
            partes += [_amostras(n), silencio]
        self.audio = np.concatenate(partes)
        self.pos = 0

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self, n):
        bloco = self.audio[self.pos:self.pos + n]
        self.pos += n
        if len(bloco) < n:
            bloco = np.zeros((n, 1), np.int16)
        return bloco, False


class TestDetectorLocal(unittest.TestCase):
    def test_comeca_com_nome(self):
        self.assertEqual(voz.PALAVRAS_NOME, ["jarvis"])
        # o Vosk pequeno escreve "Jarvis" como "árvores" ou "jarbas"
        self.assertTrue(voz.comeca_com_nome("árvores [unk]"))
        self.assertTrue(voz.comeca_com_nome("[unk] ei jarbas"))
        self.assertTrue(voz.comeca_com_nome("ok árvores hoje"))
        self.assertFalse(voz.comeca_com_nome("hoje árvores"))
        self.assertFalse(voz.comeca_com_nome("jardim [unk]"))
        self.assertFalse(voz.comeca_com_nome(""))

    @unittest.skipUnless(voz.detector_disponivel(), "modelo Vosk não baixado")
    def test_ignora_outras_frases_e_acorda_com_o_nome(self):
        mic = MicrofoneComFrases("vamos_almocar.wav", "vamos_jantar.wav", "jarvis_que_horas.wav")
        limite = len(mic.audio) + voz.TAXA * 2
        with mock.patch("sounddevice.InputStream", mic):
            audio = voz.esperar_chamada(parar=lambda: mic.pos > limite)
        self.assertIsNotNone(audio, "não acordou com 'Jarvis, que horas são?'")
        # o áudio devolvido é a frase do chamado, não as anteriores
        with wave.open(io.BytesIO(audio)) as w:
            segundos = w.getnframes() / w.getframerate()
        self.assertLess(segundos, 5)

    @unittest.skipUnless(voz.detector_disponivel(), "modelo Vosk não baixado")
    def test_nao_acorda_sem_o_nome_no_comeco(self):
        mic = MicrofoneComFrases("falando_do_jarvis.wav", "vamos_jantar.wav", "vamos_almocar.wav")
        limite = len(mic.audio)
        with mock.patch("sounddevice.InputStream", mic):
            self.assertIsNone(voz.esperar_chamada(parar=lambda: mic.pos >= limite))

    def test_proxima_chamada_com_detector(self):
        with mock.patch.object(voz, "detector_disponivel", return_value=True), \
             mock.patch.object(voz, "esperar_chamada", return_value=b"wav"), \
             mock.patch.object(voz, "transcrever", return_value="Jarvis, que horas são?"):
            self.assertEqual(voz.proxima_chamada(escutar=None), "que horas são?")
        # Vosk acordou mas a transcrição não começa com NEXO: alarme falso
        with mock.patch.object(voz, "detector_disponivel", return_value=True), \
             mock.patch.object(voz, "esperar_chamada", return_value=b"wav"), \
             mock.patch.object(voz, "transcrever", return_value="hoje é sexta-feira, jardim"):
            self.assertIsNone(voz.proxima_chamada(escutar=None))
        # Vosk acordou e o nome veio logo depois de uma interjeição: vale
        with mock.patch.object(voz, "detector_disponivel", return_value=True), \
             mock.patch.object(voz, "esperar_chamada", return_value=b"wav"), \
             mock.patch.object(voz, "transcrever", return_value="Ô Jarvis, que horas são?"):
            self.assertEqual(voz.proxima_chamada(escutar=None), "que horas são?")
        # ...mas o nome no meio de uma frase longa não
        with mock.patch.object(voz, "detector_disponivel", return_value=True), \
             mock.patch.object(voz, "esperar_chamada", return_value=b"wav"), \
             mock.patch.object(voz, "transcrever", return_value="ontem falei com o Jarvis"):
            self.assertIsNone(voz.proxima_chamada(escutar=None))


class FluxoFalso:
    """Microfone simulado: silêncio, 1 s de voz, silêncio."""

    def __init__(self, *a, **kw):
        tam = int(voz.BLOCO * voz.TAXA)
        tom = (3000 * np.sin(np.arange(tam) * 0.3)).astype(np.int16).reshape(-1, 1)
        quieto = np.zeros((tam, 1), np.int16)
        self.blocos = [quieto] * 5 + [tom] * 10 + [quieto] * 30

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self, n):
        return self.blocos.pop(0), False


class TestOuvir(unittest.TestCase):
    def test_grava_a_frase_e_para_no_silencio(self):
        with mock.patch("sounddevice.InputStream", FluxoFalso):
            audio = voz.ouvir(limiar=500)
        with wave.open(io.BytesIO(audio)) as w:
            segundos = w.getnframes() / w.getframerate()
        # 1 s de voz + até 0,3 s antes + 0,9 s de silêncio final
        self.assertTrue(1.8 <= segundos <= 2.3, segundos)

    def test_ninguem_falou(self):
        class Quieto(FluxoFalso):
            def __init__(self, *a, **kw):
                super().__init__()
                self.blocos = [np.zeros((int(voz.BLOCO * voz.TAXA), 1), np.int16)] * 200
        with mock.patch("sounddevice.InputStream", Quieto):
            self.assertIsNone(voz.ouvir(limiar=500, espera_maxima=0))


class TestMotoresDeVoz(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        p = mock.patch.object(voz, "FALAS", Path(self.pasta.name))
        p.start()
        self.addCleanup(p.stop)
        from nexo import fishsite
        q = mock.patch.object(fishsite, "disponivel", return_value=False)   # estes testes são do Fish por API
        q.start()
        self.addCleanup(q.stop)

    def test_usa_o_fish_quando_ha_chave_e_guarda_frase_curta(self):
        chamadas = []
        with mock.patch.dict("os.environ", {"FISH_API_KEY": "x"}), \
             mock.patch.object(voz, "_fish", side_effect=lambda t, modelo: chamadas.append(t) or b"mp3"):
            primeiro = voz.gerar_mp3("Pois não, senhor?")
            segundo = voz.gerar_mp3("Pois não, senhor?")
        self.assertEqual(primeiro, segundo)
        self.assertEqual(chamadas, ["Pois não, senhor?"])   # a segunda veio do cache

    def test_cai_no_edge_se_o_fish_falhar(self):
        with mock.patch.dict("os.environ", {"FISH_API_KEY": "x"}), \
             mock.patch.object(voz, "_fish", side_effect=OSError("sem rede")), \
             mock.patch.object(voz, "_edge", return_value=b"mp3"):
            arquivo = voz.gerar_mp3("Bom dia, senhor.")
        self.assertTrue(arquivo and open(arquivo, "rb").read() == b"mp3")

    def test_sem_chave_nao_chama_o_fish(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("FISH_API_KEY", None)
            self.assertEqual([m[0] for m in voz.motores()], ["edge"])


class TestFishSite(unittest.TestCase):
    def test_divide_em_frases_sem_passar_do_limite(self):
        from nexo import fishsite
        texto = "Primeira frase. " * 40
        trechos = fishsite.dividir(texto, 100)
        self.assertGreater(len(trechos), 1)
        self.assertTrue(all(len(t) <= 100 for t in trechos))
        self.assertEqual(fishsite.dividir("Pois não, senhor?"), ["Pois não, senhor?"])
        self.assertEqual(fishsite.dividir("x" * 130 + " " + "y" * 130, 150), ["x" * 130, "y" * 130])

    def test_so_usa_o_site_depois_do_login(self):
        from nexo import fishsite
        with mock.patch.object(fishsite, "logado", return_value=False):
            self.assertNotIn("fish-site", [m[0] for m in voz.motores()])
        with mock.patch.object(fishsite, "logado", return_value=True), \
             mock.patch.object(fishsite, "uso_hoje", return_value=0), \
             mock.patch.dict("os.environ", {}) as env:
            env.pop("FISH_API_KEY", None)
            self.assertEqual(voz.motores()[0][0], "fish-site")
        with mock.patch.object(fishsite, "logado", return_value=True), \
             mock.patch.object(fishsite, "uso_hoje", return_value=fishsite.LIMITE_DIA):
            self.assertNotIn("fish-site", [m[0] for m in voz.motores()])

    def test_api_vem_antes_do_site(self):
        from nexo import fishsite
        with mock.patch.object(fishsite, "logado", return_value=True), \
             mock.patch.object(fishsite, "uso_hoje", return_value=0), \
             mock.patch.dict("os.environ", {"FISH_API_KEY": "x"}):
            self.assertEqual([m[0] for m in voz.motores()], ["fish", "fish-site", "edge"])

    def test_texto_longo_demais_cai_para_outro_motor(self):
        from nexo import fishsite
        with mock.patch.object(fishsite, "uso_hoje", return_value=0):
            with self.assertRaises(fishsite.ErroFish):
                fishsite.gerar("Uma frase razoável com bastante conteúdo. " * 60)


class TestFalaEmTrechos(unittest.TestCase):
    def test_primeiro_trecho_curto_e_resto_agrupado(self):
        fala = ("Bom dia, senhor. Hoje é terça-feira, 27 de outubro. Em Brasília faz 24 graus. "
                "Recomendo o projeto principal. Estou pronto.")
        trechos = voz.trechos_de_fala(fala)
        self.assertEqual(" ".join(trechos), fala)
        self.assertLessEqual(len(trechos[0]), 80)
        self.assertLess(len(trechos), 5)
        self.assertEqual(voz.trechos_de_fala("Pois não, senhor?"), ["Pois não, senhor?"])

    def test_toca_um_trecho_enquanto_gera_o_proximo(self):
        eventos = []
        def gerar(t):
            eventos.append(("gerou", t))
            return f"{t}.mp3"
        with mock.patch.object(voz, "gerar_mp3", side_effect=gerar), \
             mock.patch.object(voz, "_tocar_mp3", side_effect=lambda a: eventos.append(("tocou", a))):
            voz.falar("Primeira frase bem curta. Segunda frase que vem depois, com mais texto para passar do limite do primeiro trecho, "
                      "e ainda continua falando por bastante tempo. Terceira frase final.")
        tocadas = [e[1] for e in eventos if e[0] == "tocou"]
        self.assertEqual(tocadas, [e[1] + ".mp3" for e in eventos if e[0] == "gerou"])
