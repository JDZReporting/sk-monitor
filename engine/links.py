#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — PREPOJENIE kontrolných zistení (NKÚ) s verejnými výdavkami.
Spája kontrolovaný subjekt (NKÚ) s jeho zmluvami (objednávateľ) a zákazkami (obstarávateľ),
takže vidno: subjekt, ktorý NKÚ kontroloval, A ZÁROVEŇ míňa verejné peniaze cez kontrakty
— vrátane dodávateľov a súm. Všetko sú OFICIÁLNE FAKTY (žiadna hypotéza), ale keďže menuje
subjekty, výstup ide do súkromnej vrstvy (sk-monitor-intelligence) na ľudské posúdenie.

Vstup: data/store.json (verejný). Výstup: findings/kontrolne_vydavky.{json,md}
Použitie: python engine/links.py [cesta_k_store.json] [výstupný_adresár]
"""
import json, sys, os, re
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import parse_suma, parse_buyer

SENTINEL = "SKMON-PRIVATE-DO-NOT-PUBLISH"

# právne formy a šumové tokeny, ktoré pri porovnaní názvov ignorujeme
_LEGAL = r"\b(s\.?\s?r\.?\s?o|a\.?\s?s|spol|k\.?\s?s|v\.?\s?o\.?\s?s|o\.?\s?z|n\.?\s?o|š\.?\s?p|štátny podnik|a\. s\.)\b"

def norm(s):
    s = (s or "").lower()
    s = s.replace("č.", " ").replace("·", " ")
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(_LEGAL.replace("š", "s").replace("č", "c"), " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def run(store):
    items = store.get("items", [])
    # 1) kontrolované subjekty (NKÚ): normalizovaný názov -> {nazov, audity[]}
    audited = defaultdict(lambda: {"nazov": "", "audity": []})
    for it in items:
        if it.get("source") != "kontrolne":
            continue
        subj = it.get("overit") or ""
        k = norm(subj)
        if len(k) < 4:
            continue
        audited[k]["nazov"] = audited[k]["nazov"] or subj
        audited[k]["audity"].append({"nazov": it.get("title", "")[:120], "date": it.get("date"),
                                     "ka": re.sub(r".*(KA-\S+).*", r"\1", it.get("meta", "")) if "KA-" in it.get("meta", "") else "",
                                     "url": it.get("url", "")})
    # 2) výdavky (zmluvy objednávateľ / zákazky obstarávateľ) podľa normalizovaného kupujúceho
    spend = defaultdict(list)
    for it in items:
        s = it.get("source")
        if s not in ("zmluvy", "uvo"):
            continue
        buyer = parse_buyer(it.get("meta"))
        if not buyer:
            continue
        spend[norm(buyer)].append(it)
    # 3) prienik: kontrolovaný subjekt, ktorý zároveň míňa
    links = []
    for k, info in audited.items():
        sp = spend.get(k, [])
        if not sp:
            continue
        total = 0.0
        contracts = []
        for it in sp:
            v = parse_suma(it.get("suma")) or 0
            total += v
            contracts.append({"source": it.get("source"), "nazov": it.get("title", "")[:100],
                              "dod": it.get("dod", ""), "suma": v, "date": it.get("date"),
                              "url": it.get("url", "")})
        contracts.sort(key=lambda c: c["suma"], reverse=True)
        links.append({"subjekt": info["nazov"], "pocet_auditov": len(info["audity"]),
                      "pocet_kontraktov": len(sp), "suma_spolu": round(total, 2),
                      "audity": info["audity"][:5], "kontrakty": contracts[:10]})
    links.sort(key=lambda x: (x["suma_spolu"], x["pocet_kontraktov"]), reverse=True)
    return links

def render_md(links):
    out = ["<!-- " + SENTINEL + " -->",
           "# Prepojenie: kontrolované subjekty (NKÚ) × verejné výdavky", "",
           "Subjekty, ktoré NKÚ kontroloval A ZÁROVEŇ míňajú verejné peniaze cez zmluvy/zákazky.",
           "Oficiálne fakty — pred publikovaním konkrétnych tvrdení o subjekte nutné ľudské overenie.", ""]
    if not links:
        out.append("_Žiadne prekryvy v aktuálnom okne dát._")
        return "\n".join(out)
    out.append(f"**Nájdených prepojení: {len(links)}**\n")
    for L in links[:40]:
        out.append(f"## {L['subjekt']}")
        out.append(f"- Auditov NKÚ: {L['pocet_auditov']} · Kontraktov: {L['pocet_kontraktov']} · "
                   f"Suma spolu: {L['suma_spolu']:,.0f} €".replace(",", " "))
        if L["audity"]:
            a = L["audity"][0]
            out.append(f"- Kontrola: {a['nazov']} ({a.get('ka','')}, {a.get('date','')})")
        for c in L["kontrakty"][:5]:
            lab = "zmluva" if c["source"] == "zmluvy" else "zákazka"
            dod = (" → " + c["dod"]) if c["dod"] else ""
            suma = f" · {c['suma']:,.0f} €".replace(",", " ") if c["suma"] else ""
            out.append(f"  - [{lab}] {c['nazov']}{dod}{suma}")
        out.append("")
    return "\n".join(out)

def main():
    store_path = sys.argv[1] if len(sys.argv) > 1 else "data/store.json"
    outdir = sys.argv[2] if len(sys.argv) > 2 else "findings"
    store = json.load(open(store_path, encoding="utf-8"))
    links = run(store)
    os.makedirs(outdir, exist_ok=True)
    json.dump({"generated_from": store_path, "pocet": len(links), SENTINEL: True, "links": links},
              open(os.path.join(outdir, "kontrolne_vydavky.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    open(os.path.join(outdir, "kontrolne_vydavky.md"), "w", encoding="utf-8").write(render_md(links))
    print(f"links.py: {len(links)} prepojení kontrola×výdavky")

if __name__ == "__main__":
    main()
