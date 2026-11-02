import datetime as dt
import email
import unittest
from unittest import mock

from nexo import cerebro, config
from nexo.ferramentas import agenda_email

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//teste//pt
BEGIN:VEVENT
UID:1
DTSTART;TZID=America/Sao_Paulo:20261102T140000
DTEND;TZID=America/Sao_Paulo:20261102T150000
SUMMARY:Reuni\xc3\xa3o com a Ana
LOCATION:Escrit\xc3\xb3rio
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART:20261026T113000Z
DTEND:20261026T120000Z
RRULE:FREQ=WEEKLY;BYDAY=MO
SUMMARY:Academia
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART;VALUE=DATE:20261103
DTEND;VALUE=DATE:20261104
SUMMARY:Anivers\xc3\xa1rio do Pedro
END:VEVENT
END:VCALENDAR
"""


class BaseAgenda(unittest.TestCase):
    def setUp(self):
        agenda_email._cache_ics.clear()
        for alvo, valor in ((config, ("AGENDA_ICS", ["https://exemplo/secreto.ics"])),):
            p = mock.patch.object(alvo, *valor)
            p.start()
            self.addCleanup(p.stop)
        b = mock.patch.object(agenda_email, "_baixar_ics", return_value=ICS)
        self.baixar = b.start()
        self.addCleanup(b.stop)
        a = mock.patch.object(cerebro, "agora", return_value=dt.datetime(2026, 11, 2, 8, 0))
        a.start()
        self.addCleanup(a.stop)


class TestAgenda(BaseAgenda):
    def test_compromissos_de_hoje_com_recorrencia_e_fuso(self):
        linhas = agenda_email.compromissos(1)
        self.assertEqual(len(linhas), 2)
        self.assertTrue(linhas[0].endswith(": Academia"))       # segunda-feira, repete toda semana
        self.assertIn("14:00: Reunião com a Ana (Escritório)", linhas[1])

    def test_proximos_dias_mostram_data_e_dia_inteiro(self):
        texto = agenda_email.ver_agenda(2)
        self.assertIn("03/11 dia inteiro: Aniversário do Pedro", texto)

    def test_sem_agenda_explica_como_configurar(self):
        with mock.patch.object(config, "AGENDA_ICS", []):
            self.assertEqual(agenda_email.compromissos(), [])
            self.assertIn("NEXO_AGENDA_ICS", agenda_email.ver_agenda())


class TestEmail(unittest.TestCase):
    def test_sem_configuracao_nao_conecta(self):
        with mock.patch.object(config, "EMAIL_USUARIO", ""), mock.patch.object(agenda_email, "_conectar") as c:
            self.assertEqual(agenda_email.resumo_emails(), {})
            self.assertIn("NEXO_EMAIL_SENHA_APP", agenda_email.ver_emails())
            c.assert_not_called()

    def test_id_invalido_nao_vai_ao_servidor(self):
        with mock.patch.object(config, "EMAIL_USUARIO", "a@b.c"), mock.patch.object(config, "EMAIL_SENHA", "x"), \
             mock.patch.object(agenda_email, "_conectar") as c:
            self.assertIn("só números", agenda_email.ler_email("1 OR ALL"))
            c.assert_not_called()

    def test_texto_do_email_prefere_texto_puro_e_limpa_html(self):
        msg = email.message_from_bytes(
            "Content-Type: text/html; charset=utf-8\n\n<style>x{}</style><p>Olá <b>senhor</b></p>".encode())
        self.assertEqual(" ".join(agenda_email._texto_do_email(msg).split()), "Olá senhor")

    def test_nao_lidos_usa_peek_e_decodifica_cabecalhos(self):
        cab = (b"From: =?utf-8?q?Jo=C3=A3o?= <joao@x.com>\r\nSubject: =?utf-8?q?Or=C3=A7amento?=\r\n"
               b"Date: Mon, 02 Nov 2026 10:00:00 -0300\r\n\r\n")
        caixa = mock.Mock()
        caixa.uid.side_effect = lambda cmd, *a: (("OK", [b"7 8"]) if cmd == "search"
                                                  else ("OK", [(b"x", cab), b")"]))
        with mock.patch.object(agenda_email, "_conectar", return_value=caixa):
            total, recentes = agenda_email.nao_lidos(5)
        self.assertEqual(total, 2)
        self.assertEqual(recentes[0], {"id": "8", "de": "João", "assunto": "Orçamento", "data": "02/11 10:00"})
        pedidos = [c.args[2] for c in caixa.uid.call_args_list if c.args[0] == "fetch"]
        self.assertTrue(all("PEEK" in p for p in pedidos))
        caixa.logout.assert_called_once()


if __name__ == "__main__":
    unittest.main()
