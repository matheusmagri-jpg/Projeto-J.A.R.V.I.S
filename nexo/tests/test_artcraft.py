"""Roda os programas do ArtCraft de verdade (pulado se não estiverem instalados)."""
import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from nexo import config, ferramentas
from nexo.ferramentas import artcraft

INSTALADOS = all(p.exists() for p in artcraft.CLIS.values())
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
       '<circle cx="32" cy="32" r="30" fill="#4b2bd6"/></svg>')


@unittest.skipUnless(INSTALADOS, "ArtCraft não instalado")
class TestArtCraft(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.patch = mock.patch.object(config, "ARQUIVOS", cls.tmp)
        cls.patch.start()
        (cls.tmp / "logo.svg").write_text(SVG, encoding="utf-8")
        (cls.tmp / "vendas.csv").write_text("mes,valor\njan,100\nfev,250\n", encoding="utf-8")
        with wave.open(str(cls.tmp / "tom.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100)
            w.writeframes(b"".join(struct.pack("<h", int(2000 * math.sin(2 * math.pi * 440 * i / 44100)))
                                   for i in range(22050)))

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_vetor_para_png_e_imagem_para_webp(self):
        self.assertIn("logo.png", artcraft.vetor_exportar("logo.svg", "png", 4))
        self.assertIn("256x256", artcraft.imagem_info("logo.png"))
        r = artcraft.imagem_converter("logo.png", "webp", largura=128)
        self.assertIn("logo-128.webp: 128x128", r)
        # Não sobrescreve: a segunda conversão ganha sufixo.
        self.assertIn("logo-128-1.webp", artcraft.imagem_converter("logo.png", "webp", largura=128))

    def test_documento_criar_pdf_e_ler(self):
        r = artcraft.documento_criar("Proposta NEXO", "## Escopo\n\nAssistente com **cérebro**.", "docx")
        self.assertIn("Proposta NEXO.docx", r)
        self.assertIn("Assistente com cérebro", artcraft.documento_ler("Proposta NEXO.docx"))
        self.assertIn(".pdf", artcraft.documento_converter("Proposta NEXO.docx", "pdf"))

    def test_documento_sem_links_do_obsidian(self):
        artcraft.documento_criar("Links", "Fala do [[NEXO]] e do [[USUARIO|Matheus]].", "md")
        texto = (self.tmp / "Links.md").read_text(encoding="utf-8")
        self.assertIn("Fala do NEXO e do Matheus.", texto)

    def test_planilha(self):
        self.assertIn("vendas.xlsx", artcraft.planilha_converter("vendas.csv", "xlsx"))
        self.assertIn("fev,250", artcraft.planilha_ver("vendas.xlsx"))
        self.assertTrue(artcraft.planilha_formula("SUM(B2:B3)", "vendas.xlsx").endswith("350"))

    def test_audio_normalizar(self):
        self.assertIn("tom-normalizado.flac", artcraft.audio_converter("tom.wav", "flac", normalizar=True))

    def test_recusa_arquivo_fora_da_pasta(self):
        with self.assertRaises(artcraft.ErroArtCraft):
            artcraft.imagem_info("../../segredo.png")

    def test_ferramentas_carregadas(self):
        todas = ferramentas.carregar()
        for nome in ("imagem_converter", "documento_criar", "planilha_formula", "audio_converter"):
            self.assertIn(nome, todas)
