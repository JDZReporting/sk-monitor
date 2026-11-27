#!/usr/bin/env python3
# SKMON-PUBLIC (kód). Výstupy o subjektoch -> súkromná vrstva.
"""
engine/ted.py — klient TED (Tenders Electronic Daily) Search API v3.

Zdroj: EÚ databáza verejných obstarávaní (nadlimitné). Dokumentácia:
  https://docs.ted.europa.eu/api/latest/search.html
Endpoint: POST https://api.ted.europa.eu/v3/notices/search  — BEZ autentifikácie (pre reuserov).
Telo (expert query): {"query": "...", "fields": [...], "page": 1, "limit": N, "scope": "ALL"}.

CIEĽ: získať pre SK obstarávania — víťaz, IČO, počet uchádzačov, typ konania, predpokladaná/výsledná
hodnota, CPV, časti (lots), dátumy, zmeny. Prepojiť na CRZ zmluvy (cez IČO + predmet + hodnoty + dátumy).

ROBUSTNOSŤ: názvy eForms polí sú v Swaggeri; klient pri prvom behu uloží SUROVÚ odpoveď (ted_raw.json)
na overenie schémy a parsuje OBRANNE (skúša varianty názvov). HTTP 202/200 samo osebe nie je úspech —
úspech = reálne SK záznamy uložené a sparsované (merané v data_quality).

Použitie:
  python3 engine/ted.py --selftest
  python3 engine/ted.py <out_dir> [limit]      # stiahne SK oznámenia, uloží ted_notices.json + ted_raw.json
"""
import json, sys, os, datetime, urllib.request, urllib.error

API = "https://api.ted.europa.eu/v3/notices/search"
UA = {"User-Agent": "sk-monitor/ted (public-interest research)", "Content-Type": "application/json", "Accept": "application/json"}

# Polia skúšame v dokumentovaných eForms business-term názvoch; parser potom berie, čo reálne príde.
REQ_FIELDS = ["publication-number", "notice-title", "notice-type", "buyer-name", "buyer-country",
              "winner-name", "organisation-identifier", "classification-cpv", "total-value",
              "estimated-value", "received-tenders", "procedure-type", "publication-date", "links"]

def _query_sk(since):
    # Expert query: oznámenia s krajinou kupujúceho SK, publikované od dátumu.
    return f'(buyer-country="SVK" OR organisation-country-buyer="SVK") AND publication-date>={since}'

def search(since="20260101", limit=50, page=1):
    body = json.dumps({"query": _query_sk(since), "fields": REQ_FIELDS,
                       "page": page, "limit": limit, "scope": "ALL"}).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def _g(d, *keys):
    """Vráti prvú neprázdnu hodnotu z viacerých možných názvov polí (obranne)."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", [], {}):
            return d[k]
    return None

def parse_notice(n):
    """Z jedného TED záznamu vytiahni kanonické polia (obranne voči názvom)."""
    return {
        "ted_id": _g(n, "publication-number", "publicationNumber", "ND"),
        "nazov": _g(n, "notice-title", "title", "TI"),
        "typ_oznamenia": _g(n, "notice-type", "TD"),
        "obstaravatel": _g(n, "buyer-name", "AA", "OL"),
        "vitaz": _g(n, "winner-name", "winner"),
        "ico_subjektu": _g(n, "organisation-identifier", "nationalId"),
        "cpv": _g(n, "classification-cpv", "PC", "cpv"),
        "predpokladana_hodnota": _g(n, "estimated-value", "estimatedValue"),
        "vysledna_hodnota": _g(n, "total-value", "totalValue", "value"),
        "pocet_uchadzacov": _g(n, "received-tenders", "numberTenders"),
        "typ_konania": _g(n, "procedure-type", "PR"),
        "datum": _g(n, "publication-date", "PD", "publicationDate"),
        "url": _g(n, "links", "URI"),
    }

def run(since="20260101", limit=50, max_pages=4):
    raw_first = None; notices = []; err = None
    try:
        for p in range(1, max_pages + 1):
            d = search(since, limit, p)
            if raw_first is None: raw_first = d
            items = d.get("notices") or d.get("results") or d.get("content") or []
            if not items: break
            notices.extend(parse_notice(x) for x in items)
            if len(items) < limit: break
    except urllib.error.HTTPError as e:
        try: err = {"http": e.code, "body": e.read()[:500].decode("utf-8", "ignore")}
        except Exception: err = {"http": e.code}
    except Exception as e:
        err = {"error": type(e).__name__, "msg": str(e)[:300]}
    return {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "zdroj": "TED Search API v3", "since": since,
            "pocet": len(notices), "chyba": err,
            "raw_prva_strana_kluce": (list(raw_first.keys()) if isinstance(raw_first, dict) else None),
            "notices": notices}, raw_first

def _selftest():
    sample = {"notices": [
        {"publication-number": "123456-2026", "notice-title": "Rekonštrukcia cesty",
         "buyer-name": "Mesto X", "buyer-country": "SVK", "winner-name": "Stavba s.r.o.",
         "organisation-identifier": "12345678", "received-tenders": 1, "procedure-type": "open",
         "estimated-value": 1000000, "total-value": 1250000, "classification-cpv": "45233120",
         "publication-date": "2026-03-01"}]}
    # simuluj parse
    ps = [parse_notice(x) for x in sample["notices"]]
    p = ps[0]; ok = True
    for k, v in {"ted_id": "123456-2026", "obstaravatel": "Mesto X", "vitaz": "Stavba s.r.o.",
                 "ico_subjektu": "12345678", "pocet_uchadzacov": 1, "vysledna_hodnota": 1250000,
                 "predpokladana_hodnota": 1000000}.items():
        if p.get(k) != v: ok = False; print("  !!", k, p.get(k), "exp", v)
    print("single-bid signál:", p["pocet_uchadzacov"] == 1)
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"): print(__doc__); return 0
    if argv[0] == "--selftest": return _selftest()
    outdir = argv[0]; limit = int(argv[1]) if len(argv) > 1 else 50
    since = (datetime.date.today() - datetime.timedelta(days=120)).strftime("%Y%m%d")
    res, raw = run(since=since, limit=limit)
    os.makedirs(outdir, exist_ok=True)
    json.dump(res, open(os.path.join(outdir, "ted_notices.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # surová prvá strana (malá) na overenie reálnej schémy pre doladenie parsera
    if raw is not None:
        try:
            json.dump({"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "sample": raw},
                      open(os.path.join(outdir, "ted_raw.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception: pass
    print(f"TED: {res['pocet']} SK oznámení | chyba: {res['chyba']}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
