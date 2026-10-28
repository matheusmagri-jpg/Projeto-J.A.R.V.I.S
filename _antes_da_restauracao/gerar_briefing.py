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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emails", default=PASTA / "emails.json")
    ap.add_argument("--prioridades", default=PASTA / "prioridades.json")
    ap.add_argument("--sem-audio", action="store_true")
    a = ap.parse_args()

    data = {"demo": False, "geradoEm": dt.datetime.now().isoformat(timespec="minutes")}
    anterior = PASTA / "data.json"
    if anterior.exists():  # campos que a rotina grava direto (YouTube, texto do briefing) sobrevivem a uma nova rodada
        antigo = json.loads(anterior.read_text(encoding="utf-8"))
        data.update({k: antigo[k] for k in ("youtube", "briefing") if k in antigo})
    for nome, fonte in (("RevenueCat", revenuecat), ("Meta Ads", meta_ads)):
        try:
            data.update(fonte())
        except Exception as e:  # uma fonte fora do ar não derruba o briefing
            print(f"[aviso] {nome}: {e}", file=sys.stderr)
            data.setdefault("falhas", []).append(nome)
    data["emails"] = ler_json(a.emails)
    data["prioridades"] = ler_json(a.prioridades)

    (PASTA / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    texto = PASTA / "briefing.txt"
    if not a.sem_audio and texto.exists():
        subprocess.run([sys.executable, str(PASTA / "jarvis_voz.py"), "--arquivo", str(texto),
                        "--saida", str(PASTA / "jarvis.mp3"), "--nao-tocar"], check=False)


if __name__ == "__main__":
    main()
