#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
it_results.py — flux de la v4 de LOTO AI IT : it_results.json (08/10/2026)

  superenalotto : 30 derniers concorsi (6 numeri, Jolly, SuperStar) + vraie quota par
                  vincitore pour chaque catégorie (« 6 », « 5+1 », « 5 », « 4 », « 3 », « 2 »)
                  et nombre de vincitori.
  eurojackpot   : 30 derniers tirages (5 numeri + 2 euronumeri) + vraie quota en Italie
                  pour les 12 catégories jouables en Italie, et vincitori italiens.

Sources :
  • SuperEnalotto : superenalotto.com — archive annuelle (numéros, Jolly, SuperStar) +
    page de chaque concorso (quote et vincitori). Les numéros des deux pages doivent concorder.
    ⚠️ Lottoland publie des quote FAUSSES (montants types) : ne jamais l'utiliser pour les gains.
  • Eurojackpot : euro-jackpot.net/results/JJ-MM-AAAA (numéros + tableau « Italy »).
Accès direct, sinon r.jina.ai (HTML). Fusion avec le fichier déjà publié : une quota qui
arrive plus tard est complétée au run suivant ; on ne retélécharge pas un tirage déjà complet.
Échec bruyant si le flux est périmé (> 6 j). Le flux de la v3 (it_recent.json) n'est PAS touché.
"""
import json, os, re, subprocess, sys, time
from datetime import date, datetime, timedelta, timezone

FEED = "it_results.json"
KEEP = 30
MAX_STALE_DAYS = 6
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}
SE_KEYS = {"6 numbers": "6", "5 numbers + Jolly": "5+1", "5 numbers": "5",
           "4 numbers": "4", "3 numbers": "3", "2 numbers": "2"}
EJ_KEYS = {"Match 5 and 2 Euro Numbers": "5+2", "Match 5 and 1 Euro Number": "5+1", "Match 5": "5+0",
           "Match 4 and 2 Euro Numbers": "4+2", "Match 4 and 1 Euro Number": "4+1",
           "Match 3 and 2 Euro Numbers": "3+2", "Match 4": "4+0", "Match 2 and 2 Euro Numbers": "2+2",
           "Match 3 and 1 Euro Number": "3+1", "Match 3": "3+0", "Match 1 and 2 Euro Numbers": "1+2",
           "Match 2 and 1 Euro Number": "2+1"}


def curl(url, timeout=60, extra=None):
    r = subprocess.run(["curl", "-sL", "--max-time", str(timeout), "-A", UA] + (extra or []) + [url],
                       capture_output=True, text=True, timeout=timeout + 30)
    return r.stdout if r.returncode == 0 else ""


def get(url, marker, tries=3):
    """HTML de `url` contenant `marker` : direct d'abord, puis r.jina.ai."""
    for i in range(tries):
        html = curl(url)
        if marker in html:
            return html
        html = curl(f"https://r.jina.ai/{url}", 120, ["-H", "X-Return-Format: html"])
        if marker in html:
            return html
        print(f"  essai {i + 1} KO : {url}", file=sys.stderr)
        time.sleep(8 * (i + 1))
    return None


def text(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t).replace("&euro;", "€").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t)


def eur(s):
    """« 34.464,15 € » (it) ou « €883,793.90 » (en) → float ; « - » → None"""
    s = s.strip().replace("€", "").strip()
    if not re.search(r"\d", s):
        return None
    if re.fullmatch(r"[\d.]+,\d{2}", s):          # format italien
        s = s.replace(".", "").replace(",", ".")
    else:                                           # format anglais
        s = s.replace(",", "")
    v = float(s)
    return v if v > 0 else None


def count(s):
    return int(s.replace(",", "").replace(".", ""))


# ----------------------------- SuperEnalotto -----------------------------

SE_BOX = re.compile(r'boxarchiveDate">(\d{1,2}) (\w+) (\d{4})</div>(.*?)</div>\s*</div>\s*</div>', re.S)


def se_archive(year):
    html = get(f"https://www.superenalotto.com/en/archive/draw-{year}", "boxarchiveDate")
    if not html:
        raise SystemExit(f"SE: archive {year} illisible")
    out = []
    for dd, mon, yy, body in SE_BOX.findall(html):
        nums = [int(x) for x in re.findall(r'class="boxArchiveNumber">(\d{1,2})</div>', body)]
        j = re.search(r'boxArchiveNumberRed">(\d{1,2})<div>Jolly', body)
        s = re.search(r'boxArchiveNumberstar">(\d{1,2})<div>Superstar', body)
        d = f"{int(yy):04d}-{MONTHS[mon]:02d}-{int(dd):02d}"
        if len(nums) != 6 or not j:
            raise SystemExit(f"SE {d}: bloc d'archive illisible {nums}")
        nums, jolly = sorted(nums), int(j.group(1))
        if len(set(nums)) != 6 or not all(1 <= n <= 90 for n in nums) or not 1 <= jolly <= 90 or jolly in nums:
            raise SystemExit(f"SE {d}: valeurs invalides {nums} J{jolly}")
        out.append({"date": d, "numbers": nums, "jolly": jolly,
                    "superstar": int(s.group(1)) if s else None})
    return out


