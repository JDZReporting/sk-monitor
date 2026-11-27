#!/usr/bin/env python3
# SKMON-PUBLIC. Diagnostika štruktúry DODATKOV na CRZ — beží v Actions (otvorená sieť).
"""
tools/crz_dodatky_probe.py — zistí, ako CRZ viaže dodatky na zmluvu, aby sme ingest nestavali naslepo.
Stiahne listing „doplnené zmluvy", vytiahne prvé odkazy na /zmluva/<id>, otvorí 2 detaily a uloží:
sekciu okolo „Dodatk"/„Doplnené", podradené /zmluva/ odkazy, typ/číslo. Výstup do findings/ (súkromné).

Použitie (Actions):  python3 tools/crz_dodatky_probe.py findings/_crz_dodatky_probe.json
"""
import json, sys, os, re, urllib.request

UA = {"User-Agent": "sk-monitor/crz-dodatky-probe (public-interest research)"}
BASE = "https://www.crz.gov.sk"

def _get(url, cap=500000):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
            return r.read(cap).decode("utf-8", "ignore")   # limit čítania — veľký listing inak vyprší
    except Exception as e:
        return f"__ERR__ {type(e).__name__}: {e}"

def _zmluva_links(html, exclude=None):
    ids = re.findall(r'href=["\'](/zmluva/(\d+)/?)["\']', html or "")
    out, seen = [], set()
    for href, zid in ids:
        if zid in seen or zid == (exclude or ""): continue
        seen.add(zid); out.append(zid)
    return out

def _around(html, needle, win=600):
    t = re.sub(r"<[^>]+>", " ", html or ""); t = re.sub(r"\s+", " ", t)
    i = t.lower().find(needle.lower())
    return t[max(0, i-120):i+win] if i >= 0 else None

def main(argv):
    out = argv[0] if argv else "findings/_crz_dodatky_probe.json"
    res = {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "ucel": "zistiť väzbu dodatok↔zmluva v CRZ"}
    listing = _get(BASE + "/doplnene-zmluvy/")
    if listing.startswith("__ERR__"):
        res["listing_error"] = listing
        json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2); return 0
    zids = _zmluva_links(listing)[:3]
    res["listing_prvych_id"] = zids
    res["detaily"] = []
    for zid in zids[:2]:
        html = _get(f"{BASE}/zmluva/{zid}/")
        d = {"id": zid}
        if html.startswith("__ERR__"):
            d["error"] = html
        else:
            d["typ_cislo_okno"] = _around(html, "Typ:", 200)
            d["dodatky_okno"] = _around(html, "Dodatk", 800) or _around(html, "Doplnen", 800)
            d["podradene_zmluva_id"] = _zmluva_links(html, exclude=zid)[:15]
        res["detaily"].append(d)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Zapísané:", out, "| listing id:", zids)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
