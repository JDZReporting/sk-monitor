#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — SCORING v2 (viacrozmerné, vysvetliteľné, reprodukovateľné).

NIE je to jedno číslo „pravdepodobnosť korupcie". Žiadny vedecky validovaný model korupcie
nemáme, preto skóre NEPREDSTIERA pravdepodobnosť protiprávneho konania. Namiesto toho počíta
PÄŤ SAMOSTATNÝCH dimenzií a „investigatívnu prioritu" ako TRANSPARENTNÝ triage signál
(kam sa pozrieť najskôr pri ľudskom overovaní), nie ako verdikt.

Dimenzie (0–100, oddelené):
  1. vyznamnost        — rozsah verejných prostriedkov + verejný záujem kategórie
  2. stat_neobvyklost  — ako veľmi sa vymyká norme (percentil sumy v kategórii, koncentrácia)
  3. sila_dokazov      — ako „tvrdé" sú signály (dokumentárny fakt vs odvodené; nezávislé klastre)
  4. kvalita_dat       — úplnosť dát (IČO, RPVS, suma, dátum, RPO) → nízka = nižšia istota
  5. investigativna_priorita — DOKUMENTOVANÁ kombinácia 1–3 tlmená kvalitou dát (len triage)

Zásady:
  - Korelované príznaky sa zoskupujú do KLASTROV a počítajú RAZ (žiadne dvojité započítanie).
  - Vysoká suma, zahraničné sídlo, PEP ani vlastníctvo verejným činiteľom SAMÉ OSEBE nie sú
    dôkaz korupčného rizika — vstupujú do dimenzií s dokumentovanou váhou a vysvetlením.
  - Každý výsledok je vysvetliteľný (zoznam príspevkov) a reprodukovateľný (pevné vzorce, verzia).
  - Sektorové výnimky sa aplikujú per indikátor (nie plošné vylúčenie skupín dodávateľov).