def se_prizes(draw):
    """Quote + vincitori de la page du concorso ; vérifie que les numéros concordent."""
    y, m, d = draw["date"].split("-")
    html = get(f"https://www.superenalotto.com/en/results/{d}-{m}-{y}", "SuperEnalotto Odds")
    if not html:
        return None
    t = text(html)
    head = re.search(r"Draw n\.\s*(\d+)\s+((?:\d{1,2}\s+){6})(\d{1,2})\s+Jolly", t)
    if not head or sorted(int(x) for x in head.group(2).split()) != draw["numbers"] \
            or int(head.group(3)) != draw["jolly"]:
        raise SystemExit(f"SE {draw['date']}: numéros de la page ≠ archive")
    block = t[t.find("SuperEnalotto Odds"):t.find("SuperStar Odds")]
    pay, win = {}, {}
    for label, key in SE_KEYS.items():
        mm = re.search(rf"{re.escape(label)} (-|[\d.]+,\d{{2}} €) ([\d.]+)(?= )", block)
        if not mm:
            raise SystemExit(f"SE {draw['date']}: catégorie « {label} » introuvable")
        win[key] = count(mm.group(2))
        v = eur(mm.group(1))
        if v is not None and win[key] > 0:
            pay[key] = v
    return {"concorso": int(head.group(1)), "payouts": pay, "winners": win}


def superenalotto(prev):
    today = date.today()
    draws = se_archive(today.year)
    if len(draws) < KEEP and today.month <= 3:
        time.sleep(3)
        draws += se_archive(today.year - 1)
    draws = sorted(draws, key=lambda x: x["date"], reverse=True)[:KEEP]
    old = {p["date"]: p for p in prev}
    for dr in draws:
        o = old.get(dr["date"])
        if o and o.get("payouts") is not None and o.get("numbers") == dr["numbers"]:
            dr.update({k: o[k] for k in ("concorso", "payouts", "winners") if k in o})
            continue
        time.sleep(2)
        got = se_prizes(dr)
        if got:
            dr.update(got)
        else:
            dr.update({"payouts": None, "winners": None})
            print(f"  SE {dr['date']}: quote pas encore disponibles", file=sys.stderr)
    return draws


# ----------------------------- Eurojackpot -----------------------------

def ej_draw(day):
    url = f"https://www.euro-jackpot.net/results/{day:%d-%m-%Y}"
    html = get(url, "Prize Breakdown", tries=2)
    if not html:
        return None
    t = text(html)
    # Page d'un autre tirage (redirection d'une date sans tirage) → ignorée
    mt = re.search(r"Results for \w+ (\d{1,2}) ?(?:st|nd|rd|th)? (\w+) (\d{4})", t)
    if not mt or (int(mt.group(1)), MONTHS.get(mt.group(2)), int(mt.group(3))) != (day.day, day.month, day.year):
        return None
    balls = re.findall(r'<li class="(ball|euro)[^"]*"[^>]*>\s*(?:<span>)?(\d{1,2})', html)
    nums = [int(n) for k, n in balls if k == "ball"][:5]
    euros = [int(n) for k, n in balls if k == "euro"][:2]
    if len(set(nums)) != 5 or not all(1 <= n <= 50 for n in nums) \
            or len(set(euros)) != 2 or not all(1 <= e <= 12 for e in euros):
        raise SystemExit(f"EJ {day}: numéros illisibles {nums}+{euros}")
    i = t.find(" Italy Numbers Matched")
    if i < 0:
        return {"date": f"{day:%Y-%m-%d}", "numbers": sorted(nums), "euros": sorted(euros),
                "payouts": None, "winners": None}
    block = t[i:t.find("Eurojackpot prizes in Italy", i)]
    pay, win = {}, {}
    for label, key in EJ_KEYS.items():
        mm = re.search(rf"{re.escape(label)} (€[\d,]+\.\d{{2}}) ([\d,]+) (?:€[\d,]+\.\d{{2}}) ([\d,]+)(?= )", block)
        if not mm:
            raise SystemExit(f"EJ {day}: catégorie italienne « {label} » introuvable")
        win[key] = count(mm.group(2))
        total = count(mm.group(3))
        v = eur(mm.group(1))
        # Jackpot non gagné (0 gagnant en Europe) : montant annoncé, pas un gain → absent
        if v is not None and total > 0:
            pay[key] = v
    return {"date": f"{day:%Y-%m-%d}", "numbers": sorted(nums), "euros": sorted(euros),
            "payouts": pay, "winners": win}


def eurojackpot(prev):
    old = {p["date"]: p for p in prev}
    out, day = [], date.today()
    # mardis et vendredis, du plus récent au plus ancien
    while len(out) < KEEP and day > date.today() - timedelta(days=130):
        if day.weekday() in (1, 4):
            key = f"{day:%Y-%m-%d}"
            o = old.get(key)
            if o and o.get("payouts") is not None:
                out.append(o)
            else:
                time.sleep(2)
                got = ej_draw(day)
                if got:
                    out.append(got)
                elif o:
                    out.append(o)
        day -= timedelta(days=1)
    return out


def main():
    prev = {}
    if os.path.exists(FEED):
        try:
            prev = json.load(open(FEED))
        except Exception as e:
            print("flux existant illisible:", e, file=sys.stderr)
    se = superenalotto(prev.get("superenalotto", []))
    ej = eurojackpot(prev.get("eurojackpot", []))
    for name, lst in (("superenalotto", se), ("eurojackpot", ej)):
        if len(lst) < 10:
            raise SystemExit(f"FAIL: {name} seulement {len(lst)} tirages")
        age = (date.today() - date.fromisoformat(lst[0]["date"])).days
        print(f"{name}: {len(lst)} tirages, dernier {lst[0]['date']} ({age} j)", file=sys.stderr)
        if age > MAX_STALE_DAYS:
            raise SystemExit(f"FAIL: {name} périmé")
    new = {"superenalotto": se, "eurojackpot": ej}
    if new == {k: prev.get(k) for k in new}:
        print("Aucune nouvelle donnée.", file=sys.stderr); return
    json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), **new},
              open(FEED, "w"), ensure_ascii=False, indent=1)
    print("OK", file=sys.stderr)


if __name__ == "__main__":
    main()
