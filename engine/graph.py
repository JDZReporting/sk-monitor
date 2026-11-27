#!/usr/bin/env python3
# SKMON-PUBLIC (kód). Výstup (subjektový graf) -> súkromná vrstva.
"""
engine/graph.py — graf vzťahov: firma ↔ objednávateľ ↔ konečný užívateľ výhod (KÚV).

Uzly: firmy (dodávatelia), objednávatelia, osoby (KÚV). Hrany:
  - "dodáva"           firma → objednávateľ (CRZ, váha = objem)
  - "KÚV"              osoba → firma (RPVS, z ownership.json)
  - "spoločný_vlastník" firma — firma (odvodené: zdieľajú meno KÚV)
Čistý Python (bez NetworkX). Výstup je konzumovateľný pre vizualizáciu (Cytoscape.js) aj terminál.

METODIKA: zhoda MENA KÚV != istá totožnosť osoby (rovnaké meno môžu mať dvaja ľudia). Spoločného
vlastníka označujeme ako „podľa mena — overiť"; investigatívnu hodnotu má najmä keď firmy vystupujú
ako formálne nezávislí konkurenti v tom istom obstarávaní (to treba doplniť z ÚVO/TED).

Použitie:
  python3 engine/graph.py --selftest
  python3 engine/graph.py <findings_dir> <store.json> [out.json]
"""
import json, sys, os, re, unicodedata
from collections import defaultdict

def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()

def parse_buyer(meta):
    m = re.search(r"(?:Objednávate[ľl]|Obstarávate[ľl]):\s*([^·→]+)", meta or "")
    return (m.group(1).strip() if m else None)

def parse_suma(x):
    if x is None: return 0.0
    t = re.sub(r"[^\d,.]", "", str(x)).replace(" ", "")
    if not t: return 0.0
    t = t.replace(",", ".") if (t.count(",") == 1 and t.count(".") == 0) else t.replace(",", "")
    try: return float(t)
    except Exception: return 0.0

def build(ownership, store):
    nodes = {}  # id -> {id, typ, label, ...}
    edges = []
    def node(nid, typ, label, **extra):
        if nid not in nodes: nodes[nid] = {"id": nid, "typ": typ, "label": label, **extra}
        return nid

    # (1) KÚV osoba → firma (z ownership.json)
    osoba_firmy = defaultdict(set)   # norm(meno) -> {firma_id}
    osoba_label = {}
    for r in (ownership or {}).get("rows", []):
        fid = "firma:" + (str(r.get("ico")) if r.get("ico") else _norm(r.get("subjekt")))
        node(fid, "firma", r.get("subjekt"), ico=r.get("ico"), je_partner_vs=r.get("je_partner_vs"))
        for k in (r.get("kuv") or []):
            meno = k.get("meno")
            if not meno: continue
            pid = "osoba:" + _norm(meno); osoba_label[pid] = meno
            node(pid, "osoba", meno, verejny_cinitel=k.get("verejny_cinitel"))
            edges.append({"zdroj": pid, "ciel": fid, "typ": "KÚV", "od": k.get("od")})
            osoba_firmy[pid].add(fid)

    # (2) firma → objednávateľ (z CRZ store)
    dod_buyer = defaultdict(float)
    items = (store or {}).get("items", store if isinstance(store, list) else [])
    for it in items:
        if it.get("source") != "zmluvy": continue
        dod = it.get("dod") or it.get("overit");
        if not dod: continue
        fid = "firma:" + (str(it.get("dod_ico")) if it.get("dod_ico") else _norm(dod))
        node(fid, "firma", dod, ico=it.get("dod_ico"))
        buyer = parse_buyer(it.get("meta"))
        if not buyer: continue
        bid = "objednavatel:" + _norm(buyer)
        node(bid, "objednavatel", buyer)
        dod_buyer[(fid, bid)] += parse_suma(it.get("suma"))
    for (fid, bid), suma in dod_buyer.items():
        edges.append({"zdroj": fid, "ciel": bid, "typ": "dodáva", "vaha": round(suma)})

    # (3) spoloční vlastníci: osoba s ≥2 firmami -> hrana firma—firma
    spolocni = []
    for pid, firmy in osoba_firmy.items():
        if len(firmy) >= 2:
            fl = sorted(firmy)
            spolocni.append({"osoba": osoba_label.get(pid), "firmy": [nodes[f]["label"] for f in fl],
                             "pozn": "zhoda podľa MENA KÚV — overiť totožnosť; hodnota najmä pri súťaži v tom istom obstarávaní"})
            for a in range(len(fl)):
                for b in range(a+1, len(fl)):
                    edges.append({"zdroj": fl[a], "ciel": fl[b], "typ": "spoločný_vlastník", "osoba": osoba_label.get(pid)})

    # metriky: stupeň uzla
    deg = defaultdict(int)
    for e in edges: deg[e["zdroj"]] += 1; deg[e["ciel"]] += 1
    for nid, d in deg.items():
        if nid in nodes: nodes[nid]["stupen"] = d
    top_huby = sorted(({"label": nodes[n]["label"], "typ": nodes[n]["typ"], "stupen": d}
                       for n, d in deg.items() if n in nodes), key=lambda x: x["stupen"], reverse=True)[:15]

    return {"SKMON-PRIVATE-DO-NOT-PUBLISH": True,
            "metodika": "zhoda mena KÚV != totožnosť; spoločný vlastník = námet, nie dôkaz",
            "pocet_uzlov": len(nodes), "pocet_hran": len(edges),
            "spolocni_vlastnici": spolocni, "top_huby": top_huby,
            "uzly": list(nodes.values()), "hrany": edges}

def _selftest():
    own = {"rows": [
        {"subjekt": "Alfa s.r.o.", "ico": "111", "kuv": [{"meno": "Ján Novák"}]},
        {"subjekt": "Beta s.r.o.", "ico": "222", "kuv": [{"meno": "Ján Novák"}, {"meno": "Eva Málik"}]},
    ]}
    store = {"items": [
        {"source": "zmluvy", "dod": "Alfa s.r.o.", "dod_ico": "111", "meta": "Objednávateľ: Mesto X", "suma": "1 000 000"},
        {"source": "zmluvy", "dod": "Beta s.r.o.", "dod_ico": "222", "meta": "Objednávateľ: Mesto X", "suma": "500 000"},
    ]}
    g = build(own, store)
    ok = True
    sv = g["spolocni_vlastnici"]
    if len(sv) != 1 or _norm(sv[0]["osoba"]) != "jan novak": ok = False; print("  !! spoloční vlastníci:", sv)
    if set(sv[0]["firmy"]) != {"Alfa s.r.o.", "Beta s.r.o."}: ok = False
    if not any(e["typ"] == "spoločný_vlastník" for e in g["hrany"]): ok = False
    if not any(e["typ"] == "dodáva" for e in g["hrany"]): ok = False
    print("uzlov", g["pocet_uzlov"], "hran", g["pocet_hran"], "| spoloční vlastníci:", sv[0]["osoba"] if sv else None)
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"): print(__doc__); return 0
    if argv[0] == "--selftest": return _selftest()
    d = argv[0]; store_path = argv[1]
    out = argv[2] if len(argv) > 2 else os.path.join(d, "graph.json")
    own = json.load(open(os.path.join(d, "ownership.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "ownership.json")) else {}
    store = json.load(open(store_path, encoding="utf-8"))
    g = build(own, store)
    json.dump(g, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Zapísané: {out} | uzlov {g['pocet_uzlov']} hran {g['pocet_hran']} spoloční vlastníci {len(g['spolocni_vlastnici'])}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