Vstup: store.json (+ voliteľne findings/risk_scored.json a findings/ownership.json).
Výstup: findings/scorecards.{json,md} (SÚKROMNE, sentinel).
"""
import json, sys, os, re, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from score import parse_suma as _parse_suma
except Exception:
    def _parse_suma(x):
        if not x: return 0.0
        t = re.sub(r"[^\d,.]", "", str(x)).replace(" ", "")
        t = t.replace(",", ".") if (t.count(",") == 1 and t.count(".") == 0) else t.replace(",", "")
        try: return float(t)
        except Exception: return 0.0

def parse_suma(x):
    """Bezpečná suma: None/chyba -> 0.0 (score.parse_suma môže vrátiť None)."""
    v = _parse_suma(x)
    return v if isinstance(v, (int, float)) else 0.0

SENTINEL = "SKMON-PRIVATE-DO-NOT-PUBLISH"
VERZIA = "2.0"
TODAY = datetime.date.today()

# ---- klastre korelovaných príznakov (započítané RAZ) ----
KLASTRE = {
    "nova_zmenena_firma": {"SK-SUP-NEW", "SK-OWN-NAMECHANGE", "SK-OWN-SEATCHANGE"},
    "koncentracia":       {"SK-BUYER-CONC", "SK-MARKET-HHI"},
    "zahranicie":         {"SK-SUP-FOREIGN", "SK-OWN-FOREIGN-KUV"},
    "vlastnik_cinitel":   {"SK-OWN-PUBOFFICIAL"},
    "netransparentne":    {"SK-OWN-NO-KUV", "SK-OWN-CHALLENGED"},
}
# „tvrdosť" dôkazu klastra (dokumentárny fakt vs odvodené); 0–1
KLASTER_SILA = {
    "vlastnik_cinitel": 1.0,   # RPVS príznak verejného činiteľa = tvrdý register. fakt
    "koncentracia":     0.7,   # štrukturálny fakt z CRZ/ÚVO
    "nova_zmenena_firma": 0.7, # dokumentárny fakt z RPO (zmena názvu/sídla, vznik)
    "netransparentne":  0.6,   # RPVS podnet / chýbajúci KÚV
    "zahranicie":       0.4,   # kontextový signál, veľa legitímnych prípadov
}
# verejný záujem kategórie (modifikátor významnosti), 0.8–1.2
KAT_ZAUJEM = {
    "Zdravotníctvo": 1.15, "Doprava a výstavba": 1.1, "Obrana": 1.15,
    "Štát a štátne podniky": 1.05, "Samospráva": 1.0, "Vnútro a bezpečnosť": 1.1,
}

def _clip(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))

def _klastre_z_flagov(flags):
    fs = set(flags or [])
    return [k for k, members in KLASTRE.items() if fs & members]

def percentily_kategorii(items):
    """Pre každú kategóriu zoradené sumy zmlúv (na percentil)."""
    from collections import defaultdict
    cat = defaultdict(list)
    for it in items:
        if it.get("source") in ("zmluvy", "uvo"):
            v = parse_suma(it.get("suma"))
            if v > 0:
                cat[it.get("category", "Ostatné")].append(v)
    for k in cat:
        cat[k].sort()
    return cat

def percentil(sorted_vals, v):
    if not sorted_vals:
        return None
    import bisect
    i = bisect.bisect_right(sorted_vals, v)
    return 100.0 * i / len(sorted_vals)

def dim_vyznamnost(suma, kategoria):
    """Rozsah verejných prostriedkov (log škála, €50M ≈ 100) × verejný záujem kategórie."""
    if suma <= 0:
        return 0.0, "suma neznáma"
    base = 100.0 * math.log10(suma + 1) / math.log10(50_000_000)
    mod = KAT_ZAUJEM.get(kategoria, 1.0)
    return _clip(base * mod), f"suma {suma:,.0f} € (log škála) × záujem kat. {mod}".replace(",", " ")

def dim_neobvyklost(suma, kategoria, klastre, perc):
    """Percentil sumy v kategórii + štrukturálna koncentrácia."""
    body, vysv = 0.0, []
    p = percentil(perc.get(kategoria, []), suma) if suma > 0 else None
    if p is not None:
        body = max(body, p)  # P95 → 95 bodov
        vysv.append(f"suma v ~P{p:.0f} kategórie")
    if "koncentracia" in klastre:
        body = max(body, 70.0); vysv.append("vysoká koncentrácia dodávateľ↔obstarávateľ")
    return _clip(body), "; ".join(vysv) or "bez porovnania"

def dim_sila_dokazov(klastre):
    """Sila = najtvrdší klaster + bonus za NEZÁVISLÉ klastre (nie za počet korelovaných príznakov)."""
    if not klastre:
        return 0.0, "žiadny príznak"
    sily = sorted((KLASTER_SILA.get(k, 0.3) for k in klastre), reverse=True)
    base = sily[0]
    # nezávislé ďalšie klastre pridávajú klesajúco (korelované príznaky v jednom klastri sa už nerátajú)
    for i, s in enumerate(sily[1:], start=1):
        base += s * (0.5 ** i)
    return _clip(base * 100.0 / 1.8), f"{len(klastre)} nezávislých klastrov; najtvrdší={sily[0]:.1f}"

def dim_kvalita_dat(it, ownership):
    """Úplnosť: IČO, RPVS (partner VS), suma, dátum, RPO vznik/krajina."""
    body, chyba = 0, []
    checks = [("suma", bool(parse_suma(it.get("suma")))),
              ("dátum", bool(it.get("date"))),
              ("IČO", bool(it.get("dod_ico") or (ownership or {}).get("ico"))),
              ("RPO vznik/krajina", bool(it.get("dod_vznik") or (ownership or {}).get("vznik"))),
              ("RPVS (partner VS)", bool((ownership or {}).get("je_partner_vs")))]
    for nazov, ok in checks:
        if ok: body += 20
        else: chyba.append(nazov)
    return float(body), ("úplné" if not chyba else "chýba: " + ", ".join(chyba))

def investigativna_priorita(v, n, s, kval):
    """TRANSPARENTNÁ kombinácia (len triage, NIE pravdepodobnosť korupcie).
    priorita = (0.35*významnosť + 0.35*neobvyklosť + 0.30*sila) × tlmenie_kvalitou."""
    jadro = 0.35 * v + 0.35 * n + 0.30 * s
    tlmenie = 0.6 + 0.4 * (kval / 100.0)   # nízka kvalita dát znižuje prioritu (nie istotu konania)
    return _clip(jadro * tlmenie)

def scorecard(it, flags, ownership, perc):
    suma = parse_suma(it.get("suma"))
    kat = it.get("category", "Ostatné")
    klastre = _klastre_z_flagov(flags)
    v, v_e = dim_vyznamnost(suma, kat)
    n, n_e = dim_neobvyklost(suma, kat, klastre, perc)
    s, s_e = dim_sila_dokazov(klastre)
    q, q_e = dim_kvalita_dat(it, ownership)
    p = investigativna_priorita(v, n, s, q)
    return {
        "subjekt": it.get("overit") or it.get("dod"), "kategoria": kat,
        "suma": suma, "date": it.get("date"), "url": it.get("url", ""),
        "flags": sorted(set(flags or [])), "klastre": klastre,
        "dimenzie": {"vyznamnost": round(v, 1), "stat_neobvyklost": round(n, 1),
                     "sila_dokazov": round(s, 1), "kvalita_dat": round(q, 1),
                     "investigativna_priorita": round(p, 1)},
        "vysvetlenie": {"vyznamnost": v_e, "stat_neobvyklost": n_e, "sila_dokazov": s_e, "kvalita_dat": q_e},
    }

def load_flags(findings_dir):
    """Zluč príznaky per položka/subjekt z risk_scored.json a ownership.json (ak sú)."""
    by_id, by_subject = {}, {}
    rs = os.path.join(findings_dir, "risk_scored.json")
    if os.path.exists(rs):
        try:
            d = json.load(open(rs, encoding="utf-8"))
            for r in (d.get("results") or d if isinstance(d, list) else d.get("results", [])):
                if isinstance(r, dict) and r.get("id"):
                    by_id[r["id"]] = r.get("flags", [])
        except Exception:
            pass
    ow = os.path.join(findings_dir, "ownership.json")
    own_map = {}
    if os.path.exists(ow):
        try:
            d = json.load(open(ow, encoding="utf-8"))
            for r in d.get("rows", []):
                key = (r.get("subjekt") or "").strip().lower()
                by_subject[key] = r.get("flags", [])
                own_map[key] = r
        except Exception:
            pass
    return by_id, by_subject, own_map

def run(store, findings_dir="findings"):
    items = store.get("items", [])
    perc = percentily_kategorii(items)
    by_id, by_subject, own_map = load_flags(findings_dir)
    cards = []
    for it in items:
        if it.get("source") not in ("zmluvy", "uvo"):
            continue
        subj = (it.get("overit") or it.get("dod") or "").strip().lower()
        flags = list(by_id.get(it.get("id"), [])) + list(by_subject.get(subj, []))
        if not flags:
            continue
        cards.append(scorecard(it, flags, own_map.get(subj), perc))
    # agreguj na subjekt (max priorita za subjekt), aby sme neduplikovali
    best = {}
    for c in cards:
        k = (c["subjekt"] or "").lower()
        if k not in best or c["dimenzie"]["investigativna_priorita"] > best[k]["dimenzie"]["investigativna_priorita"]:
            best[k] = c
    out = sorted(best.values(), key=lambda c: c["dimenzie"]["investigativna_priorita"], reverse=True)
    return out

def render_md(cards):
    L = ["<!-- " + SENTINEL + " -->", f"# Scoring v2 — scorecards (verzia {VERZIA})", "",
         "**Investigatívna priorita NIE je pravdepodobnosť korupcie.** Je to transparentný triage",
         "signál (kam sa pozrieť najskôr). Vysoká suma / zahraničie / PEP / vlastník-činiteľ samé osebe",
         "nie sú dôkaz. Každé skóre je vysvetliteľné a reprodukovateľné. Pred verejným tvrdením ľudské overenie.", ""]
    L.append(f"**Subjektov so skóre: {len(cards)}**\n")
    for c in cards[:40]:
        d = c["dimenzie"]
        L.append(f"## {c['subjekt']}  ·  priorita {d['investigativna_priorita']}/100")
        L.append(f"- Dimenzie — významnosť {d['vyznamnost']} · neobvyklosť {d['stat_neobvyklost']} · "
                 f"sila dôkazov {d['sila_dokazov']} · kvalita dát {d['kvalita_dat']}")
        L.append(f"- Suma: {c['suma']:,.0f} € · kat.: {c['kategoria']} · klastre: {', '.join(c['klastre']) or '—'}".replace(",", " "))
        L.append(f"- Príznaky: {', '.join(c['flags'])}")
        L.append(f"- Prečo: významnosť = {c['vysvetlenie']['vyznamnost']}; neobvyklosť = {c['vysvetlenie']['stat_neobvyklost']}; "
                 f"sila = {c['vysvetlenie']['sila_dokazov']}; kvalita = {c['vysvetlenie']['kvalita_dat']}")
        L.append("")
    return "\n".join(L)

def main():
    store_path = sys.argv[1] if len(sys.argv) > 1 else "data/store.json"
    findings = sys.argv[2] if len(sys.argv) > 2 else "findings"
    store = json.load(open(store_path, encoding="utf-8"))
    cards = run(store, findings)
    os.makedirs(findings, exist_ok=True)
    json.dump({SENTINEL: True, "verzia": VERZIA, "generated": TODAY.isoformat(), "pocet": len(cards), "cards": cards},
              open(os.path.join(findings, "scorecards.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(findings, "scorecards.md"), "w", encoding="utf-8").write(render_md(cards))
    print(f"score2.py: {len(cards)} scorecardov (viacrozmerné skóre)")

if __name__ == "__main__":
    main()
