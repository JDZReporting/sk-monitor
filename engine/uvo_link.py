#!/usr/bin/env python3
# SKMON-PUBLIC (kód). Výstup (subjekty) -> súkromná vrstva.
"""
engine/uvo_link.py — prepojenie procesu: ÚVO zákazka  →  CRZ zmluva  (→ dodatky, platby keď budú).

CIEĽ: sledovať jeden proces od obstarávania po zmluvu a rozlišovať TRI RÔZNE SUMY:
  (1) predpokladaná_hodnota  — z ÚVO (odhad pred súťažou)
  (2) zmluvna_suma           — z CRZ detailu (dohodnutá v zmluve)
  (3) zaplatene              — reálne platby (zatiaľ NEdostupné; CRZ ich neobsahuje) -> "n/a"
NIKDY ich nescitavaj ani nezamieňaj. Rozdiel (2)-(1) je signál (navýšenie oproti odhadu), nie dôkaz.

IDENTIFIKÁTORY (dnešný stav vs cieľ):
  - Dnes: ÚVO položka má len odvodené id (z názvu), CRZ zmluva má stabilné id (z-<cislo>) + dod_ico.
    Preto je prepojenie zatiaľ podľa OBSTARÁVATEĽA + podobnosti názvu + času -> NÍZKA istota, treba overiť.
  - Cieľ (po migrácii ÚVO na štruktúrovaný zdroj): join cez IČO dodávateľa + ID zákazky/časti ->
    vysoká istota. Zdroje na migráciu: ÚVO OpenData (opendata.uvo.gov.sk), TED eForms, OCDS.

Použitie:
  python3 engine/uvo_link.py --selftest
  python3 engine/uvo_link.py <store.json> <out.json> [min_sim=0.34]
"""
import json, sys, os, re, unicodedata
from collections import defaultdict

STOP = set("a and o v na pre do zo za po s so k ku z u i the of for na roku rok zmluva zakazka "
           "dodavka dodavky sluzby sluzieb prace tovar tovary projekt mesto obec".split())

def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()

