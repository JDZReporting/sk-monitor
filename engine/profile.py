#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — profil entity (firma/osoba): agreguje všetko, čo o subjekte vieme.
Zmluvy/zákazky, sumy, obstarávatelia, kategórie, vlastníci (RPVS), prepojenia, red-flagy.
SÚKROMNÉ (menuje subjekt) -> sk-monitor-intelligence. Použitie: python profile.py "<názov>"
"""
import json, sys, os, re, urllib.parse
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from score import parse_suma, parse_buyer
try:
    import rpvs
except Exception:
    rpvs = None

def norm_name(s):
    return re.sub(r"\s+", " ", re.sub(r"[.,]", " ", (s or "").lower())).strip()

def build_profile(store, subject, rpvs_lookup=None):
    items = store.get("items", [])
    key = norm_name(subject)
    mine = [it for it in items if norm_name(it.get("overit") or it.get("dod") or "") == key]
    contracts = []
    total = 0.0
    buyers = Counter(); cats = Counter()
    ico = ""; vznik = ""; krajina = ""
    for it in mine:
        v = parse_suma(it.get("suma")) or 0
        total += v
        b = parse_buyer(it.get("meta"))
        if b: buyers[b] += 1
        cats[it.get("category", "Ostatné")] += 1
        ico = ico or it.get("dod_ico", "")
        vznik = vznik or it.get("dod_vznik", "")
        krajina = krajina or it.get("dod_krajina", "")
        contracts.append({"date": it.get("date"), "suma": v, "obstaravatel": b,
                          "kategoria": it.get("category"), "nazov": it.get("title", "")[:90],
                          "url": it.get("url", "")})
    contracts.sort(key=lambda c: c["suma"], reverse=True)
    prof = {"subjekt": subject, "ico": ico, "vznik": vznik, "krajina": krajina,
            "pocet_kontraktov": len(mine), "suma_spolu": round(total),
            "obstaravatelia": buyers.most_common(8), "kategorie": cats.most_common(),
            "kontrakty": contracts[:25]}
    # RPVS vlastníci + prepojenia
    if ico and rpvs_lookup and rpvs:
        try:
            partner = rpvs_lookup(ico)
        except Exception:
            partner = None
        if partner:
            flags, ev = rpvs.derive_flags(partner)
            prof["rpvs_priznaky"] = flags
            prof["rpvs_dokaz"] = ev
            prof["konecni_uzivatelia_vyhod"] = [
                f"{k.get('Meno','')} {k.get('Priezvisko','')}".strip() +
                (" [verejný činiteľ]" if k.get("JeVerejnyCinitel") else "")
                for k in partner.get("KonecniUzivateliaVyhod", []) if not k.get("PlatnostDo")]
    return prof

def render_md(p):
    L = [f"# Profil: {p['subjekt']}\n"]
    L.append(f"IČO: {p.get('ico') or '—'} · vznik: {p.get('vznik') or '—'} · krajina: {p.get('krajina') or 'SK'}  ")
    L.append(f"**Kontraktov: {p['pocet_kontraktov']} · spolu: {p['suma_spolu']:,} €**\n".replace(",", " "))
    if p.get("konecni_uzivatelia_vyhod"):
        L.append("**Koneční užívatelia výhod (RPVS):** " + ", ".join(p["konecni_uzivatelia_vyhod"]))
    if p.get("rpvs_priznaky"):
        L.append("**RPVS príznaky:** " + ", ".join(p["rpvs_priznaky"]))
    if p.get("obstaravatelia"):
        L.append("\n**Hlavní obstarávatelia:** " + ", ".join(f"{b} ({n})" for b, n in p["obstaravatelia"]))
    if p.get("kategorie"):
        L.append("**Kategórie:** " + ", ".join(f"{c} ({n})" for c, n in p["kategorie"]))
    q = urllib.parse.quote(p["subjekt"])
    L.append(f"\n**Preveriť:** [ORSR](https://www.orsr.sk/hladaj_subjekt.asp?OBMENO={q}&PF=0&SID=0&S=on&R=on) · [FinStat](https://finstat.sk/hladaj?q={q}) · [RPVS](https://rpvs.gov.sk/rpvs)")
    L.append("\n## Najväčšie kontrakty")
    for c in p["kontrakty"][:12]:
        L.append(f"- {c['suma']:,} € · {c.get('obstaravatel') or '—'} · {c.get('date')} · {c.get('nazov')}  ".replace(",", " ") + (f"[zdroj]({c['url']})" if c.get("url") else ""))
    return "\n".join(L)

def main():
    src = os.environ.get("STORE", "../data/store.json")
    subject = sys.argv[1] if len(sys.argv) > 1 else None
    if not subject:
        print("Použitie: python profile.py \"<názov firmy/osoby>\""); return
    store = json.load(open(src, encoding="utf-8"))
    rl = None
    try:
        import requests
        if rpvs:
            se = requests.Session(); rl = lambda i: rpvs.lookup_by_ico(se, i)
    except ImportError:
        pass
    if subject == "--batch":
        rs = json.load(open(os.environ.get("SCORED", "findings/risk_scored.json"), encoding="utf-8"))
        os.makedirs("findings/profiles", exist_ok=True)
        seen = set(); made = 0
        for it in rs.get("items", []):
            dod = it.get("dod")
            if not dod or norm_name(dod) in seen: continue
            seen.add(norm_name(dod))
            prof = build_profile(store, dod, rl)
            fn = (re.sub(r"[^\w-]+", "_", norm_name(dod))[:50] or "x")
            open(f"findings/profiles/{fn}.md", "w", encoding="utf-8").write(render_md(prof))
            made += 1
            if made >= 15: break
        print(f"profily vygenerované: {made}")
        return
    p = build_profile(store, subject, rl)
    print(render_md(p))

if __name__ == "__main__":
    main()
