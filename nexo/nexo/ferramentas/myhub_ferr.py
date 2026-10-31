"""Ferramenta: consultar as IAs do MyHub.IA (assinatura do usuário) para aprender ou ter segunda opinião."""
from .. import myhub
from . import Ferramenta

MODELOS = "MyHUB Nitro, GPT-6 Luna, Claude Opus 5.5, Claude Sonnet 5.5, Gemini 3.8 Flash, DeepSeek V4 Pro, Kimi K2.7 Code, Alibaba Qwen 3.7 Plus"

FERRAMENTAS = [
    Ferramenta(
        "consultar_myhub",
        "Pergunta a outra IA pela assinatura MyHub.IA do usuário (vários modelos). Use quando precisar aprender "
        "algo que você não sabe bem, pesquisar um assunto a fundo ou ter uma segunda opinião; depois guarde o que "
        "for útil no cérebro com criar_nota (tipo ideia ou fonte). Leva de 15 a 60 segundos e tem limite diário. "
        "Nunca envie senhas, chaves ou dados pessoais sensíveis. Modelos: " + MODELOS + " (vazio = o padrão do site).",
        myhub.consultar,
        {"pergunta": {"type": "string", "description": "Pergunta completa e autoexplicativa"},
         "modelo": {"type": "string", "description": "Nome do modelo do MyHub (opcional)"}},
        ["pergunta"]),
]
