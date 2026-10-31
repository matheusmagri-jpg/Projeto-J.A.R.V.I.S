"""Ferramentas de proatividade: lembretes, hábitos e resumo do dia."""
import json

from .. import proativo
from . import Ferramenta

FERRAMENTAS = [
    Ferramenta("lembrar",
               "Agenda um lembrete: daqui a X minutos OU num horário (ex.: 14:30). Quando chegar a hora, "
               "aviso com notificação do Windows e, no painel, em voz alta.",
               proativo.lembrar,
               {"texto": {"type": "string", "description": "Do que lembrar"},
                "minutos": {"type": "integer", "description": "Daqui a quantos minutos (0 se usar horário)"},
                "horario": {"type": "string", "description": "Hora do dia, ex.: 14:30 ou 9h (vazio se usar minutos)"}},
               ["texto"]),
    Ferramenta("listar_lembretes", "Lista os lembretes agendados.", proativo.listar_lembretes),
    Ferramenta("marcar_habito", "Marca um pilar dos hábitos de hoje como feito (ex.: saúde, conteúdo).",
               proativo.marcar_habito, {"pilar": {"type": "string"}}, ["pilar"]),
    Ferramenta("resumo_do_dia",
               "Dados do dia para um bom dia/resumo: data, clima, lembretes, pendências de ontem, hábitos que "
               "faltam, itens na caixa de entrada e prioridades do JARVIS. Use quando o usuário pedir 'bom dia', "
               "'resumo do dia' ou 'o que tenho hoje', e escreva o resumo a partir destes dados.",
               lambda: json.dumps(proativo.contexto_do_dia(), ensure_ascii=False)),
]
