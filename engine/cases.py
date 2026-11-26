#!/usr/bin/env python3
# SKMON-PUBLIC (kód). Spisy sú SÚKROMNÉ (findings/cases.json).
"""
engine/cases.py — trvalé investigatívne SPISY (case management).

Princíp (zadanie 2026-11-26): engine pri automatickom behu AKTUALIZUJE len automatické polia
(signály, auto-timeline, prepojené zmluvy/dodatky, návrhy krokov). RUČNÉ polia sa NIKDY neprepíšu:
  - stav (ak ho človek nastavil), moje_poznamky, dokazy, protidokazy, rucne_rozhodnutia, manualne_prepojenia,
  - archivované/vyriešené/vyvrátené spisy sa znovu neotvárajú automaticky.
Spis má TRVALÉ ID (SPIS-xxxxxx), nemení sa medzi behmi. Súvisiace signály sa spájajú do jedného spisu
podľa IČO (alebo normalizovaného názvu).

Vstup: findings/radar.json (+ voliteľne financial/uvo_crz_links/contract_lifecycle pre kontext).
Stav:  findings/cases.json (číta sa a zapisuje — PERZISTENTNÝ, commitovaný v súkromnom repe).

Použitie:
  python3 engine/cases.py --selftest
  python3 engine/cases.py <findings_dir>        # sync: vytvorí/aktualizuje spisy, zachová ručné dáta
"""
import json, sys, os, re, hashlib, datetime, unicodedata

AUTO_FIELDS = {"signaly", "auto_timeline", "vyznam_skore", "riziko_skore", "typ_temy",
               "suvisiace_zmluvy", "navrhy_krokov", "auto_updated", "nazov"}
MANUAL_FIELDS = {"stav", "moje_poznamky", "dokazy", "protidokazy", "rucne_rozhodnutia",
                 "manualne_prepojenia", "priorita_clovek"}
CLOSED = {"vyrieseny", "vyvrateny", "archivovany"}  # tieto engine znovu neotvára

def _now(): return datetime.datetime.now().isoformat(timespec="seconds")

def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()

def _case_key(ico, nazov):
    return ("ico:" + str(ico)) if ico else ("nm:" + _norm(nazov))

def _new_id(key):
    return "SPIS-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:8].upper()

def _load(d, n):
    p = os.path.join(d, n)
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None

def _navrhy(lead, lifecycle_hit):
    """Automatické návrhy ďalších krokov podľa signálov (deterministicky, bez LLM)."""
    out = []
    inds = {s.get("indikator") for s in (lead.get("preco", {}).get("riziko") or [])}
    if "SK-FIN-YOUNGWIN" in inds: out.append("Overiť históriu konateľov a vlastníkov (RPO/RPVS), referencie firmy.")
    if "SK-FIN-THINCAP" in inds: out.append("Porovnať aktíva/osobné náklady s objemom zmlúv; zistiť subdodávky (NACE, model).")
    if "SK-FIN-PUBRELIANCE" in inds: out.append("Overiť skutočné platby (faktúry) vs zmluvná hodnota; rozpísať zmluvy na roky.")
    if "SK-OWN-SHARED" in inds: out.append("Preveriť, či prepojené firmy súťažili v tom istom obstarávaní (formálna nezávislosť).")
    if "NKÚ-KONTROLA×VÝDAVKY" in inds: out.append("Získať a prečítať protokol NKÚ; posúdiť závažnosť a či boli nedostatky odstránené.")
    if lifecycle_hit: out.append("Preveriť dodatky: dôvod navýšenia a súlad s limitmi zmeny zmluvy (zákon o VO).")
    if not out: out.append("Potvrdiť ekonomickú významnosť a kontext; rozhodnúť, či otvoriť plný spis.")
    return out

