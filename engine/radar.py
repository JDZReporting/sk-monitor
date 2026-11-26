#!/usr/bin/env python3
# SKMON-PUBLIC (kód). Výstup (subjektové leady) -> súkromná vrstva.
"""
engine/radar.py — investigatívny + ekonomický RADAR. Spája signály do jedného rebríčka leadov,
ale DVE OSI drží oddelene (zadanie 2026-11-26):
  - vyznam_skore  (0–100): ekonomická významnosť — veľkosť peňazí, rast, koncentrácia, nový hráč.
  - riziko_skore  (0–100): investigatívne proxy signály — na preverenie, s obmedzeniami.
Nekolabuje ich do jednej „pravdepodobnosti korupcie". Lead môže byť čisto EKONOMICKÁ TÉMA
(významné, bez podozrenia) alebo NA PREVERENIE, alebo oboje.

Vstup: findings/financial.json (vyznam+signaly) + voliteľne risk_scored.json, ownership.json,
kontrolne_vydavky.json, uvo_crz_links.json. Výstup: findings/radar.json.

Použitie:
  python3 engine/radar.py --selftest
  python3 engine/radar.py <findings_dir> [out.json]
"""
import json, sys, os, re, unicodedata
from collections import defaultdict

def _load(d, n):
    p = os.path.join(d, n)
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None

def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()

def _clamp(x): return max(0, min(100, int(round(x))))

# váhy rizikových signálov (nízke — sú to proxy, nie dôkaz)
RISK_W = {"SK-FIN-PUBRELIANCE": 18, "SK-FIN-YOUNGWIN": 22, "SK-FIN-THINCAP": 16, "SK-FIN-LOSSWIN": 12,
          "SK-FIN-STATEDEBT": 22, "SK-OWN-NAMECHANGE": 14, "SK-OWN-SEATCHANGE": 12, "SK-SUP-NEW": 10,
          "SK-AUDIT-SPENDER": 20, "SK-AUDIT-REPEAT": 14, "SK-OWN-SHARED": 18, "SK-COMBO": 10, "SK-HIGHVALUE": 8}

