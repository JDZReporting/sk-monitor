#!/usr/bin/env python3
# SKMON-PUBLIC (kód). Výstup (subjektové cykly) -> súkromná vrstva.
"""
engine/contract_lifecycle.py — rekonštrukcia ŽIVOTNÉHO CYKLU kontraktu z CRZ záznamov.

Dodatky sú v CRZ samostatné záznamy s rovnakým číslom zmluvy (zml_cislo) / referenciou (zml_cislo_ref).
Zoskupíme ich, usporiadame v čase a sledujeme vývoj hodnoty, trvania a predmetu.

KRITICKÉ — sémantika súm (zabrániť DVOJITÉMU ZAPOČÍTANIU):
  Dodatok môže (a) NAVYŠOVAŤ pôvodnú cenu o deltu, alebo (b) stanoviť NOVÚ CELKOVÚ cenu.
  - delta      → kumulatív = doterajší kumulatív + suma dodatku
  - nova_cena  → kumulatív = suma dodatku (nahrádza)
  - neurcene   → NEskladáme; sumy zobrazíme oddelene a cyklus označíme ako nejednoznačný
  Sémantiku zisťujeme z TEXTU dodatku (Document Intelligence); bez textu = neurcene (konzervatívne).

PRÁVNY REŽIM (metodická poznámka, nie právny záver): zmeny zmluvy počas trvania upravuje zákon
o verejnom obstarávaní platný v čase uzavretia/zmeny (limity navýšenia, de-minimis, nepredvídateľné
okolnosti). Veľké navýšenia (napr. >50 %) označujeme na preverenie voči platnej úprave, netvrdíme nezákonnosť.

Použitie:
  python3 engine/contract_lifecycle.py --selftest
  python3 engine/contract_lifecycle.py <store.json> [out.json] [--texts texts.json]
"""
import json, sys, os, re, unicodedata
from collections import defaultdict

