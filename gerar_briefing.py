#!/usr/bin/env python3
"""Gera o data.json do dashboard, o texto do briefing e o áudio do JARVIS.

Fontes (cada uma é opcional; sem a chave, aquela parte fica de fora):
  RevenueCat  REVENUECAT_API_KEY (secret key v2), REVENUECAT_PROJECT_ID
  Meta Ads    META_ACCESS_TOKEN, META_AD_ACCOUNT_ID (só os números, sem "act_")
  E-mails     --emails emails.json  (gerado pela rotina a partir do Gmail)
  Prioridades --prioridades prioridades.json

Uso:
  python gerar_briefing.py                 # gera data.json + briefing.txt + jarvis.mp3
  python gerar_briefing.py --sem-audio
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

PASTA = Path(__file__).resolve().parent


def revenuecat() -> dict:
    key, proj = os.environ.get("REVENUECAT_API_KEY"), os.environ.get("REVENUECAT_PROJECT_ID")
    if not (key and proj):
        return {}
    r = requests.get(
        f"https://api.revenuecat.com/v2/projects/{proj}/metrics/overview",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    r.raise_for_status()
    m = {x["id"]: x for x in r.json().get("metrics", [])}
    out = {}
    if "revenue" in m:
        out["receita"] = m["revenue"]["value"]
        out["receitaLabel"] = "Receita · 28 dias"
    if "mrr" in m:
        out["mrr"] = m["mrr"]["value"]
    if "active_subscriptions" in m:
        out["assinantes"] = m["active_subscriptions"]["value"]
    if "active_trials" in m:
        out["trials"] = m["active_trials"]["value"]
    return out


def meta_insights(token: str, conta: str, inicio: dt.date, fim: dt.date, nivel: str = "account") -> list:
    r = requests.get(
        f"https://graph.facebook.com/v21.0/act_{conta}/insights",
        params={
            "access_token": token,
            "level": nivel,
            "fields": "campaign_name,spend,purchase_roas",
            "time_range": json.dumps({"since": inicio.isoformat(), "until": fim.isoformat()}),
            "limit": 200,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("data", [])


def roas(linha: dict) -> float:
    v = linha.get("purchase_roas") or []
    return float(v[0]["value"]) if v else 0.0


def meta_ads() -> dict:
    token, conta = os.environ.get("META_ACCESS_TOKEN"), os.environ.get("META_AD_ACCOUNT_ID")
    if not (token and conta):
        return {}
    hoje = dt.date.today()
    atual = meta_insights(token, conta, hoje - dt.timedelta(days=7), hoje - dt.timedelta(days=1))
    anterior = meta_insights(token, conta, hoje - dt.timedelta(days=14), hoje - dt.timedelta(days=8))
    campanhas = meta_insights(token, conta, hoje - dt.timedelta(days=7), hoje - dt.timedelta(days=1), "campaign")
    a = atual[0] if atual else {}
    p = anterior[0] if anterior else {}
    gasto, gasto_ant = float(a.get("spend", 0)), float(p.get("spend", 0))
    out = {
        "ads": round(gasto),
        "adsVar": round((gasto / gasto_ant - 1) * 100, 1) if gasto_ant else 0,
        "roas": round(roas(a), 2),
        "roasVar": round(roas(a) - roas(p), 2),
    }
    ativas = [c for c in campanhas if float(c.get("spend", 0)) > 0]
    if ativas:
        ordenadas = sorted(ativas, key=roas)
        out["piorCampanha"] = [ordenadas[0]["campaign_name"], round(roas(ordenadas[0]), 2)]
        out["melhorCampanha"] = [ordenadas[-1]["campaign_name"], round(roas(ordenadas[-1]), 2)]
    return out


def ler_json(caminho) -> list:
    if caminho and Path(caminho).exists():
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    return []


def saudacao() -> str:
    h = dt.datetime.now().hour
    return "Bom dia, senhor." if h < 12 else "Boa tarde, senhor." if h < 18 else "Boa noite, senhor."


def brl(n: float) -> str:
    return "R$ " + f"{round(n):,}".replace(",", ".")


def texto_briefing(data: dict) -> str:
    """Monta o texto do briefing no tom do persona.md, a partir dos dados coletados."""
    blocos = [f"{saudacao()} Seu resumo está pronto."]

    if "receita" in data:
        var = data.get("receitaVar")
        variacao = f", {'uma alta' if (var or 0) >= 0 else 'uma queda'} de {abs(var):.1f} por cento em relação à semana anterior" if isinstance(var, (int, float)) else ""
        assinantes = f" Temos {data['assinantes']:,}".replace(",", ".") + " assinantes ativos." if "assinantes" in data else ""
        blocos.append(f"Receita do período foi de {brl(data['receita'])}{variacao}.{assinantes}")
    elif "mrr" in data:
        blocos.append(f"O MRR atual é de {brl(data['mrr'])}.")

    if "ads" in data:
        roas = f", com ROAS de {data['roas']:.1f}" if "roas" in data else ""
        linha = f"Em anúncios, foram investidos {brl(data['ads'])}{roas}."
        if "melhorCampanha" in data and "piorCampanha" in data:
            linha += f" A campanha '{data['melhorCampanha'][0]}' teve o melhor desempenho; '{data['piorCampanha'][0]}' foi a pior, com ROAS de {data['piorCampanha'][1]:.1f}."
        blocos.append(linha)

    emails = data.get("emails") or []
    if emails:
        pendentes = [e for e in emails if len(e) > 2 and e[2] == "bad"]
        respondidos = len(emails) - len(pendentes)
        linha = f"Respondi {respondidos} e-mail{'s' if respondidos != 1 else ''} de suporte."
        linha += f" {len(pendentes)} {'casos exigem' if len(pendentes) != 1 else 'caso exige'} sua atenção." if pendentes else " Nenhum caso pendente."
        blocos.append(linha)

    agendados = (data.get("youtube") or {}).get("agendadosHoje")
    if agendados:
        blocos.append(f"Há {agendados} vídeo{'s' if agendados != 1 else ''} agendado{'s' if agendados != 1 else ''} para hoje.")

    prioridades = data.get("prioridades") or []
    if prioridades:
        blocos.append(f"Prioridade número um: {prioridades[0][0]}.")

    if data.get("falhas"):
        blocos.append(f"Não consegui acessar: {', '.join(data['falhas'])}. O restante do briefing segue sem essas fontes.")

    blocos.append("Isso é tudo por enquanto, senhor. Estarei à disposição.")
    return "\n\n".join(blocos) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emails", default=PASTA / "emails.json")
    ap.add_argument("--prioridades", default=PASTA / "prioridades.json")
    ap.add_argument("--sem-audio", action="store_true")
    a = ap.parse_args()

    data = {"demo": False, "geradoEm": dt.datetime.now().isoformat(timespec="minutes")}
    anterior = PASTA / "data.json"
    if anterior.exists():  # campos que outra rotina grava direto (YouTube via Metricool) sobrevivem a uma nova rodada
        antigo = json.loads(anterior.read_text(encoding="utf-8"))
        data.update({k: antigo[k] for k in ("youtube",) if k in antigo})
    for nome, fonte in (("RevenueCat", revenuecat), ("Meta Ads", meta_ads)):
        try:
            data.update(fonte())
        except Exception as e:  # uma fonte fora do ar não derruba o briefing
            print(f"[aviso] {nome}: {e}", file=sys.stderr)
            data.setdefault("falhas", []).append(nome)
    data["emails"] = ler_json(a.emails)
    data["prioridades"] = ler_json(a.prioridades)

    briefing = texto_briefing(data)
    data["briefing"] = briefing
    (PASTA / "briefing.txt").write_text(briefing, encoding="utf-8")
    (PASTA / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    if not a.sem_audio:
        subprocess.run([sys.executable, str(PASTA / "jarvis_voz.py"), "--arquivo", str(PASTA / "briefing.txt"),
                        "--saida", str(PASTA / "jarvis.mp3"), "--nao-tocar"], check=False)


if __name__ == "__main__":
    main()
