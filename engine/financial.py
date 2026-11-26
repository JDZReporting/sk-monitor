#!/usr/bin/env python3
# SKMON-PUBLIC (kód). Výstupy o subjektoch -> súkromná vrstva.
"""
engine/financial.py — finančná analytika nad CRZ (store.json) + RÚZ profilmi (ruz.py --batch).

Dve ODDELENÉ dimenzie (zadanie 2026-11-26):
  - vyznam  : ekonomická významnosť (deskriptívna, bez podozrenia)
  - signaly : rizikové PROXY signály (námety na preverenie, s obmedzeniami a legit. vysvetleniami)

Katalóg a metodika: engine/rules/financial.yaml. Proxy != dôkaz. Obrat != platby od štátu.

Použitie:
  python3 engine/financial.py --selftest
  python3 engine/financial.py <store.json> <ruz_profily.json> <out.json>
"""
import json, sys, os, re
from collections import defaultdict

def _rok(s):
    m = re.match(r"(\d{4})", str(s or "")); return int(m.group(1)) if m else None

def parse_suma(x):
    """Zhodné s analytics/build_db.py — suma v CRZ položke je textový reťazec."""
    if x is None: return None
    t = re.sub(r"[^\d,.]", "", str(x)).replace(" ", "")
    if not t: return None
    t = t.replace(",", ".") if (t.count(",") == 1 and t.count(".") == 0) else t.replace(",", "")
    try: return float(t)
    except Exception: return None

def parse_buyer(meta):
    m = re.search(r"(?:Objednávate[ľl]|Obstarávate[ľl]):\s*([^·]+)", meta or "")
    return (m.group(1).strip() if m else None)

def crz_agg(store):
    """Agreguj CRZ zmluvy podľa IČO dodávateľa (tvar položky zhodný s build_db.py)."""
    items = store.get("items", store if isinstance(store, list) else [])
    objem = defaultdict(float); objem_rok = defaultdict(lambda: defaultdict(float))
    first = {}; buyers = defaultdict(lambda: defaultdict(float)); nazov = {}
    for it in items:
        if it.get("source") not in (None, "zmluvy"):  # len zmluvy (CRZ); None kvôli selftestu
            continue
        ico = it.get("dod_ico")
        if not ico: continue
        s = parse_suma(it.get("suma")) or 0
        objem[ico] += s
        dt = it.get("date") or it.get("datum")
        r = _rok(dt)
        if r: objem_rok[ico][r] += s
        # "prvá zmluva" = najskorší DÁTUM zmluvy (nie scrape timestamp first_seen)
        if dt and (ico not in first or str(dt) < str(first[ico])): first[ico] = str(dt)
        buyer = it.get("objednavatel") or parse_buyer(it.get("meta"))
        if buyer: buyers[ico][buyer] += s
        nm = it.get("dodavatel") or it.get("dod") or it.get("overit")
        if nm: nazov[ico] = nm
    return objem, objem_rok, first, buyers, nazov

def significance_percentil(objem):
    """Percentil objemu v rámci všetkých dodávateľov (0-100)."""
    vals = sorted(objem.values())
    n = len(vals)
    def pct(v):
        if n == 0: return 0
        lo = sum(1 for x in vals if x < v)
        return round(100.0 * lo / n, 1)
    return pct