def _norm_cislo(s):
    s = unicodedata.normalize("NFKD", (s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", "", s).strip()

def _year(s):
    m = re.match(r"(\d{4})", str(s or "")); return int(m.group(1)) if m else None

def _days(d1, d2):
    import datetime
    try:
        a = datetime.date.fromisoformat(str(d1)[:10]); b = datetime.date.fromisoformat(str(d2)[:10])
        return (b - a).days
    except Exception:
        return None

NOVA_CENA = [r"nov[aá]\s+celkov[aá]\s+cena", r"celkov[aá]\s+cena\s+sa\s+men[ií]", r"men[ií]\s+sa\s+na",
             r"nahr[aá]dza\s+sa", r"nov[eé]\s+znenie", r"cena\s+diela\s+je", r"celkov[aá]\s+cena\s+predstavuje"]
DELTA = [r"nav[yý][sš]uje\s+o", r"zvy[sš]uje\s+o", r"o\s+sumu", r"zv[yý][sš]enie\s+o", r"dodato[cč]n[eé].{0,30}vo\s+v[yý][sš]ke",
         r"rozdiel\s+ceny", r"cena\s+sa\s+zvy[sš]uje"]

def classify_dodatok(text):
    """Vráti 'delta' / 'nova_cena' / 'neurcene' podľa textu dodatku."""
    if not text: return "neurcene"
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    for p in NOVA_CENA:
        if re.search(p, t): return "nova_cena"
    for p in DELTA:
        if re.search(p, t): return "delta"
    return "neurcene"

def build_lifecycle(records, texts=None):
    """records: zoznam {typ, datum, suma, dod, obj, url, cislo}. Vráti rekonštrukciu cyklu."""
    texts = texts or {}
    recs = [r for r in records if r.get("datum")]
    recs.sort(key=lambda r: str(r.get("datum")))
    if not recs:
        recs = records[:]
    # pôvodná zmluva = prvý záznam typu Zmluva, inak prvý
    orig = next((r for r in recs if (r.get("typ") or "").lower().startswith("zmluv")), recs[0])
    orig_suma = orig.get("suma")
    timeline = []
    kumul = orig_suma
    nejednoznacne = False
    dodatky = [r for r in recs if r is not orig]
    for r in recs:
        je_dodatok = r is not orig
        sem = None
        if je_dodatok:
            sem = classify_dodatok(texts.get(r.get("url")) or texts.get(r.get("cislo")))
            if r.get("suma") is not None and kumul is not None:
                if sem == "delta": kumul = round(kumul + r["suma"], 2)
                elif sem == "nova_cena": kumul = r["suma"]
                else: nejednoznacne = True   # neskladáme
            elif r.get("suma") is not None and kumul is None:
                nejednoznacne = True
        timeline.append({
            "typ": r.get("typ") or ("Dodatok" if je_dodatok else "Zmluva"),
            "datum": r.get("datum"), "suma": r.get("suma"),
            "semantika_sumy": sem, "dni_od_zmluvy": _days(orig.get("datum"), r.get("datum")) if je_dodatok else 0,
            "url": r.get("url"),
        })
    res = {
        "cislo": orig.get("cislo"), "dodavatel": orig.get("dod"), "objednavatel": orig.get("obj"),
        "povodna_hodnota": orig_suma, "pocet_dodatkov": len(dodatky),
        "datum_zmluvy": orig.get("datum"), "posledna_zmena": recs[-1].get("datum") if recs else None,
        "timeline": timeline,
        "kumulativna_hodnota": (None if nejednoznacne else kumul),
        "sumy_nejednoznacne": nejednoznacne,
    }
    if not nejednoznacne and orig_suma and kumul is not None and orig_suma > 0:
        res["navysenie_absolutne"] = round(kumul - orig_suma, 2)
        res["navysenie_pct"] = round(100.0 * (kumul - orig_suma) / orig_suma, 1)
        if res["navysenie_pct"] >= 50:
            res["upozornenie"] = ("navýšenie ≥50 % — preveriť voči limitom zmeny zmluvy podľa zákona o VO "
                                  "platného v čase uzavretia/zmeny (nie je to tvrdenie o nezákonnosti)")
    else:
        res["pozn"] = ("kumulatív nepočítaný: " +
                       ("nejednoznačná sémantika súm (chýba text dodatku) — sumy neskladať" if nejednoznacne
                        else "chýba pôvodná hodnota"))
    return res

def run(store, texts=None):
    items = store.get("items", store if isinstance(store, list) else [])
    groups = defaultdict(list)
    for it in items:
        if it.get("source") != "zmluvy": continue
        # KĽÚČ = referencia na pôvodnú zmluvu (pri dodatku), inak vlastné číslo zmluvy.
        # Tak sa dodatok (Č. dodatku = 1,2,…) zoskupí pod rodičovskú zmluvu, nie pod seba.
        parent = it.get("zml_cislo_ref") or it.get("zml_cislo")
        if not parent: continue
        groups[_norm_cislo(parent)].append({
            "typ": it.get("zml_typ"), "datum": it.get("date"),
            "suma": it.get("suma_zmluvna"), "dod": it.get("dod"), "obj": None,
            "url": it.get("url"), "cislo": it.get("zml_cislo_ref") or it.get("zml_cislo"),
        })
    cykly = []
    for k, recs in groups.items():
        has_dodatok = any((r.get("typ") or "").lower().startswith("dodatok") for r in recs)
        if len(recs) >= 2 or has_dodatok:
            cykly.append(build_lifecycle(recs, texts))
    cykly.sort(key=lambda c: (c.get("navysenie_pct") or -1, c.get("kumulativna_hodnota") or 0), reverse=True)
    return {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "zdroj": "CRZ (detail zmluvy)",
            "metodika": "3 sémantiky súm; kumulatív len pri jednoznačnej; >50 % = preveriť voči zákonu o VO",
            "pocet_cyklov": len(cykly), "cykly": cykly}

def _selftest():
    # (1) delta: pôvod 100000 + dodatok +20000 (text "navyšuje o") => kumul 120000, +20%
    recs1 = [{"typ": "Zmluva", "datum": "2024-01-10", "suma": 100000.0, "url": "u1", "cislo": "A/1"},
             {"typ": "Dodatok", "datum": "2024-06-10", "suma": 20000.0, "url": "u2", "cislo": "A/1"}]
    r1 = build_lifecycle(recs1, {"u2": "Dodatkom sa cena navyšuje o 20 000 EUR"})
    # (2) nova_cena: pôvod 100000, dodatok nová celková 150000 => kumul 150000, +50%
    recs2 = [{"typ": "Zmluva", "datum": "2024-01-10", "suma": 100000.0, "url": "u1", "cislo": "B/1"},
             {"typ": "Dodatok", "datum": "2024-09-10", "suma": 150000.0, "url": "u3", "cislo": "B/1"}]
    r2 = build_lifecycle(recs2, {"u3": "Nová celková cena diela je 150 000 EUR"})
    # (3) neurcene: bez textu => neskladať
    recs3 = [{"typ": "Zmluva", "datum": "2024-01-10", "suma": 100000.0, "url": "u1", "cislo": "C/1"},
             {"typ": "Dodatok", "datum": "2024-09-10", "suma": 150000.0, "url": "u4", "cislo": "C/1"}]
    r3 = build_lifecycle(recs3, {})
    ok = True
    def chk(c, k, v):
        nonlocal ok
        if c.get(k) != v: ok = False; print(f"  !! {k}={c.get(k)} exp {v}")
    chk(r1, "kumulativna_hodnota", 120000.0); chk(r1, "navysenie_pct", 20.0); chk(r1, "sumy_nejednoznacne", False)
    chk(r2, "kumulativna_hodnota", 150000.0); chk(r2, "navysenie_pct", 50.0)
    if "upozornenie" not in r2: ok = False; print("  !! r2 malo mať upozornenie >=50%")
    chk(r3, "kumulativna_hodnota", None); chk(r3, "sumy_nejednoznacne", True)
    print("dni dodatku (r1):", r1["timeline"][1]["dni_od_zmluvy"])
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    if argv[0] == "--selftest":
        return _selftest()
    store = json.load(open(argv[0], encoding="utf-8"))
    out = "findings/contract_lifecycle.json"; texts = None
    rest = argv[1:]
    if "--texts" in rest:
        i = rest.index("--texts"); texts = json.load(open(rest[i+1], encoding="utf-8")); del rest[i:i+2]
    if rest: out = rest[0]
    res = run(store, texts)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapísané: {out} | cyklov {res['pocet_cyklov']}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