def _toks(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", _norm(s)) if w not in STOP}

def _jacc(a, b):
    if not a or not b: return 0.0
    return len(a & b) / len(a | b)

def parse_suma(x):
    if x is None: return None
    t = re.sub(r"[^\d,.]", "", str(x)).replace(" ", "")
    if not t: return None
    t = t.replace(",", ".") if (t.count(",") == 1 and t.count(".") == 0) else t.replace(",", "")
    try: return float(t)
    except Exception: return None

def parse_buyer(meta):
    m = re.search(r"(?:Objednávate[ľl]|Obstarávate[ľl]):\s*([^·→]+)", meta or "")
    return (m.group(1).strip() if m else None)

def _year(s):
    m = re.match(r"(\d{4})", str(s or "")); return int(m.group(1)) if m else None

def link(store, min_sim=0.34):
    items = store.get("items", store if isinstance(store, list) else [])
    zakazky, zmluvy = [], []
    for it in items:
        s = it.get("source")
        if s == "uvo":
            zakazky.append({"id": it.get("id"), "title": it.get("title"),
                            "buyer": parse_buyer(it.get("meta")), "date": it.get("date"),
                            "predpokladana": parse_suma(it.get("suma")), "cpv": it.get("cpv"),
                            "druh": it.get("druh"), "url": it.get("url")})
        elif s == "zmluvy":
            zmluvy.append({"id": it.get("id"), "title": it.get("title"),
                           "buyer": parse_buyer(it.get("meta")), "date": it.get("date"),
                           "dod": it.get("dod"), "dod_ico": it.get("dod_ico"),
                           "zmluvna": it.get("suma_zmluvna") if it.get("suma_zmluvna") is not None else parse_suma(it.get("suma")),
                           "url": it.get("url")})
    # index zákaziek podľa normalizovaného obstarávateľa
    by_buyer = defaultdict(list)
    for z in zakazky:
        if z["buyer"]: by_buyer[_norm(z["buyer"])].append({**z, "_tok": _toks(z["title"])})
    links = []
    for c in zmluvy:
        if not c["buyer"]: continue
        cand = by_buyer.get(_norm(c["buyer"]))
        if not cand: continue
        ctok = _toks(c["title"]); cy = _year(c["date"])
        best, bestsim = None, 0.0
        for z in cand:
            sim = _jacc(ctok, z["_tok"])
            # časové pravidlo: zmluva by mala byť po/okolo zákazky (±1 rok tolerancia)
            zy = _year(z["date"])
            if cy and zy and cy < zy - 1:  # zmluva výrazne pred zákazkou -> nepravdepodobné
                continue
            if sim > bestsim: best, bestsim = z, sim
        if best and bestsim >= min_sim:
            pred = best["predpokladana"]; zml = c["zmluvna"]
            rozdiel = (round(zml - pred) if (pred is not None and zml is not None) else None)
            links.append({
                "obstaravatel": c["buyer"], "dodavatel": c["dod"], "dod_ico": c["dod_ico"],
                "zakazka_nazov": best["title"], "zmluva_nazov": c["title"],
                "predpokladana_hodnota": pred,            # (1) ÚVO
                "zmluvna_suma": zml,                      # (2) CRZ
                "zaplatene": None,                        # (3) n/a (nemáme platby)
                "rozdiel_zmluvna_minus_predpoklad": rozdiel,
                "istota": round(bestsim, 2),
                "uroven_istoty": "stredná" if bestsim >= 0.55 else "nízka",
                "zakazka_url": best["url"], "zmluva_url": c["url"],
                "pozn": "Prepojenie podľa obstarávateľa+názvu (nie cez ID/IČO) — OVERIŤ. Sumy sú rôzne veličiny, nescitavať.",
            })
    links.sort(key=lambda l: (l["istota"], l.get("zmluvna_suma") or 0), reverse=True)
    return {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "zdroj": "ÚVO + CRZ",
            "pocet_zakaziek": len(zakazky), "pocet_zmluv": len(zmluvy), "pocet_prepojeni": len(links),
            "metodika": "3 oddelené sumy (predpokladaná/zmluvná/zaplatená=n/a); join názov+obstarávateľ (nízka istota).",
            "links": links}

def _selftest():
    store = {"items": [
        {"source": "uvo", "id": "u-rekonstrukcia cesty ii 507", "title": "Rekonštrukcia cesty II/507 úsek Alfa",
         "meta": "Obstarávateľ: Mesto Testov", "date": "2024-02-01", "suma": "1 000 000 €"},
        {"source": "zmluvy", "id": "z-1", "title": "Rekonštrukcia cesty II/507 úsek Alfa - zmluva o dielo",
         "meta": "Dodávateľ: StavbaX s.r.o. → Objednávateľ: Mesto Testov", "date": "2024-06-01",
         "dod": "StavbaX s.r.o.", "dod_ico": "11112222", "suma_zmluvna": 1250000.0},
        {"source": "zmluvy", "id": "z-2", "title": "Nákup kancelárskych potrieb",
         "meta": "Dodávateľ: PapierY → Objednávateľ: Mesto Testov", "date": "2024-03-01",
         "dod": "PapierY", "suma_zmluvna": 5000.0},
    ]}
    r = link(store)
    ok = True
    if r["pocet_prepojeni"] != 1: ok = False; print("  !! očak. 1 prepojenie, mám", r["pocet_prepojeni"])
    if ok:
        L = r["links"][0]
        print("  prepojenie:", L["zakazka_nazov"][:30], "->", L["dodavatel"], "| istota", L["istota"])
        print("  predpokladaná", L["predpokladana_hodnota"], "| zmluvná", L["zmluvna_suma"],
              "| rozdiel", L["rozdiel_zmluvna_minus_predpoklad"], "| zaplatené", L["zaplatene"])
        if L["dod_ico"] != "11112222": ok = False
        if L["rozdiel_zmluvna_minus_predpoklad"] != 250000: ok = False; print("  !! zlý rozdiel")
        if L["zaplatene"] is not None: ok = False
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    if argv[0] == "--selftest":
        return _selftest()
    store = json.load(open(argv[0], encoding="utf-8"))
    out = argv[1] if len(argv) > 1 else "findings/uvo_crz_links.json"
    min_sim = float(argv[2]) if len(argv) > 2 else 0.34
    res = link(store, min_sim)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapísané: {out} | zákaziek {res['pocet_zakaziek']} zmlúv {res['pocet_zmluv']} prepojení {res['pocet_prepojeni']}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