def analyze_firm(ico, prof, objem, objem_rok, first, buyers, nazov, pct):
    """Vráti scorecard s dvoma dimenziami pre jednu firmu."""
    fin = prof or {}
    rad = fin.get("obrat_rad") or []           # [(rok, obrat)]
    obrat_by_rok = {y: v for y, v in rad}
    posledny_obrat = rad[-1][1] if rad else None
    crz = objem.get(ico, 0.0)

    # --- (A) VÝZNAMNOSŤ ---
    vyznam = {
        "crz_objem_eur": round(crz),
        "crz_percentil": pct(crz),
        "obrat_posledny": posledny_obrat,
        "aktiva": (((fin.get("casovy_rad") or [{}])[0].get("financie")) or {}).get("aktiva_spolu"),
        "sk_nace": fin.get("sk_nace"),
        "pocet_objednavatelov": len(buyers.get(ico, {})),
        "top_objednavatel_podiel": None,
    }
    bs = buyers.get(ico, {})
    if bs and crz > 0:
        top = max(bs.values())
        vyznam["top_objednavatel_podiel"] = round(100.0 * top / crz, 1)
    # dynamika obratu
    if len(rad) >= 2:
        y0, v0 = rad[0]; y1, v1 = rad[-1]
        if v0 and v0 > 0:
            vyznam["obrat_zmena_pct"] = round(100.0 * (v1 - v0) / v0, 1)
            vyznam["obrat_obdobie"] = f"{y0}->{y1}"

    # --- (B) RIZIKOVÉ PROXY SIGNÁLY ---
    signaly = []
    def sig(ind, miera, preco, obmedzenie):
        signaly.append({"indikator": ind, "istota": miera, "preco": preco,
                        "obmedzenie": obmedzenie, "pozn": "proxy, nie dôkaz"})

    # SK-FIN-PUBRELIANCE: proxy závislosti (porovnaj rok, kde máme oboje)
    spolocne = [(r, objem_rok[ico][r], obrat_by_rok[r]) for r in objem_rok.get(ico, {})
                if r in obrat_by_rok and obrat_by_rok[r]]
    if spolocne:
        r, cz, ob = max(spolocne, key=lambda t: t[1])
        podiel = cz / ob if ob else None
        if podiel and podiel >= 0.5:
            sig("SK-FIN-PUBRELIANCE", "nizka",
                f"objem CRZ zmlúv {round(cz)} € ~ {round(100*podiel)} % obratu {round(ob)} € (rok {r})",
                "zmluva=záväzok, nie platba; môže byť viacročná/rámcová; obrat je účtovný, nie cash od štátu")
    # SK-FIN-YOUNGWIN: mladá firma, veľká zákazka
    dz = _rok(fin.get("datum_zalozenia")); fr = _rok(first.get(ico))
    if dz and fr and 0 <= (fr - dz) <= 2 and crz >= 1_000_000:
        sig("SK-FIN-YOUNGWIN", "nizka",
            f"vznik {dz}, prvá veľká zmluva {fr}, objem {round(crz)} €",
            "vek firmy nič nedokazuje; spin-off/nová dcéra/špecialista sú legitímne")
    # SK-FIN-THINCAP: nízka kapitalizácia vs objem
    cr0 = (fin.get("casovy_rad") or [{}])[0].get("financie") if fin.get("casovy_rad") else None
    if cr0 and crz >= 1_000_000:
        akt = cr0.get("aktiva_spolu"); osob = cr0.get("osobne_naklady")
        if akt is not None and akt < 0.05 * crz:
            sig("SK-FIN-THINCAP", "nizka",
                f"aktíva {round(akt)} € voči objemu zmlúv {round(crz)} €",
                "NEOZNAČUJE schránku; sprostredkovanie/služby/subdodávky/holding majú nízke aktíva — pozri NACE a model")
    # SK-FIN-LOSSWIN: opakovaná strata
    straty = [r for r in (fin.get("casovy_rad") or [])
              if r.get("financie") and (r["financie"].get("vysledok_po_dani") or 0) < 0]
    if len(straty) >= 2 and crz >= 500_000:
        sig("SK-FIN-LOSSWIN", "nizka",
            f"strata v {len(straty)} rokoch pri objeme zmlúv {round(crz)} €",
            "strata je bežná (investície, odpisy, cyklus); sama osebe nič neznamená")

    return {
        "ico": ico, "nazov": nazov.get(ico) or fin.get("nazov"),
        "najdene_v_ruz": bool(fin.get("najdene")),
        "rokov_so_strukt_datami": fin.get("rokov_so_strukt_datami", 0),
        "vyznam": vyznam,
        "signaly": signaly,
        "poznamka": "Dve dimenzie: významnosť (deskriptívna) vs signály (proxy na preverenie).",
    }

