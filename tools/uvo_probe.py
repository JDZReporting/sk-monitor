#!/usr/bin/env python3
# SKMON-PUBLIC. Diagnostika schémy ÚVO OpenData — beží v Actions (otvorená sieť), lokálne/sandbox blokované.
"""
tools/uvo_probe.py — zistí REÁLNU schému ÚVO OpenData (opendata.uvo.gov.sk), aby sme klienta
nestavali naslepo. Stiahne pár kandidátskych endpointov, uloží malú vzorku + zoznam polí.
Nepublikuje sa do verejnej vrstvy (výstup patrí do findings/).

Použitie (v Actions):  python3 tools/uvo_probe.py findings/_uvo_probe.json
"""
import json, sys, urllib.request, urllib.error

# Overené sondou: www.uvo.gov.sk/openDataIdx žije (200, HTML index datasetov); TED API 202 (reachable).
# Teraz z HTML indexu extrahujeme odkazy na reálne datasety (bulk súbory / GetFile / sub-API).
CANDIDATES = [
    "https://www.uvo.gov.sk/openDataIdx",
    "https://www.uvo.gov.sk/opendata-zakazky",
    "https://www.uvo.gov.sk/bulk-downloads",
    "https://data.slovensko.sk/api/action/package_search?q=obstar%C3%A1vanie",
    "https://ted.europa.eu/api/v3.0/notices/search",
]

def _extract_links(html):
    """Z HTML indexu vytiahni zaujímavé odkazy (datasety/bulk/API)."""
    import re
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html or "")
    pat = re.compile(r'(opendata|getfile|dataset|\.xml|\.csv|\.zip|\.json|download|export|/od/|rest|api)', re.I)
    out, seen = [], set()
    for h in hrefs:
        if pat.search(h) and h not in seen:
            seen.add(h); out.append(h)
        if len(out) >= 40: break
    return out
UA = {"User-Agent": "sk-monitor/uvo-probe (public-interest research)"}

def probe(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            raw = r.read(120000)   # väčší náhľad, aby sme zachytili odkazy na datasety v HTML indexe
            out = {"url": url, "status": r.status, "ctype": r.headers.get("Content-Type")}
            try:
                d = json.loads(raw.decode("utf-8", "ignore"))
                out["json_top_keys"] = list(d.keys())[:30] if isinstance(d, dict) else f"list[{len(d)}]"
                # ukáž kľúče prvého záznamu, ak je to zoznam/stránkovaný objekt
                rec = None
                if isinstance(d, dict):
                    for k in ("data", "items", "content", "results", "_embedded"):
                        if isinstance(d.get(k), list) and d[k]:
                            rec = d[k][0]; out["list_field"] = k; break
                elif isinstance(d, list) and d:
                    rec = d[0]
                if isinstance(rec, dict):
                    out["record_keys"] = list(rec.keys())[:40]
                    out["record_sample"] = {k: rec[k] for k in list(rec.keys())[:12]}
            except Exception:
                txt = raw.decode("utf-8", "ignore")
                out["text_head"] = txt[:200]
                links = _extract_links(txt)
                if links: out["links"] = links
            return out
    except urllib.error.HTTPError as e:
        return {"url": url, "http_error": e.code, "msg": str(e)[:160]}
    except Exception as e:
        return {"url": url, "error": type(e).__name__, "msg": str(e)[:160]}

def main(argv):
    out = argv[0] if argv else "findings/_uvo_probe.json"
    res = {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "ucel": "zistiť reálnu schému ÚVO OpenData pre klienta",
           "sondy": [probe(u) for u in CANDIDATES]}
    import os
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for s in res["sondy"]:
        print(s.get("url"), "->", s.get("status") or s.get("http_error") or s.get("error"),
              "| record_keys:", s.get("record_keys", "—"))
    print("Zapísané:", out)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