def sync(radar, existing, lifecycle=None):
    """Zlúči radar leady do spisov; zachová ručné polia z existing."""
    existing = existing or {"cases": {}}
    cases = existing.get("cases", {})
    # index životného cyklu podľa dodávateľa (pre návrh krokov)
    lc_by_sup = {}
    for c in (lifecycle or {}).get("cykly", []):
        if c.get("dodavatel"): lc_by_sup.setdefault(_norm(c["dodavatel"]), []).append(c)

    for lead in (radar or {}).get("leady", []):
        typ = lead.get("typ_temy", "")
        # spis zakladáme len pre relevantné (nie „bežné"/„sledovať" bez rizika)
        if not (typ.startswith("prioritné") or typ.startswith("na preverenie") or lead.get("vyznam_skore", 0) >= 70):
            continue
        key = _case_key(lead.get("ico"), lead.get("nazov"))
        cid = _new_id(key)
        c = cases.get(cid)
        if c and c.get("stav") in CLOSED:
            continue  # uzavretý spis engine znovu neotvára
        lc_hit = lc_by_sup.get(_norm(lead.get("nazov") or ""))
        auto = {
            "id": cid, "kluc": key, "nazov": lead.get("nazov"), "ico": lead.get("ico"),
            "typ_temy": typ, "vyznam_skore": lead.get("vyznam_skore"), "riziko_skore": lead.get("riziko_skore"),
            "signaly": lead.get("preco"), "suvisiace_zmluvy": [c0.get("cislo") for c0 in (lc_hit or [])],
            "navrhy_krokov": _navrhy(lead, bool(lc_hit)), "auto_updated": _now(),
        }
        if not c:
            # nový spis — ručné polia prázdne
            cases[cid] = {**auto, "vytvoreny": _now(), "stav": "novy",
                          "moje_poznamky": [], "dokazy": [], "protidokazy": [],
                          "rucne_rozhodnutia": [], "manualne_prepojenia": [], "auto_timeline": [
                              {"kedy": _now(), "co": f"Spis vytvorený automaticky ({typ})."}]}
        else:
            # EXISTUJÚCI spis — prepíš LEN auto polia, ručné nechaj
            changed = []
            for f in AUTO_FIELDS:
                if f in auto and c.get(f) != auto[f]:
                    c[f] = auto[f]; changed.append(f)
            # auto-timeline: pripni záznam, ak sa zmenili signály/skóre
            if {"signaly", "riziko_skore", "vyznam_skore"} & set(changed):
                c.setdefault("auto_timeline", []).append(
                    {"kedy": _now(), "co": "Aktualizované automatické signály/skóre."})
            # stav: ak ho človek nenastavil (ostal 'novy'/'auto'), môže engine ponechať; inak nechať
    return {"SKMON-PRIVATE-DO-NOT-PUBLISH": True,
            "pozn": "Spisy: auto polia aktualizuje engine; ručné (stav, poznámky, dôkazy, rozhodnutia) sa NEPREPISUJÚ.",
            "pocet": len(cases), "cases": cases}

def _selftest():
    radar = {"leady": [
        {"nazov": "Firma A", "ico": "111", "typ_temy": "prioritné preverenie (významné + rizikové)",
         "vyznam_skore": 80, "riziko_skore": 40,
         "preco": {"riziko": [{"indikator": "SK-FIN-YOUNGWIN"}], "vyznamnost": ["objem"]}},
        {"nazov": "Firma B", "ico": "222", "typ_temy": "bežné", "vyznam_skore": 10, "riziko_skore": 0,
         "preco": {"riziko": [], "vyznamnost": []}},
    ]}
    r1 = sync(radar, None)
    cidA = _new_id(_case_key("111", "Firma A"))
    ok = True
    if cidA not in r1["cases"]: ok = False; print("  !! spis A nevznikol")
    if any(_new_id(_case_key("222", "Firma B")) == k for k in r1["cases"]): ok = False; print("  !! B (bežné) nemal vzniknúť")
    # človek pridá poznámku + zmení stav
    r1["cases"][cidA]["moje_poznamky"].append("Zavolať na úrad, overiť zmluvu X.")
    r1["cases"][cidA]["stav"] = "v_rieseni"
    r1["cases"][cidA]["dokazy"].append("Zmluva č. 123 — kópia uložená.")
    # druhý beh enginu (radar sa zmenil — iné skóre)
    radar["leady"][0]["riziko_skore"] = 55
    r2 = sync(radar, r1)
    c = r2["cases"][cidA]
    if c["moje_poznamky"] != ["Zavolať na úrad, overiť zmluvu X."]: ok = False; print("  !! poznámka sa stratila/prepísala")
    if c["stav"] != "v_rieseni": ok = False; print("  !! stav prepísaný:", c["stav"])
    if c["dokazy"] != ["Zmluva č. 123 — kópia uložená."]: ok = False; print("  !! dôkaz sa stratil")
    if c["riziko_skore"] != 55: ok = False; print("  !! auto skóre sa neaktualizovalo")
    # uzavretý spis sa znovu neotvára
    r2["cases"][cidA]["stav"] = "vyvrateny"
    r3 = sync(radar, r2)
    if r3["cases"][cidA]["stav"] != "vyvrateny": ok = False; print("  !! uzavretý spis zmenený")
    print("spisov:", r3["pocet"], "| A stav:", r3["cases"][cidA]["stav"], "| poznámky zachované:", c["moje_poznamky"])
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"): print(__doc__); return 0
    if argv[0] == "--selftest": return _selftest()
    d = argv[0]
    radar = _load(d, "radar.json"); existing = _load(d, "cases.json")
    lifecycle = _load(d, "contract_lifecycle.json")
    res = sync(radar, existing, lifecycle)
    out = os.path.join(d, "cases.json")
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapísané: {out} | spisov {res['pocet']}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
