#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — DOCUMENT INTELLIGENCE (extrakcia zo SK dokumentov).
Z textu dokumentu (kontrolný protokol NKÚ, zmluva, rozhodnutie) vytiahne štruktúrované
údaje s DOHĽADATEĽNOSŤOU na konkrétnu pasáž:
  - finančné hodnoty (€, tis./mil. eur) + kontext
  - IČO
  - dátumy
  - odkazy na zákony (č./rok)
  - kľúčové zistenia (nehospodárne, zmarené, odstúpené OČTK, v rozpore so zákonom, nepreukázané)

Extrakcia textu z PDF (produkcia, engine): pdfplumber ak je dostupné (text PDF);
skenované PDF = OCR (pytesseract) — fáza 2. Tu je extrakcia textu oddelená od parsingu,
takže parsing sa dá testovať na čistom texte bez PDF závislosti.
Výstup SÚKROMNE (sentinel). Zistenia sú DOSLOVNE z dokumentu — nie interpretácia.
"""
import re, json, sys, os

SENTINEL = "SKMON-PRIVATE-DO-NOT-PUBLISH"

MESIACE = {"januára":1,"februára":2,"marca":3,"apríla":4,"mája":5,"júna":6,"júla":7,
           "augusta":8,"septembra":9,"októbra":10,"novembra":11,"decembra":12}

def _ctx(text, start, end, pad=70):
    a = max(0, start - pad); b = min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[a:b]).strip()

def extract_amounts(text):
    """Finančné hodnoty v €. Normalizuje 'tis. eur'→×1000, 'mil. eur'→×1e6."""
    out = []
    # X mil. eur / X tis. eur / X eur / X €
    for m in re.finditer(r"(\d[\d\s]*(?:[.,]\d+)?)\s*(mil\.|tis\.)?\s*(?:eur|€)", text, re.I):
        raw = m.group(1).replace(" ", "").replace(",", ".")
        try: val = float(raw)
        except Exception: continue
        unit = (m.group(2) or "").lower()
        if unit.startswith("mil"): val *= 1_000_000
        elif unit.startswith("tis"): val *= 1_000
        if val < 1000:   # odfiltruj drobné/percentá bez jednotky
            continue
        out.append({"suma_eur": round(val, 2), "text": m.group(0).strip(), "kontext": _ctx(text, m.start(), m.end())})
    return out

def extract_icos(text):
    out = []
    for m in re.finditer(r"I[ČC]O\s*:?\s*(\d{8})", text):
        out.append({"ico": m.group(1), "kontext": _ctx(text, m.start(), m.end())})
    return out

def extract_dates(text):
    out = set()
    for m in re.finditer(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b", text):
        d, mo, y = m.groups()
        try:
            import datetime; out.add(datetime.date(int(y), int(mo), int(d)).isoformat())
        except Exception: pass
    for m in re.finditer(r"\b(\d{1,2})\.\s*([a-záéíóúýčšžťďľň]+)\s*(\d{4})\b", text, re.I):
        mo = MESIACE.get(m.group(2).lower())
        if mo:
            try:
                import datetime; out.add(datetime.date(int(m.group(3)), mo, int(m.group(1))).isoformat())
            except Exception: pass
    return sorted(out)

def extract_laws(text):
    out = {}
    for m in re.finditer(r"z[áa]kon\w*\s*(?:č\.\s*)?(\d+/\d{4})", text, re.I):
        out.setdefault(m.group(1), _ctx(text, m.start(), m.end()))
    return [{"zakon": k, "kontext": v} for k, v in out.items()]

FINDING_KW = [
    ("nehospodárne", r"nehospod[áa]rn"),
    ("zmarené investície", r"zmaren\w*\s+investíci"),
    ("odstúpené OČTK (trestné)", r"orgán\w*\s+činn\w*\s+v\s+trestn"),
    ("v rozpore so zákonom", r"v\s+rozpore\s+so\s+z[áa]konom"),
    ("nepreukázané výdavky", r"nepreuk[áa]z\w*"),
    ("sankcia / pokuta", r"sankci\w*|pokut\w*|vyrub\w*"),
    ("zlyhanie finančného riadenia", r"zlyhani\w*\s+finančn\w*\s+riaden"),
]

def extract_findings(text):
    out = []
    for label, pat in FINDING_KW:
        for m in re.finditer(pat, text, re.I):
            out.append({"typ": label, "pasáž": _ctx(text, m.start(), m.end(), pad=110)})
    # dedup podľa (typ, prvých 60 znakov pasáže)
    seen, dd = set(), []
    for o in out:
        k = (o["typ"], o["pasáž"][:60])
        if k in seen: continue
        seen.add(k); dd.append(o)
    return dd

def extract_structured(text, source_url=""):
    return {
        SENTINEL: True, "zdroj": source_url, "dlzka_textu": len(text),
        "sumy": extract_amounts(text)[:60],
        "ico": extract_icos(text),
        "datumy": extract_dates(text)[:40],
        "zakony": extract_laws(text),
        "zistenia": extract_findings(text),
    }

# ---- extrakcia textu z PDF (produkcia) ----
def pdf_text(path):
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber nie je nainštalované (pip install pdfplumber)")
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, p in enumerate(pdf.pages):
            pages.append(p.extract_text() or "")
    return "\n".join(pages)

def pdf_text_url(session, url):
    """Stiahne PDF (requests) do /tmp a extrahuje text (pdfplumber)."""
    import tempfile
    r = session.get(url, timeout=60, headers={"User-Agent": "sk-monitor/0.1 (verejny zaujem)"})
    r.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(r.content); tmp = f.name
    try:
        return pdf_text(tmp)
    finally:
        try: os.unlink(tmp)
        except Exception: pass

def process_store(store, out_dir, cap=5):
    """Spracuje NKÚ PDF dokumenty linkované z kontrolných položiek store.json (najnovšie)."""
    try:
        import requests
    except ImportError:
        print("requests chýba"); return []
    items = [it for it in store.get("items", []) if it.get("source") == "kontrolne"
             and ".pdf" in (it.get("url", "").lower())]
    seen, docs = set(), []
    items.sort(key=lambda it: it.get("date") or "", reverse=True)
    sess = requests.Session()
    for it in items:
        url = it.get("url")
        if url in seen:
            continue
        seen.add(url)
        if len(docs) >= cap:
            break
        try:
            text = pdf_text_url(sess, url)
            res = extract_structured(text, url)
            res["kontrola"] = it.get("meta", ""); res["titul"] = it.get("title", "")
            docs.append(res)
        except Exception as e:
            print("WARN document", str(e)[:80])
    os.makedirs(out_dir, exist_ok=True)
    json.dump({SENTINEL: True, "pocet": len(docs), "dokumenty": docs},
              open(os.path.join(out_dir, "documents.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # čitateľný prehľad
    L = ["<!-- " + SENTINEL + " -->", "# Document Intelligence — extrakcia z NKÚ protokolov", "",
         "Doslovne z dokumentov (nie interpretácia). Každé zistenie má pasáž na dohľadanie.", ""]
    for d in docs:
        L.append(f"## {d.get('titul','')[:90]}")
        sumy = sorted({s['suma_eur'] for s in d['sumy']}, reverse=True)[:8]
        L.append("- Sumy: " + ", ".join(f"{int(x):,} €".replace(",", " ") for x in sumy))
        L.append("- Zistenia: " + ", ".join(sorted({z['typ'] for z in d['zistenia']})))
        L.append("- Zákony: " + ", ".join(z['zakon'] for z in d['zakony']))
        L.append("")
    open(os.path.join(out_dir, "documents.md"), "w", encoding="utf-8").write("\n".join(L))
    print(f"document.py: spracovaných {len(docs)} NKÚ dokumentov")
    return docs

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--store":
        store = json.load(open(sys.argv[2], encoding="utf-8"))
        out = sys.argv[3] if len(sys.argv) > 3 else "findings"
        cap = int(sys.argv[4]) if len(sys.argv) > 4 else 5
        process_store(store, out, cap); return
    if len(sys.argv) < 2:
        print("Použitie: python document.py <text|pdf> [url]  |  python document.py --store <store.json> [out] [cap]"); return
    path = sys.argv[1]; src = sys.argv[2] if len(sys.argv) > 2 else path
    text = pdf_text(path) if path.lower().endswith(".pdf") else open(path, encoding="utf-8").read()
    print(json.dumps(extract_structured(text, src), ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
