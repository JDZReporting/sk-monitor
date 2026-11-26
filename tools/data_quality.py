#!/usr/bin/env python3
# SKMON-PUBLIC (agregátne počty, žiadne citlivé subjektové dáta)
"""
tools/data_quality.py — TRVALÝ interný prehľad kvality dát. Spúšťa sa po každom zbere.

Každá metrika nesie: hodnotu, čitateľa (numerator), menovateľa (denominator), rozsah dát a
spôsob výpočtu (method). Metriky bez dostupných vstupov sa označia "n/a" + dôvod (nezavádzať nuly).

Použitie:
  python3 tools/data_quality.py --store data/store.json [--findings <dir>] [--health data/source_health.json] [--out data/data_quality.json]
  python3 tools/data_quality.py --selftest
"""
import json, sys, os, re, argparse, datetime
from collections import Counter, defaultdict

def _load(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None

def _rok(s):
    m = re.match(r"(\d{4})", str(s or "")); return int(m.group(1)) if m else None

def M(hodnota, num=None, den=None, rozsah=None, method=""):
    d = {"hodnota": hodnota, "method": method}
    if num is not None: d["numerator"] = num
    if den is not None: d["denominator"] = den
    if rozsah is not None: d["rozsah_dat"] = rozsah
    if den == 0: d["hodnota"] = None; d["pozn"] = "menovateľ 0"
    return d

def compute(store, findings_dir=None, health=None):
    items = (store or {}).get("items", store if isinstance(store, list) else []) or []
    metr = {}

    # 1) počet záznamov podľa zdroja
    bysrc = Counter(it.get("source") for it in items)
    metr["zaznamy_podla_zdroja"] = M(dict(bysrc), num=len(items), den=len(items),
        method="count(items) group by source (aktuálny store.json)")

    # 2) historické pokrytie (min/max dátum + rozpätie mesiacov) per zdroj
    hist = {}
    for s in bysrc:
        ds = [it.get("date") for it in items if it.get("source") == s and it.get("date")]
        ds = sorted(d for d in ds if _rok(d))
        if ds:
            hist[s] = {"od": ds[0], "do": ds[-1], "zaznamov_s_datumom": len(ds)}
    metr["historicke_pokrytie"] = M(hist, method="min/max(date) per source; len=počet s platným dátumom. "
        "POZN: store = 30-dňové okno; viacročná história je v data/history/*.jsonl (nie tu).")

    # 3) podiel záznamov s validným IČO (len zmluvy — tam má IČO zmysel)
    zm = [it for it in items if it.get("source") == "zmluvy"]
    def valid_ico(x): return bool(x) and bool(re.fullmatch(r"\d{6,8}", str(x)))
    zm_ico = [it for it in zm if valid_ico(it.get("dod_ico"))]
    metr["zmluvy_s_validnym_ico"] = M(round(100*len(zm_ico)/len(zm), 1) if zm else None,
        num=len(zm_ico), den=len(zm), method="zmluvy s dod_ico vo formáte 6–8 číslic / všetky zmluvy")

    # 3b) provenancia IČO (primárne CRZ vs sekundárne RPO) — presnosť > počet
    prov = Counter(it.get("dod_ico_zdroj") for it in zm_ico)
    metr["ico_provenancia"] = M({(k or "?"): v for k, v in prov.items()},
        num=len(zm_ico), den=len(zm_ico),
        method="dod_ico_zdroj: 'crz'=primárne z detailu zmluvy (jednoznačné), 'rpo'=sekundárne zhoda mena (jednoznačná aktívna firma)")

    # 4) identifikovaní dodávatelia (unikátni podľa mena) — koľko má IČO
    sup = defaultdict(lambda: {"ico": None})
    for it in zm:
        nm = (it.get("dod") or it.get("overit") or "").strip()
        if not nm: continue
        if valid_ico(it.get("dod_ico")): sup[nm]["ico"] = it["dod_ico"]
        else: sup[nm].setdefault("ico", None)
    uniq = len(sup); ident = sum(1 for v in sup.values() if v["ico"])
    metr["dodavatelia_identifikovani"] = M(round(100*ident/uniq, 1) if uniq else None,
        num=ident, den=uniq, method="unikátni dodávatelia (podľa názvu) s prideleným IČO / všetci unikátni dodávatelia")
    metr["dodavatelia_neidentifikovani"] = M(uniq - ident, num=uniq - ident, den=uniq,
        method="unikátni dodávatelia bez IČO (CRZ detail zlyhal / nejednoznačná RPO zhoda / zahr. subjekt)")

    # 5) duplicity (rovnaké id viackrát v store — malo by byť 0)
    ids = [it.get("id") for it in items if it.get("id")]
    dup = len(ids) - len(set(ids))
    metr["duplicitne_zaznamy"] = M(dup, num=dup, den=len(ids), method="count(id) - count(distinct id) v store.json")

    # ---- metriky závislé od súkromných findings (RÚZ/RPVS/dokumenty) ----
    def fload(n): return _load(os.path.join(findings_dir, n)) if findings_dir else None
    ruz = fload("ruz_profily.json")
    if ruz and ruz.get("firmy"):
        fs = ruz["firmy"]; naj = sum(1 for f in fs if f.get("najdene"))
        strukt = sum(1 for f in fs if (f.get("rokov_so_strukt_datami") or 0) > 0)
        metr["ruz_pokrytie"] = M(round(100*naj/len(fs), 1), num=naj, den=len(fs),
            method="firmy nájdené v RÚZ / analyzované firmy (top dodávatelia)")
        metr["ruz_strukturovane_vykazy"] = M(round(100*strukt/len(fs), 1), num=strukt, den=len(fs),
            method="firmy aspoň s 1 rokom štrukt. výkazu / analyzované (IFRS/2009–2012 bývajú len PDF)")
    else:
        metr["ruz_pokrytie"] = M("n/a", method="chýba findings/ruz_profily.json (vzniká v Actions)")

    own = fload("ownership.json")
    if own and own.get("rows"):
        rows = own["rows"]; pvs = sum(1 for r in rows if r.get("je_partner_vs"))
        metr["rpvs_pokrytie"] = M(round(100*pvs/len(rows), 1), num=pvs, den=len(rows),
            method="subjekty označené ako partner VS / analyzované subjekty (koneční užívatelia výhod)")
    else:
        metr["rpvs_pokrytie"] = M("n/a", method="chýba findings/ownership.json (vzniká v Actions)")

    doc = fload("document_findings.json") or fload("documents.json")
    if doc:
        proc = doc.get("spracovane") or doc.get("processed") or doc.get("pocet")
        metr["dokumenty_extrakcia"] = M(proc, method="počet úspešne spracovaných PDF (document.py)")
    else:
        metr["dokumenty_extrakcia"] = M("n/a", method="chýba výstup document.py (vzniká v Actions)")

    fin = fload("financial.json")
    if fin and fin.get("firmy"):
        miss = sum(1 for f in fin["firmy"] if not (f.get("vyznam") or {}).get("obrat_posledny"))
        metr["zaznamy_bez_financii"] = M(miss, num=miss, den=len(fin["firmy"]),
            method="firmy bez dostupného obratu (RÚZ) / analyzované firmy")

    # Investigatívne spisy (engine/cases.py)
    cs = fload("cases.json")
    if cs and ("cases" in cs):
        cc = cs["cases"]
        otv = sum(1 for c in cc.values() if c.get("stav") not in ("vyrieseny", "vyvrateny", "archivovany"))
        metr["spisy_celkom"] = M(len(cc), num=len(cc), method="počet investigatívnych spisov (cases.json)")
        metr["spisy_otvorene"] = M(otv, num=otv, den=len(cc), method="spisy, ktoré nie sú vyriešené/vyvrátené/archivované")

    # Životný cyklus / dodatky (engine/contract_lifecycle.py)
    lc = fload("contract_lifecycle.json")
    if lc and ("pocet_cyklov" in lc):
        amb = sum(1 for c in (lc.get("cykly") or []) if c.get("sumy_nejednoznacne"))
        metr["zmluvy_s_dodatkami"] = M(lc["pocet_cyklov"], num=lc["pocet_cyklov"], den=len(zm),
            method="zmluvy s ≥1 dodatkom (podľa čísla zmluvy) / všetky zmluvy")
        metr["cykly_nejednoznacna_suma"] = M(amb, num=amb, den=lc["pocet_cyklov"],
            method="cykly, kde sa kumulatív nedá spočítať (chýba text dodatku) — konzervatívne, neskladá sa")
    else:
        metr["zmluvy_s_dodatkami"] = M("n/a", method="chýba findings/contract_lifecycle.json (vzniká v Actions)")

    # ÚVO↔CRZ prepojenie (engine/uvo_link.py)
    ul = fload("uvo_crz_links.json")
    if ul and ("pocet_prepojeni" in ul):
        den = ul.get("pocet_zmluv") or 0
        metr["uvo_crz_prepojenie"] = M(ul["pocet_prepojeni"], num=ul["pocet_prepojeni"], den=den,
            method="prepojené zmluvy↔zákazky / všetky zmluvy. Join názov+obstarávateľ (nízka istota), nie cez ID/IČO.")
    else:
        metr["uvo_crz_prepojenie"] = M("n/a", method="chýba findings/uvo_crz_links.json (vzniká v Actions)")

    # posledná aktualizácia zdrojov
    if health:
        if isinstance(health, dict) and isinstance(health.get("sources"), dict):
            health = health["sources"]   # source_health.json má tvar {generated, sources:{...}}
        la = {}
        for k, v in (health.items() if isinstance(health, dict) else []):
            if isinstance(v, dict):
                la[k] = {"stav": v.get("state") or v.get("status"), "aktualizovane": v.get("updated") or v.get("last")}
        metr["posledna_aktualizacia_zdrojov"] = M(la or health, method="z data/source_health.json")
    else:
        metr["posledna_aktualizacia_zdrojov"] = M("n/a", method="chýba source_health.json")

    return {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "store_items": len(items), "metriky": metr}

def _selftest():
    store = {"items": [
        {"id": "z-1", "source": "zmluvy", "dod": "Alfa s.r.o.", "dod_ico": "12345678", "dod_ico_zdroj": "crz", "date": "2024-05-01"},
        {"id": "z-2", "source": "zmluvy", "dod": "Beta a.s.", "dod_ico": "87654321", "dod_ico_zdroj": "rpo", "date": "2023-02-01"},
        {"id": "z-3", "source": "zmluvy", "dod": "Gama", "date": "2024-01-01"},  # bez IČO
        {"id": "u-1", "source": "uvo", "date": "2024-03-01"},
        {"id": "u-1", "source": "uvo", "date": "2024-03-01"},  # duplicitné id
    ]}
    r = compute(store)
    m = r["metriky"]
    ok = True
    checks = [
        (m["zmluvy_s_validnym_ico"]["numerator"], 2),
        (m["zmluvy_s_validnym_ico"]["denominator"], 3),
        (m["dodavatelia_identifikovani"]["numerator"], 2),
        (m["dodavatelia_neidentifikovani"]["hodnota"], 1),
        (m["duplicitne_zaznamy"]["hodnota"], 1),
        (m["ico_provenancia"]["hodnota"].get("crz"), 1),
        (m["ico_provenancia"]["hodnota"].get("rpo"), 1),
    ]
    for got, exp in checks:
        if got != exp: ok = False; print("  !! got", got, "exp", exp)
    print("zdroje:", m["zaznamy_podla_zdroja"]["hodnota"])
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/store.json")
    ap.add_argument("--findings", default=None)
    ap.add_argument("--health", default="data/source_health.json")
    ap.add_argument("--out", default="data/data_quality.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest: return _selftest()
    store = _load(a.store) or {"items": []}
    health = _load(a.health)
    rep = compute(store, a.findings, health)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(rep, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("data_quality:", a.out, "| items", rep["store_items"])
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