def compute(fin, risk=None, own=None, kontrola=None):
    leads = {}  # kľúč = ico alebo norm(nazov)
    def key(ico, nazov): return ("ico:" + str(ico)) if ico else ("nm:" + _norm(nazov))

    for f in (fin or {}).get("firmy", []):
        v = f.get("vyznam") or {}
        k = key(f.get("ico"), f.get("nazov"))
        # --- os VÝZNAMNOSŤ ---
        vyz = 0.0; vyzp = []
        pct = v.get("crz_percentil")
        if pct is not None:
            vyz += 0.6 * pct
            if pct >= 90: vyzp.append(f"objem v top {round(100-pct)} % dodávateľov")
        zm = v.get("obrat_zmena_pct")
        if zm is not None and abs(zm) >= 30:
            vyz += min(25, abs(zm) / 4)
            vyzp.append(f"obrat {'rastie' if zm>0 else 'klesá'} o {abs(round(zm))} %")
        kon = v.get("top_objednavatel_podiel")
        if kon is not None and kon >= 60:
            vyz += 12; vyzp.append(f"{round(kon)} % objemu od jedného objednávateľa (koncentrácia)")
        if (v.get("crz_objem_eur") or 0) >= 5_000_000:
            vyzp.append(f"objem {round(v['crz_objem_eur']):,} €".replace(",", " "))
        # --- os RIZIKO (z finančných signálov) ---
        riz = 0.0; rizp = []
        for s in (f.get("signaly") or []):
            ind = s.get("indikator")
            riz += RISK_W.get(ind, 10)
            rizp.append({"indikator": ind, "preco": s.get("preco"), "obmedzenie": s.get("obmedzenie")})
        leads[k] = {"nazov": f.get("nazov"), "ico": f.get("ico"),
                    "vyznam_skore": _clamp(vyz), "_vyzp": vyzp,
                    "riziko_skore": _clamp(riz), "_rizp": rizp,
                    "crz_objem_eur": v.get("crz_objem_eur")}

    # augment riziko z ďalších zdrojov (flags)
    def add_flags(rows, name_field, flags_field, ico_field=None):
        for r in rows or []:
            k = key(r.get(ico_field) if ico_field else None, r.get(name_field))
            L = leads.get(k)
            if not L:
                L = leads[k] = {"nazov": r.get(name_field), "ico": r.get(ico_field) if ico_field else None,
                                "vyznam_skore": 0, "_vyzp": [], "riziko_skore": 0, "_rizp": [], "crz_objem_eur": None}
            for fl in (r.get(flags_field) or []):
                L["riziko_skore"] = _clamp(L["riziko_skore"] + RISK_W.get(fl, 10))
                L["_rizp"].append({"indikator": fl, "preco": "príznak z " + flags_field})

    if own: add_flags(own.get("rows"), "subjekt", "flags", "ico")
    if risk:
        for it in (risk.get("items") or []):
            k = key(it.get("ico"), it.get("dod"))
            L = leads.get(k)
            if not L:
                L = leads[k] = {"nazov": it.get("dod"), "ico": it.get("ico"), "vyznam_skore": 0,
                                "_vyzp": [], "riziko_skore": 0, "_rizp": [], "crz_objem_eur": None}
            for fl in (it.get("flags") or []):
                L["riziko_skore"] = _clamp(L["riziko_skore"] + RISK_W.get(fl, 8))
                L["_rizp"].append({"indikator": fl, "preco": "rizikový príznak (score)"})
    if kontrola:
        for l in (kontrola.get("links") or []):
            k = key(None, l.get("subjekt"))
            L = leads.get(k)
            if not L:
                L = leads[k] = {"nazov": l.get("subjekt"), "ico": None, "vyznam_skore": 0,
                                "_vyzp": [], "riziko_skore": 0, "_rizp": [], "crz_objem_eur": None}
            L["riziko_skore"] = _clamp(L["riziko_skore"] + (20 if l.get("opakovana_kontrola") else 14))
            L["_rizp"].append({"indikator": "NKÚ-KONTROLA×VÝDAVKY",
                               "preco": f"pod kontrolou NKÚ a míňa ({round(l.get('suma_spolu') or 0)} €)"})

    out = []
    for L in leads.values():
        vyz, riz = L["vyznam_skore"], L["riziko_skore"]
        if riz >= 30 and vyz >= 50: typ = "prioritné preverenie (významné + rizikové)"
        elif riz >= 30: typ = "na preverenie"
        elif vyz >= 50: typ = "ekonomická téma (významné, bez podozrenia)"
        elif riz > 0: typ = "sledovať"
        else: typ = "bežné"
        preco = {"vyznamnost": L.pop("_vyzp"), "riziko": L.pop("_rizp")}
        L.update({"typ_temy": typ, "preco": preco,
                  "poznamka": "Dve osi oddelene; riziko = proxy na preverenie, nie dôkaz. Významnosť ≠ podozrenie."})
        out.append(L)
    # rebríček: najprv prioritné, potom podľa max(osi)
    out.sort(key=lambda L: (L["typ_temy"].startswith("prioritné"), max(L["vyznam_skore"], L["riziko_skore"]),
                            L.get("crz_objem_eur") or 0), reverse=True)
    return {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "pocet": len(out),
            "osi": "vyznam_skore (ekonomická významnosť) a riziko_skore (proxy na preverenie) sú NEZÁVISLÉ",
            "leady": out}

def _selftest():
    fin = {"firmy": [
        {"ico": "111", "nazov": "VelkáFirma a.s.", "vyznam": {"crz_percentil": 97, "obrat_zmena_pct": 5,
            "top_objednavatel_podiel": 20, "crz_objem_eur": 40_000_000}, "signaly": []},
        {"ico": "222", "nazov": "MladáThin s.r.o.", "vyznam": {"crz_percentil": 55, "obrat_zmena_pct": 180,
            "top_objednavatel_podiel": 90, "crz_objem_eur": 8_000_000},
            "signaly": [{"indikator": "SK-FIN-YOUNGWIN", "preco": "vznik 2023, zákazka 2024", "obmedzenie": "vek nič nedokazuje"},
                        {"indikator": "SK-FIN-THINCAP", "preco": "aktíva nízke", "obmedzenie": "nie schránka automaticky"}]},
    ]}
    r = compute(fin)
    by = {L["ico"]: L for L in r["leady"]}
    A, B = by["111"], by["222"]
    print("VelkáFirma:", A["typ_temy"], "| vyznam", A["vyznam_skore"], "riziko", A["riziko_skore"])
    print("MladáThin :", B["typ_temy"], "| vyznam", B["vyznam_skore"], "riziko", B["riziko_skore"])
    ok = True
    if not A["typ_temy"].startswith("ekonomická"): ok = False; print("  !! A má byť ekon. téma (významné, bez rizika)")
    if A["riziko_skore"] != 0: ok = False; print("  !! A nemá mať riziko")
    if B["riziko_skore"] <= 0: ok = False; print("  !! B má mať riziko")
    if not B["preco"]["riziko"]: ok = False
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    if argv[0] == "--selftest":
        return _selftest()
    d = argv[0]
    out = argv[1] if len(argv) > 1 else os.path.join(d, "radar.json")
    res = compute(_load(d, "financial.json"), _load(d, "risk_scored.json"),
                  _load(d, "ownership.json"), _load(d, "kontrolne_vydavky.json"))
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapísané: {out} | leadov {res['pocet']}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
