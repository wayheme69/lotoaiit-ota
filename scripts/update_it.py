#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_it.py — met à jour it_recent.json (SuperEnalotto + EuroJackpot) pour LOTO AI IT.

Chaînes de sources (leçons ES 28/07 : succès = données VALIDES uniquement, échec
BRUYANT, no-op réel quand rien ne change, fusion avec l'existant pour résilience) :
  • SuperEnalotto : superenalotto.com/en/results (HTML régulier, direct) ;
    fallback r.jina.ai en X-Return-Format: html (⚠️ jamais "text" : les numéros
    sortent concaténés) ; dernier recours Lottoland (1 tirage + next).
    La même page fournit le PROCHAIN tirage (nextDrawDate inline) + jackpot
    (topBarJackpotValueNumber).
  • EuroJackpot : asderfvfv/eurojackpot-data (CSV raw GitHub, prod LOTTO AI DE,
    MAJ soir de tirage) ; next jackpot via Lottoland, fallback euro-jackpot.net.

Sorties : it_recent.json
  {"updated", "superenalotto": {"draws":[{date,concorso,numbers[6],jolly}], "next":{date,jackpot_eur}},
              "eurojackpot":  {"draws":[{date,numbers[5],euros[2]}],        "next":{date,jackpot_eur}}}
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}

SE_RESULTS = "https://www.superenalotto.com/en/results"
EJ_CSV = "https://raw.githubusercontent.com/asderfvfv/eurojackpot-data/main/data/eurojackpot_draws.csv"
LOTTOLAND_SE = "https://media.lottoland.com/api/drawings/superEnalotto"
LOTTOLAND_EJ = "https://media.lottoland.com/api/drawings/euroJackpot"
EJNET = "https://www.euro-jackpot.net/results"

# Borne de dates : rien avant 1997 (SE) / 2012 (EJ), rien apres demain — une typo
# d'annee amont ("2062-…") polluait sinon it_recent.json DURABLEMENT (revue 28/07).
def max_date():
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def curl(url, extra=None, timeout=60):
    cmd = ["curl", "-sL", "--max-time", str(timeout)] + (extra or []) + [url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 20)
    return r.stdout if r.returncode == 0 else ""


# ----------------------------- SuperEnalotto -----------------------------

SE_BLOCK = re.compile(r'Draw of (\d{1,2}) (\w+) (\d{4})\s*-\s*draw n\. (\d+)(.*?)(?=Draw of \d|\Z)', re.S)
SE_NUM = re.compile(r'<div class="boxDrawNumber">(\d{1,2})</div>')
SE_JOLLY = re.compile(r'boxDrawNumberRed">(\d{1,2})<div>Jolly')


def parse_se_page(html):
    draws = []
    for dd, mon, yy, conc, body in SE_BLOCK.findall(html):
        if mon not in MONTHS:
            continue
        d = f"{int(yy):04d}-{MONTHS[mon]:02d}-{int(dd):02d}"
        if not ("1997-01-01" <= d <= max_date()):
            raise SystemExit(f"SE: date hors plage {d}")
        nums = sorted(int(x) for x in SE_NUM.findall(body))
        jm = SE_JOLLY.search(body)
        if len(nums) != 6 or not jm:
            raise SystemExit(f"SE: bloc illisible {d} ({nums})")
        jolly = int(jm.group(1))
        if len(set(nums)) != 6 or not all(1 <= n <= 90 for n in nums) \
                or not (1 <= jolly <= 90) or jolly in nums:
            raise SystemExit(f"SE: valeurs invalides {d}: {nums} J{jolly}")
        draws.append({"date": d, "concorso": int(conc), "numbers": nums, "jolly": jolly})
    return draws


def fetch_se():
    """-> (draws, next) ; next = {date, jackpot_eur} depuis la même page."""
    for attempt, fetch in enumerate([
        lambda: curl(SE_RESULTS),
        lambda: curl(f"https://r.jina.ai/{SE_RESULTS}", ["-H", "X-Return-Format: html"], 90),
    ]):
        html = fetch()
        if "boxDrawNumber" in html:
            draws = parse_se_page(html)
            if draws:
                nxt = None
                md = re.search(r'nextDrawDate = new Date\("(\d{4}-\d{2}-\d{2})', html)
                mj = re.search(r'topBarJackpotValueNumber">([\d.]+)<', html)
                if md:
                    nxt = {"date": md.group(1)}
                    if mj:
                        try:
                            nxt["jackpot_eur"] = int(mj.group(1).replace(".", ""))
                        except ValueError:
                            pass
                return draws, nxt
        print(f"  SE essai {attempt + 1} KO", file=sys.stderr)
        time.sleep(8)
    # Dernier recours : Lottoland (1 tirage + next) — mieux que rien, fusion comblera.
    body = curl(LOTTOLAND_SE)
    j = json.loads(body) if body.startswith("{") else {}
    last, nxt_raw = j.get("last") or {}, j.get("next") or {}
    nums = sorted(int(x) for x in (last.get("numbers") or []))
    jolly_l = last.get("jolly")
    jolly = int(jolly_l[0]) if isinstance(jolly_l, list) and jolly_l else None
    dd = last.get("date") or {}
    if len(nums) == 6 and jolly and all(1 <= n <= 90 for n in nums) and jolly not in nums \
            and {"year", "month", "day"} <= set(dd):
        d = f"{dd['year']:04d}-{dd['month']:02d}-{dd['day']:02d}"
        draws = [{"date": d, "concorso": int(last.get("nr") or 0), "numbers": nums, "jolly": jolly}]
        nxt = None
        nd = nxt_raw.get("date") or {}
        if {"year", "month", "day"} <= set(nd):
            nxt = {"date": f"{nd['year']:04d}-{nd['month']:02d}-{nd['day']:02d}"}
            try:
                nxt["jackpot_eur"] = int(float(nxt_raw.get("jackpot")) * 1_000_000)
            except (TypeError, ValueError):
                pass
        return draws, nxt
    raise SystemExit("SE: les 3 sources ont échoué")


