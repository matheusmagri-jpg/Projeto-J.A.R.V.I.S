import time
import unittest
from unittest import mock

from nexo import cerebro, config, conversa, ia, telegram


def mensagem(texto="oi", chat=42, idade=0, **extra):
    return {"chat": {"id": chat}, "date": int(time.time()) - idade, "text": texto, **extra}


class BaseTelegram(unittest.TestCase):
    def setUp(self):
        for nome, valor in (("TELEGRAM_TOKEN", "123:abc"), ("TELEGRAM_CHAT", "42")):
            p = mock.patch.object(config, nome, valor)
            p.start()
            self.addCleanup(p.stop)
        e = mock.patch.object(telegram, "enviar", return_value=True)
        self.enviar = e.start()
        self.addCleanup(e.stop)
        c = mock.patch.object(telegram, "_chamar_sem_falha")
        c.start()
        self.addCleanup(c.stop)
        d = mock.patch.object(cerebro, "registrar_diario")
        self.diario = d.start()
        self.addCleanup(d.stop)
        self.bot = telegram.Bot()


class TestRecebimento(BaseTelegram):
    def test_so_o_chat_configurado_entra_na_fila(self):
        self.bot._receber(mensagem(chat=999))
        self.assertTrue(self.bot.fila.empty())
        self.enviar.assert_not_called()          # estranho nem fica sabendo que o bot existe
        self.bot._receber(mensagem(chat=42))
        self.assertEqual(self.bot.fila.get_nowait()["text"], "oi")

    def test_mensagem_antiga_nao_e_executada(self):
        self.bot._receber(mensagem(idade=3600))
        self.assertTrue(self.bot.fila.empty())

    def test_sem_chat_configurado_so_informa_o_numero(self):
        with mock.patch.object(config, "TELEGRAM_CHAT", ""):
            self.bot._receber(mensagem(chat=777))
        self.assertTrue(self.bot.fila.empty())
        self.assertIn("NEXO_TELEGRAM_CHAT=777", self.enviar.call_args.args[0])


class TestResposta(BaseTelegram):
    def test_atende_pela_conversa_e_registra_no_diario(self):
        falsa = mock.Mock()
        falsa.enviar.return_value = conversa.Turno("Às ordens.", "gemini")
        with mock.patch.object(conversa, "Conversa", return_value=falsa), \
             mock.patch.object(ia, "privado_ativo", return_value=False):
            self.bot._atender(mensagem("que horas são?"))
        falsa.enviar.assert_called_once_with("que horas são?")
        self.enviar.assert_called_with("Às ordens.")
        self.assertIn("Pelo Telegram", self.diario.call_args.args[0])

    def test_modo_privado_nao_escreve_no_diario(self):
        falsa = mock.Mock()
        falsa.enviar.return_value = conversa.Turno("ok", "ollama")
        with mock.patch.object(conversa, "Conversa", return_value=falsa), \
             mock.patch.object(ia, "privado_ativo", return_value=True):
            self.bot._atender(mensagem("segredo"))
        self.diario.assert_not_called()

    def test_audio_e_transcrito_e_responde_tambem_falando(self):
        falsa = mock.Mock()
        falsa.enviar.return_value = conversa.Turno("Feito.", "gemini")
        msg = mensagem(texto=None, voice={"file_id": "f1", "mime_type": "audio/ogg"})
        with mock.patch.object(conversa, "Conversa", return_value=falsa), \
             mock.patch.object(telegram, "_baixar_arquivo", return_value=b"ogg"), \
             mock.patch("nexo.voz.transcrever", return_value="toca música") as transcrever, \
             mock.patch("nexo.voz.gerar_mp3", return_value="resposta.mp3"), \
             mock.patch.object(telegram, "_enviar_audio") as audio, \
             mock.patch.object(ia, "privado_ativo", return_value=False):
            self.bot._atender(msg)
        transcrever.assert_called_once_with(b"ogg", "audio/ogg")
        falsa.enviar.assert_called_once_with("toca música")
        audio.assert_called_once_with("resposta.mp3")

    def test_confirmacao_espera_o_sim_pelo_proprio_chat(self):
        self.bot.fila.put(mensagem("sim"))
        self.assertTrue(self.bot._confirmar("Posso desligar o PC?"))
        self.bot.fila.put(mensagem("não"))
        self.assertFalse(self.bot._confirmar("Posso desligar o PC?"))
        self.assertIn("sim ou não", self.enviar.call_args_list[0].args[0])


class TestAvisos(unittest.TestCase):
    def test_enviar_divide_texto_longo(self):
        with mock.patch.object(config, "TELEGRAM_TOKEN", "t"), mock.patch.object(config, "TELEGRAM_CHAT", "42"), \
             mock.patch.object(telegram, "_chamar") as chamar:
            self.assertTrue(telegram.enviar("a" * 9000))
        self.assertEqual(chamar.call_count, 3)

    def test_sem_token_nao_sobe_bot(self):
        with mock.patch.object(config, "TELEGRAM_TOKEN", ""):
            self.assertIsNone(telegram.iniciar())
            self.assertFalse(telegram.enviar("oi"))


if __name__ == "__main__":
    unittest.main()
