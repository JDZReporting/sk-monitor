#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — rizikové skóre (engine, v0.2).

Reťazec: verejné data/store.json  ->  základné príznaky (suma/vznik/krajina)
         ->  RPVS obohatenie (vlastníctvo, konflikt záujmov, spoloční vlastníci)
         ->  SÚKROMNÝ výstup findings/risk_scored.json (so sentinelom).

Výstup je subjektovo-špecifický -> patrí do sk-monitor-intelligence/, NIE do verejného repa.
RPVS je voliteľné: ak nie je sieť/requests, engine beží len so základnými príznakmi.
"""
import json, re, sys, os, datetime
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import rpvs
except Exception:
    rpvs = None

# ---------- parsovanie ----------
def parse_date(s):
    if not s: return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    try: return datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else None
    except ValueError: return None

def parse_suma(s):
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    t = re.sub(r"[^\d,.\-]", "", str(s))
    if not t: return None
    if "," in t and "." in t: t = t.replace(".", "").replace(",", ".")
    elif "," in t: t = t.replace(",", ".")
    try: return float(t)
    except ValueError: return None

def is_foreign(k):
    return bool(k) and k.strip().lower() not in ("sk","slovensko","slovenská republika","slovenska republika","")

# váhy indikátorov
W = {"SK-SUP-NEW":2,"SK-SUP-FOREIGN":1,"SK-HIGHVALUE":1,"SK-COMBO":2,
     "SK-OWN-PUBOFFICIAL":3,"SK-OWN-CHALLENGED":2,"SK-OWN-FOREIGN-KUV":1,"SK-OWN-NO-KUV":1,"SK-OWN-SHARED":3,
     "SK-BUYER-CONC":2,"SK-MARKET-HHI":1}

# ---------- základné príznaky ----------
def base_flags(items):
    by_cat = defaultdict(list)
    for it in items:
        s = parse_suma(it.get("suma"))
        if s and s > 0: by_cat[it.get("category","Ostatné")].append(s)
    p90 = {}
    for cat, vals in by_cat.items():
        if len(vals) >= 10:
            v = sorted(vals); p90[cat] = v[int(0.9*(len(v)-1))]
    out = []
    for it in items:
        flags, score, ev = [], 0, {}
        vznik, dt = parse_date(it.get("dod_vznik")), (parse_date(it.get("date")) or parse_date(it.get("first_seen")))
        suma, cat = parse_suma(it.get("suma")), it.get("category","Ostatné")
        new = foreign = hv = False
        if vznik and dt and (dt-vznik).days < 365:
            new=True; flags.append("SK-SUP-NEW"); ev["vek_firmy_dni"]=(dt-vznik).days
        if is_foreign(it.get("dod_krajina","")):
            foreign=True; flags.append("SK-SUP-FOREIGN"); ev["krajina"]=it.get("dod_krajina")
        if suma and cat in p90 and suma >= p90[cat]:
            hv=True; flags.append("SK-HIGHVALUE"); ev["suma"]=suma; ev["p90_kategorie"]=round(p90[cat])
        if hv and (new or foreign): flags.append("SK-COMBO")
        if flags:
            out.append({"id":it.get("id"),"dod":it.get("overit") or it.get("dod"),
                        "ico":it.get("dod_ico",""),"objednavatel_meta":it.get("meta",""),
                        "kategoria":cat,"date":it.get("date"),"url":it.get("url",""),
                        "flags":flags,"dokaz":ev})
    return out, p90

# ---------- RPVS obohatenie ----------
def enrich_rpvs(results, rpvs_lookup, cap=60):
    if not rpvs_lookup or not rpvs: return {}
    owner_index = defaultdict(set)  # kuv_key -> {dod}
    done = 0
    # najprv položky s najväčším počtom základných príznakov (prioritizácia)
    for r in sorted(results, key=lambda x: -len(x["flags"])):
        if done >= cap: break
        ico = (r.get("ico") or "").strip()
        if not ico: continue
        try:
            partner = rpvs_lookup(ico)
        except Exception:
            continue
        done += 1
        if not partner: continue
        oflags, oev = rpvs.derive_flags(partner)
        if oflags:
            r["flags"] += oflags
            r["dokaz"].update(oev)
        for key in rpvs.kuv_key(partner):
            owner_index[key].add(r["dod"])
    # SK-OWN-SHARED: spoloční koneční užívatelia výhod medzi rôznymi dodávateľmi
    shared = {}
    for key, dods in owner_index.items():
        if len(dods) >= 2:
            for d in dods: shared.setdefault(d, set()).update(dods - {d})
    for r in results:
        if r["dod"] in shared:
            r["flags"].append("SK-OWN-SHARED")
            r["dokaz"]["spolocny_vlastnik_s"] = sorted(shared[r["dod"]])[:5]
    return {"rpvs_overenych": done, "spolocni_vlastnici_dvojic": sum(1 for v in owner_index.values() if len(v)>=2)}

def finalize(results):
    for r in results:
        r["skore"] = sum(W.get(f,0) for f in dict.fromkeys(r["flags"]))
    results.sort(key=lambda r: r["skore"], reverse=True)
    return results

def parse_buyer(meta):
    import re as _re
    m = _re.search(r"Objedn[a\u00e1]vate[\u013el]:\s*(.+?)(?:\s*\u00b7|$)", meta or "")
    if m: return m.group(1).strip()
    m = _re.search(r"Obstar[a\u00e1]vate[\u013el]:\s*(.+?)(?:\s*\u00b7|$)", meta or "")
    return m.group(1).strip() if m else ""

def aggregate(items):
    """Koncentrácia: opakovaný dodávateľ u obstarávateľa (SK-BUYER-CONC) a HHI kategórie (SK-MARKET-HHI)."""
    buyer_total=defaultdict(float); pair_total=defaultdict(float); pair_count=defaultdict(int)
    cat_sup=defaultdict(lambda: defaultdict(float))
    for it in items:
        if it.get("source")!="zmluvy": continue
        v=parse_suma(it.get("suma"))
        if not v or v<=0: continue
        dod=it.get("overit") or it.get("dod") or ""
        buyer=parse_buyer(it.get("meta")); cat=it.get("category","Ostatn\u00e9")
        if buyer and dod:
            buyer_total[buyer]+=v; pair_total[(buyer,dod)]+=v; pair_count[(buyer,dod)]+=1
        if dod: cat_sup[cat][dod]+=v
    hhi={}
    for cat,sup in cat_sup.items():
        tot=sum(sup.values())
        if tot>0 and len(sup)>=3:
            hhi[cat]=sum((x/tot)**2 for x in sup.values())
    extra=defaultdict(list); ev=defaultdict(dict)
    for it in items:
        if it.get("source")!="zmluvy": continue
        dod=it.get("overit") or it.get("dod") or ""
        buyer=parse_buyer(it.get("meta")); cat=it.get("category","Ostatn\u00e9")
        if buyer and dod and buyer_total[buyer]>0:
            share=pair_total[(buyer,dod)]/buyer_total[buyer]
            if share>0.5 and pair_count[(buyer,dod)]>=3:
                extra[it["id"]].append("SK-BUYER-CONC")
                ev[it["id"]]["podiel_u_obstaravatela"]=round(share,2)
                ev[it["id"]]["pocet_zmluv_dvojice"]=pair_count[(buyer,dod)]
                ev[it["id"]]["obstaravatel"]=buyer
        if cat in hhi and hhi[cat]>0.25:
            extra[it["id"]].append("SK-MARKET-HHI")
            ev[it["id"]]["hhi_kategorie"]=round(hhi[cat],3)
    return extra, ev

def run(store, rpvs_lookup=None, rpvs_cap=60):
    items = store.get("items", [])
    results, p90 = base_flags(items)
    # agregačné (štrukturálne) príznaky — môžu označiť aj položky bez základného príznaku
    extra, agg_ev = aggregate(items)
    by_id = {r["id"]: r for r in results}
    for it in items:
        iid = it.get("id")
        if iid in extra:
            if iid in by_id:
                r = by_id[iid]; r["flags"] += extra[iid]; r["dokaz"].update(agg_ev[iid])
            else:
                r = {"id": iid, "dod": it.get("overit") or it.get("dod"),
                     "ico": it.get("dod_ico",""), "objednavatel_meta": it.get("meta",""),
                     "kategoria": it.get("category","Ostatn\u00e9"), "date": it.get("date"),
                     "url": it.get("url",""), "flags": list(extra[iid]), "dokaz": dict(agg_ev[iid])}
                results.append(r); by_id[iid] = r
    rinfo = enrich_rpvs(results, rpvs_lookup, rpvs_cap)
    finalize(results)
    summary = {"polozky":len(items),"kategorii_s_p90":len(p90),"oznacenych":len(results)}
    summary.update(rinfo)
    return results, summary

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "../data/store.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "findings/risk_scored.json"
    store = json.load(open(src, encoding="utf-8"))
    rpvs_lookup = None
    try:
        import requests
        if rpvs:
            sess = requests.Session()
            rpvs_lookup = lambda ico: rpvs.lookup_by_ico(sess, ico)
    except ImportError:
        pass
    results, summary = run(store, rpvs_lookup)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump({"SKMON-PRIVATE-DO-NOT-PUBLISH":True,
               "generated":datetime.datetime.utcnow().isoformat()+"Z",
               "summary":summary,"items":results},
              open(out,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print("SÚHRN:", summary)
    for r in results[:5]:
        print(f"  [{r['skore']}] {r['flags']} | {r['dod']} | {r['kategoria']}")

if __name__ == "__main__":
    main()