# ----------------------------- EuroJackpot -----------------------------

def fetch_ej():
    body = curl(EJ_CSV)
    lines = body.strip().splitlines()
    if len(lines) < 100 or not lines[0].startswith("Date,"):
        raise SystemExit("EJ: CSV asderfvfv illisible")
    draws = []
    for line in lines[-14:]:
        c = line.split(",")
        if len(c) != 8 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", c[0])                 or not ("2012-01-01" <= c[0] <= max_date()):
            continue
        nums = sorted(int(x) for x in c[1:6])
        euros = sorted(int(x) for x in c[6:8])
        if len(set(nums)) != 5 or not all(1 <= n <= 50 for n in nums) \
                or len(set(euros)) != 2 or not all(1 <= e <= 12 for e in euros):
            raise SystemExit(f"EJ: valeurs invalides {c}")
        draws.append({"date": c[0], "numbers": nums, "euros": euros})
    if not draws:
        raise SystemExit("EJ: aucun tirage parsé")
    draws = sorted(draws, key=lambda x: x["date"], reverse=True)
    # Sonde de fraicheur (modele « anti-retard Caixa » BR, revue 28/07) : mar/ven
    # -> ecart normal max 4 j + marge publication. Au-dela : Action ROUGE, alerte,
    # au lieu d'un flux verrouille sur un CSV tiers gele (mode de panne Magayo).
    age = (datetime.now(timezone.utc).date()
           - datetime.strptime(draws[0]["date"], "%Y-%m-%d").date()).days
    if age > 6:
        raise SystemExit(f"EJ: source asderfvfv périmée — dernier tirage {draws[0]['date']} ({age} j)")
    return draws


def fetch_ej_next():
    body = curl(LOTTOLAND_EJ)
    if body.startswith("{"):
        j = json.loads(body)
        nd = (j.get("next") or {}).get("date") or {}
        if {"year", "month", "day"} <= set(nd):
            out = {"date": f"{nd['year']:04d}-{nd['month']:02d}-{nd['day']:02d}"}
            try:
                out["jackpot_eur"] = int(float(j["next"]["jackpot"]) * 1_000_000)
            except (KeyError, TypeError, ValueError):
                pass
            return out
    # Fallback : euro-jackpot.net ("Next Jackpot €10 Million" + date dans la page)
    html = curl(EJNET)
    mj = re.search(r"Next\s+Jackpot.*?€(\d+(?:\.\d+)?)\s*Million", html, re.S | re.I)
    if mj:
        return {"jackpot_eur": int(float(mj.group(1)) * 1_000_000)}
    raise SystemExit("EJ next: Lottoland ET euro-jackpot.net ont échoué")


# ----------------------------- Assemblage -----------------------------

def merge(old_draws, fresh, key="date", cap=12):
    by = {}
    # L'existant est aussi borne -> un JSON deja pollue par une date fantome
    # s'auto-guerit au run suivant (revue 28/07).
    for r in old_draws or []:
        if "1997-01-01" <= r.get(key, "") <= max_date():
            by[r[key]] = r
    for r in fresh:
        by[r[key]] = r
    return sorted(by.values(), key=lambda x: x[key], reverse=True)[:cap]


try:
    with open("it_recent.json") as f:
        old = json.load(f)
except (OSError, ValueError):
    old = {}

se_draws, se_next = fetch_se()
ej_draws = fetch_ej()
ej_next = fetch_ej_next()

content = {
    "superenalotto": {
        "draws": merge((old.get("superenalotto") or {}).get("draws"), se_draws),
        "next": se_next or (old.get("superenalotto") or {}).get("next"),
    },
    "eurojackpot": {
        "draws": merge((old.get("eurojackpot") or {}).get("draws"), ej_draws),
        "next": ej_next or (old.get("eurojackpot") or {}).get("next"),
    },
}

old_cmp = dict(old)
old_cmp.pop("updated", None)
if old_cmp == content:
    print("Aucune nouvelle donnée — it_recent.json inchangé.", file=sys.stderr)
    raise SystemExit(0)

payload = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **content}
with open("it_recent.json", "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=1)
se0, ej0 = content["superenalotto"]["draws"][0], content["eurojackpot"]["draws"][0]
print(f"OK: SE {se0['date']} {se0['numbers']} J{se0['jolly']} next={content['superenalotto']['next']}; "
      f"EJ {ej0['date']} {ej0['numbers']}+{ej0['euros']} next={content['eurojackpot']['next']}", file=sys.stderr)
