#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — OWNERSHIP INTELLIGENCE.
Pre top súkromných dodávateľov (podľa objemu verejných zmlúv) automaticky spojí:
  RPO (IČO, história názvu a sídla, vznik, krajina) + RPVS (koneční užívatelia výhod,
  verejný činiteľ, podnety) → profil s rizikovými príznakmi.
Beží v privátnom Action (sieť dostupná). Výstup SÚKROMNE (sentinel) na ľudské posúdenie.

Príznaky:
  SK-OWN-PUBOFFICIAL  — KÚV je verejný činiteľ (RPVS JeVerejnyCinitel)
  SK-OWN-FOREIGN-KUV  — KÚV so zahraničnou štátnou príslušnosťou (RPVS)
  SK-OWN-CHALLENGED   — priznané vlastníctvo napadnuté kvalifikovaným podnetom (RPVS)
  SK-OWN-NO-KUV       — žiadny aktívny KÚV (netransparentné)
  SK-SUP-NEW          — firma mladšia ako 1 rok v čase najnovšej zmluvy (RPO)
  SK-OWN-NAMECHANGE   — zmena obchodného mena za posledných 12 mes. (RPO)
  SK-OWN-SEATCHANGE   — zmena sídla za posledných 12 mes. (RPO)

Použitie: python engine/ownership.py [store.json] [out_dir] [max_firiem]
"""
import json, sys, os, re, time, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpvs
try:
    from score import parse_suma, parse_buyer, is_state_supplier
except Exception:
    def parse_suma(x):
        if not x: return 0.0
        t = re.sub(r"[^\d,.]", "", str(x)).replace(" ", "")
        t = t.replace(",", ".") if (t.count(",") == 1 and t.count(".") == 0) else t.replace(",", "")
        try: return float(t)
        except Exception: return 0.0
    def parse_buyer(meta):
        m = re.search(r"(?:Objednávate[ľl]|Obstarávate[ľl]):\s*([^·]+)", meta or "")
        return (m.group(1).strip() if m else "")
    def is_state_supplier(n):
        ln = (n or "").lower()
        return any(x in ln for x in ("ministerstvo", "štátny", "statny", "úrad", "urad", "slovenskej republiky",
                   "samosprávny kraj", "mesto ", "obec ", "železnic", "zeleznic", "národná", "narodna"))

SENTINEL = "SKMON-PRIVATE-DO-NOT-PUBLISH"
RPO = "https://api.statistics.sk/rpo/v1/search"
UA = {"User-Agent": "sk-monitor/0.1 (verejny zaujem; github.com/JDZReporting/sk-monitor)"}
TODAY = datetime.date.today()

def _d(s):
    try: return datetime.date.fromisoformat((s or "")[:10])
    except Exception: return None

def _recent(dstr, months=12):
    d = _d(dstr)
    return bool(d and (TODAY - d).days <= months * 31)

def _rpo_query(session, name):
    r = session.get(RPO, params={"fullName": name}, headers=UA, timeout=25)
    return r.status_code, r.json()

def rpo_full(session, name):
    """RPO: {ico, vznik, krajina, mena[], sidla[], current_name} pre jednoznačnú aktívnu firmu; {} inak.
    Skúsi plný názov, potom očistený variant (bez právnej formy) — RPO fullName je prísny."""
    data, status = {}, None
    variants = [name, re.sub(r",?\s*(k\.?\s?s\.?|a\.?\s?s\.?|s\.?\s?r\.?\s?o\.?|spol\.?\s*s\s*r\.?\s?o\.?)\s*$", "", name, flags=re.I).strip()]
    for v in [x for i, x in enumerate(variants) if x and x not in variants[:i]]:
        try:
            status, data = _rpo_query(session, v)
        except Exception as e:
            data = {"_err": str(e)[:60]}; continue
        if data.get("results"):
            break
        time.sleep(0.2)
    if not isinstance(data, dict) or not data.get("results"):
        return {"_status": status} if status else (data if data.get("_err") else {})
    for e in data.get("results", []):
        if e.get("termination"):
            continue
        names = e.get("fullNames", [])
        cur = next((n for n in names if not n.get("validTo")), (names[-1] if names else None))
        out = {"ico": "", "vznik": e.get("establishment", "") or "",
               "current_name": (cur or {}).get("value", ""),
               "mena": [{"v": n.get("value", ""), "od": (n.get("validFrom") or "")[:10], "do": (n.get("validTo") or "")[:10]} for n in names],
               "sidla": []}
        ids = e.get("identifiers", [])
        ident = next((i for i in ids if not i.get("validTo")), (ids[0] if ids else None))
        if ident and ident.get("value"):
            out["ico"] = re.sub(r"\s", "", str(ident["value"]))
        addrs = e.get("addresses", [])
        for a in addrs:
            muni = (a.get("municipality") or {}).get("value", "")
            country = (a.get("country") or {}).get("value", "")
            out["sidla"].append({"obec": muni, "krajina": country, "od": (a.get("validFrom") or "")[:10], "do": (a.get("validTo") or "")[:10]})
        cur_addr = next((a for a in out["sidla"] if not a["do"]), (out["sidla"][0] if out["sidla"] else {}))
        out["krajina"] = cur_addr.get("krajina", "")
        return out
    return {}

def rpo_flags(rpo, newest_contract_date):
    flags, ev = [], {}
    if not rpo:
        return flags, ev
    vz = _d(rpo.get("vznik"))
    cd = _d(newest_contract_date) or TODAY
    if vz and (cd - vz).days < 365:
        flags.append("SK-SUP-NEW"); ev["vznik"] = rpo.get("vznik")
    # zmena mena za 12 mes (viac mien a najnovšia zmena nedávno)
    mena = rpo.get("mena", [])
    if len(mena) >= 2 and any(_recent(m["od"]) for m in mena if m["od"]):
        flags.append("SK-OWN-NAMECHANGE"); ev["mena"] = [m["v"] for m in mena][-3:]
    sidla = rpo.get("sidla", [])
    if len(sidla) >= 2 and any(_recent(s["od"]) for s in sidla if s["od"]):
        flags.append("SK-OWN-SEATCHANGE"); ev["sidla"] = [s["obec"] for s in sidla][-3:]
    return flags, ev

def run(store, max_firiem=30, sleep=0.35):
    try:
        import requests
    except ImportError:
        print("requests nie je nainštalované."); return []
    items = store.get("items", [])
    agg = {}
    for it in items:
        if it.get("source") != "zmluvy":
            continue
        dod = it.get("dod") or it.get("overit")
        if not dod or is_state_supplier(dod):
            continue
        a = agg.setdefault(dod, {"suma": 0.0, "n": 0, "newest": "", "buyers": set(), "urls": []})
        a["suma"] += parse_suma(it.get("suma")); a["n"] += 1
        if (it.get("date") or "") > a["newest"]:
            a["newest"] = it.get("date") or ""
        b = parse_buyer(it.get("meta"))
        if b: a["buyers"].add(b)
        if it.get("url"): a["urls"].append(it["url"])
    ranked = sorted(agg.items(), key=lambda x: x[1]["suma"], reverse=True)[:max_firiem]
    sess = requests.Session()
    out = []
    for name, a in ranked:
        rpo = rpo_full(sess, name); time.sleep(sleep)
        ico = rpo.get("ico", "")
        partner = None
        if ico:
            try: partner = rpvs.lookup_by_ico(sess, ico)
            except Exception: partner = None
            time.sleep(sleep)
        rflags, rev = rpo_flags(rpo, a["newest"])
        oflags, oev = rpvs.derive_flags(partner) if partner else ([], {})
        kuv = []
        if partner:
            for k in partner.get("KonecniUzivateliaVyhod", []):
                if rpvs._active(k):
                    kuv.append({"meno": f"{k.get('Meno','')} {k.get('Priezvisko','')}".strip(),
                                "verejny_cinitel": bool(k.get("JeVerejnyCinitel")),
                                "od": (k.get("PlatnostOd") or "")[:10]})
        flags = rflags + oflags
        print(f"DBG {name[:36]:36} | ico={ico or '-':>9} | pvs={'A' if partner else '-'} | rpo_status={rpo.get('_status', rpo.get('_err',''))} | {flags}")
        out.append({"subjekt": name, "ico": ico, "suma_zmluv": round(a["suma"], 2),
                    "pocet_zmluv": a["n"], "najnovsia_zmluva": a["newest"],
                    "krajina": rpo.get("krajina", ""), "vznik": rpo.get("vznik", ""),
                    "je_partner_vs": bool(partner), "kuv": kuv,
                    "flags": flags, "evidence": {**rev, **oev},
                    "zdroj_zmluvy": (a["urls"][:1] or [""])[0]})
    # najprv tie s príznakmi, potom podľa sumy
    out.sort(key=lambda x: (len(x["flags"]) > 0, len(x["flags"]), x["suma_zmluv"]), reverse=True)
    return out

def render_md(rows):
    L = ["<!-- " + SENTINEL + " -->", "# Ownership Intelligence — vlastnícke príznaky top dodávateľov", "",
         "Automaticky z RPO + RPVS. Príznaky sú SIGNÁLY, nie dôkazy. Zhoda mena ≠ totožnosť.",
         "Pred verejným tvrdením nutné ľudské overenie.", ""]
    flagged = [r for r in rows if r["flags"]]
    L.append(f"**Dodávateľov preverených: {len(rows)} · s príznakmi: {len(flagged)}**\n")
    for r in rows:
        if not r["flags"]:
            continue
        L.append(f"## {r['subjekt']}  ·  {r['suma_zmluv']:,.0f} €".replace(",", " "))
        L.append(f"- IČO: {r['ico'] or '—'} · vznik: {r['vznik'] or '—'} · krajina: {r['krajina'] or '—'} · partner VS: {'áno' if r['je_partner_vs'] else 'nie'}")
        L.append(f"- **Príznaky:** {', '.join(r['flags'])}")
        if r["kuv"]:
            ku = "; ".join(f"{k['meno']}{' ⚠️VČ' if k['verejny_cinitel'] else ''}" for k in r["kuv"])
            L.append(f"- Koneční užívatelia výhod: {ku}")
        if r["evidence"]:
            L.append(f"- Dôkaz: {json.dumps(r['evidence'], ensure_ascii=False)}")
        L.append("")
    return "\n".join(L)

def main():
    store_path = sys.argv[1] if len(sys.argv) > 1 else "data/store.json"
    outdir = sys.argv[2] if len(sys.argv) > 2 else "findings"
    maxf = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    store = json.load(open(store_path, encoding="utf-8"))
    rows = run(store, max_firiem=maxf)
    os.makedirs(outdir, exist_ok=True)
    json.dump({SENTINEL: True, "generated": TODAY.isoformat(), "pocet": len(rows), "rows": rows},
              open(os.path.join(outdir, "ownership.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(os.path.join(outdir, "ownership.md"), "w", encoding="utf-8").write(render_md(rows))
    print(f"ownership.py: preverených {len(rows)}, s príznakmi {sum(1 for r in rows if r['flags'])}")

if __name__ == "__main__":
    main()
