#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — RPVS klient (Register partnerov verejného sektora, OData v4).

Zdroj: https://rpvs.gov.sk/opendatav2/  (overené 2026-11-25, oficiálne, MS SR).
Umožňuje AUTOMATICKY overiť konečných užívateľov výhod (KÚV) dodávateľa podľa IČO —
nahrádza ručný preklik na RPVS a odomyká indikátory vlastníctva a konfliktu záujmov.

Entity (z $metadata):
  PartnerVerejnehoSektora: ObchodneMeno, Ico, Adresa, PlatnostOd/Do
  KonecnyUzivatelVyhod:    Meno, Priezvisko, JeVerejnyCinitel (bool!), StatnaPrislusnost, PlatnostDo
  VerejnyFunkcionar:       Meno, Priezvisko
  KvalifikovanyPodnet:     DatumZacatiaKonania... (niekto napadol priznané vlastníctvo)
  OverenieIdentifikacieKUV: Platny, DatumOverenia

Pozn.: nie každý dodávateľ je v RPVS (len partneri verejného sektora nad zákonné prahy).
"""
import json, time

BASE = "https://rpvs.gov.sk/opendatav2"

def _get(session, path, params, timeout=20):
    """GET s OData parametrami. session = requests.Session (v pipeline)."""
    r = session.get(f"{BASE}/{path}", params=params,
                    headers={"Accept": "application/json",
                             "User-Agent": "sk-monitor/0.1 (verejny zaujem; github.com/JDZReporting/sk-monitor)"},
                    timeout=timeout)
    r.raise_for_status()
    return r.json()

def lookup_by_ico(session, ico):
    """Vráti partnera RPVS podľa IČO aj s KÚV, verejnými funkcionármi a podnetmi.
    None ak sa nenašiel (subjekt nie je partner verejného sektora)."""
    ico = str(ico).strip()
    if not ico:
        return None
    params = {
        "$filter": f"PartneriVerejnehoSektora/any(p: p/Ico eq '{ico}')",
        "$expand": ("PartneriVerejnehoSektora,"
                    "KonecniUzivateliaVyhod($expand=StatnaPrislusnost),"
                    "VerejniFunkcionari,KvalifikovanePodnety,OverenieIdentifikacieKUV"),
        "$top": "1",
    }
    data = _get(session, "Partneri", params)
    vals = data.get("value", [])
    return vals[0] if vals else None

def _active(rec):
    """PlatnostDo == None znamená aktuálne platné."""
    return rec.get("PlatnostDo") in (None, "")

def derive_flags(partner):
    """Z RPVS partnera odvodí rizikové príznaky + dôkazy. partner = výstup lookup_by_ico."""
    flags, evidence = [], {}
    if not partner:
        return flags, evidence
    kuv = [k for k in partner.get("KonecniUzivateliaVyhod", []) if _active(k)]
    # 1) KÚV je verejný činiteľ -> konflikt záujmov
    pub = [f"{k.get('Meno','')} {k.get('Priezvisko','')}".strip()
           for k in kuv if k.get("JeVerejnyCinitel")]
    if pub:
        flags.append("SK-OWN-PUBOFFICIAL"); evidence["kuv_verejny_cinitel"] = pub
    # 2) KÚV so zahraničnou štátnou príslušnosťou
    foreign = []
    for k in kuv:
        st = (k.get("StatnaPrislusnost") or {}).get("Meno", "")
        if st and st.strip().lower() not in ("slovenská republika", "slovenska republika", "slovensko"):
            foreign.append(f"{k.get('Meno','')} {k.get('Priezvisko','')} ({st})".strip())
    if foreign:
        flags.append("SK-OWN-FOREIGN-KUV"); evidence["kuv_zahranicny"] = foreign
    # 3) Kvalifikovaný podnet -> priznané vlastníctvo bolo napadnuté
    podnety = partner.get("KvalifikovanePodnety", [])
    if podnety:
        flags.append("SK-OWN-CHALLENGED"); evidence["pocet_podnetov"] = len(podnety)
    # 4) Žiadny aktívny KÚV (netransparentné / možná medzera)
    if not kuv:
        flags.append("SK-OWN-NO-KUV")
    return flags, evidence

def kuv_key(partner):
    """Množina identit KÚV (na detekciu dvoch dodávateľov so spoločným vlastníkom)."""
    out = set()
    for k in (partner or {}).get("KonecniUzivateliaVyhod", []):
        if _active(k):
            dn = (k.get("DatumNarodenia") or "")[:10]
            out.add((k.get("Meno","").strip().lower(), k.get("Priezvisko","").strip().lower(), dn))
    return out

if __name__ == "__main__":
    import sys
    try:
        import requests
    except ImportError:
        print("requests nie je nainštalované (pipeline ho má)."); sys.exit(0)
    ico = sys.argv[1] if len(sys.argv) > 1 else None
    if not ico:
        print("Použitie: python rpvs.py <ICO>"); sys.exit(0)
    s = requests.Session()
    p = lookup_by_ico(s, ico)
    if not p:
        print(f"IČO {ico}: nie je partnerom verejného sektora (alebo nenájdené)."); sys.exit(0)
    pvs = (p.get("PartneriVerejnehoSektora") or [{}])[0]
    print("Partner:", pvs.get("ObchodneMeno") or f"{pvs.get('Meno','')} {pvs.get('Priezvisko','')}")
    flags, ev = derive_flags(p)
    print("Príznaky:", flags)
    print("Dôkaz:", json.dumps(ev, ensure_ascii=False))