def run(store, ruz_profily):
    objem, objem_rok, first, buyers, nazov = crz_agg(store)
    pct = significance_percentil(objem)
    firms = {f.get("ico"): f for f in (ruz_profily.get("firmy") or [])}
    out = {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "zdroj": "CRZ + RÚZ (CC0)",
           "metodika": "engine/rules/financial.yaml", "firmy": []}
    # analyzuj tie, ktoré majú RÚZ profil (ostatné sa dajú doplniť)
    for ico, prof in firms.items():
        out["firmy"].append(analyze_firm(ico, prof, objem, objem_rok, first, buyers, nazov, pct))
    # zorad podľa ekonomickej významnosti
    out["firmy"].sort(key=lambda f: f["vyznam"]["crz_objem_eur"], reverse=True)
    return out

def _selftest():
    store = {"items": [
        {"dod_ico": "111", "dodavatel": "Alfa s.r.o.", "objednavatel": "Min A", "suma": 6_000_000, "datum": "2024-05-01", "first_seen": "2024-05-01"},
        {"dod_ico": "111", "dodavatel": "Alfa s.r.o.", "objednavatel": "Min A", "suma": 2_000_000, "datum": "2023-03-01", "first_seen": "2023-03-01"},
        {"dod_ico": "222", "dodavatel": "Beta a.s.", "objednavatel": "Min B", "suma": 500_000, "datum": "2024-01-01", "first_seen": "2024-01-01"},
    ]}
    ruz = {"firmy": [
        {"ico": "111", "najdene": True, "nazov": "Alfa s.r.o.", "datum_zalozenia": "2023-01-10",
         "sk_nace": "46900", "rokov_so_strukt_datami": 2,
         "obrat_rad": [(2023, 2_500_000), (2024, 7_000_000)],
         "casovy_rad": [{"rok": 2024, "financie": {"aktiva_spolu": 120_000, "osobne_naklady": 40_000, "vysledok_po_dani": -50_000, "cisty_obrat": 7_000_000}},
                        {"rok": 2023, "financie": {"aktiva_spolu": 90_000, "vysledok_po_dani": -20_000, "cisty_obrat": 2_500_000}}]},
        {"ico": "222", "najdene": True, "nazov": "Beta a.s.", "datum_zalozenia": "1999-01-01",
         "sk_nace": "41200", "rokov_so_strukt_datami": 1,
         "obrat_rad": [(2024, 20_000_000)],
         "casovy_rad": [{"rok": 2024, "financie": {"aktiva_spolu": 15_000_000, "vysledok_po_dani": 500_000, "cisty_obrat": 20_000_000}}]},
    ]}
    out = run(store, ruz)
    alfa = next(f for f in out["firmy"] if f["ico"] == "111")
    beta = next(f for f in out["firmy"] if f["ico"] == "222")
    inds = {s["indikator"] for s in alfa["signaly"]}
    print("Alfa významnosť:", alfa["vyznam"]["crz_objem_eur"], "percentil", alfa["vyznam"]["crz_percentil"])
    print("Alfa signály:", sorted(inds))
    print("Beta signály:", [s["indikator"] for s in beta["signaly"]])
    ok = True
    # Alfa: young firm + big contract, thin cap, loss x2, high reliance proxy
    for need in {"SK-FIN-YOUNGWIN", "SK-FIN-THINCAP", "SK-FIN-LOSSWIN", "SK-FIN-PUBRELIANCE"}:
        if need not in inds: ok = False; print("  CHÝBA:", need)
    # Beta (stará, zisková, veľké aktíva, nízky pomer) -> žiadne rizikové signály
    if beta["signaly"]: ok = False; print("  Beta nemá mať signály, má:", beta["signaly"])
    # obe dimenzie prítomné a oddelené
    if "vyznam" not in alfa or "signaly" not in alfa: ok = False
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    if argv[0] == "--selftest":
        return _selftest()
    store = json.load(open(argv[0], encoding="utf-8"))
    ruz = json.load(open(argv[1], encoding="utf-8"))
    out = run(store, ruz)
    outp = argv[2] if len(argv) > 2 else "findings/financial.json"
    os.makedirs(os.path.dirname(outp) or ".", exist_ok=True)
    json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapísané: {outp} ({len(out['firmy'])} firiem)")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
