#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — DENNÝ ZBER (bez LLM, lacný). Parlament (NR SR) + Vláda (rokovania.gov.sk) + Zákazky (ÚVO).
Zbiera dáta, triedi PRAVIDLAMI (config.json), deduplikuje, uloží archív a vygeneruje online panel (docs/index.html).
Určené na beh v GitHub Actions (cron) — nezávisle od PC. LLM/AI sa NEpoužíva (to je až on-demand mimo tohto skriptu).

Spustenie lokálne:  python collect.py
Výstupy: data/<DATUM>.json, data/brief_<DATUM>.md, docs/index.html, data/state.json
"""
import os, re, json, datetime, unicodedata, html
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    raise SystemExit("Nainštaluj závislosti: pip install -r requirements.txt")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data"); DOCS = os.path.join(ROOT, "docs")
os.makedirs(DATA, exist_ok=True); os.makedirs(DOCS, exist_ok=True)
CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "sk"}
TODAY = datetime.date.today().isoformat()

def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))

def get(url):
    return requests.get(url, headers=UA, timeout=45).text

def tema_of(text):
    n = norm(text)
    for tema, kws in CFG["temy"].items():
        if any(k in n for k in kws):
            return tema
    return None

def blok_of(navrhovatel):
    nav = norm(navrhovatel)
    if "vlad" in nav or "ministerstvo" in nav:
        return "Koalícia (vláda)"
    k = o = False
    for pr, strana in CFG["poslanec_strana"].items():
        if norm(pr) in nav:
            if strana in CFG["koalicia_strany"]: k = True
            elif strana in CFG["opozicia_strany"]: o = True
    return "Koalícia" if (k and not o) else "Opozícia" if (o and not k) else "Zmiešané" if (k and o) else "Neurčené"

# ---------------- ZBER ----------------
def collect_nrsr():
    out = []
    try:
        soup = BeautifulSoup(get("https://www.nrsr.sk/web/Default.aspx?sid=zakony/prehlad/predlozene"), "html.parser")
        for a in soup.select('a[href*="MasterID"]'):
            nazov = a.get_text(" ", strip=True)
            if len(nazov) < 8: continue
            tr = a.find_parent("tr")
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")] if tr else []
            cpt = next((c for c in cells if re.fullmatch(r"\d{3,4}", c)), "")
            datum = next((c for c in cells if re.search(r"\d{1,2}\.\s*\d{1,2}\.\s*\d{4}", c)), "")
            mid = re.search(r"MasterID=(\d+)", a.get("href", ""))
            out.append({"id": "nrsr-" + (cpt or nazov[:20]), "cpt": cpt, "nazov": nazov, "datum": datum,
                        "tema": tema_of(nazov), "blok": blok_of(nazov),
                        "url": "https://www.nrsr.sk/web/Default.aspx?sid=zakony/zakon&MasterID=" + mid.group(1) if mid else ""})
    except Exception as e:
        out.append({"_error": f"NR SR: {e}"})
    return out

def collect_vlada():
    out = []
    try:
        soup = BeautifulSoup(get("https://rokovania.gov.sk/RVL/Material"), "html.parser")
        for tr in soup.select("tr"):
            c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(c) >= 6 and re.search(r"UV-\d+", c[2] if len(c) > 2 else ""):
                rez = c[3]; tema = next((t for k, t in CFG["vlada_rezort_tema"].items() if k in norm(rez)), None) or tema_of(c[1])
                out.append({"id": "vlada-" + c[2], "charakter": c[0], "nazov": c[1], "cislo": c[2],
                            "rezort": rez, "predkladatel": c[4], "datum": c[5], "tema": tema})
    except Exception as e:
        out.append({"_error": f"Vláda: {e}"})
    return out

def collect_uvo():
    out = []
    try:
        soup = BeautifulSoup(get("https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek"), "html.parser")
        for tr in soup.select("tr"):
            c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(c) >= 2 and c[0] and c[1]:
                obst = c[1]
                rez = next((t for t, kws in CFG["uvo_rezorty"].items() if any(k in norm(obst) for k in kws)), None)
                if rez:  # len sledované inštitúcie (redukuje šum a náklady)
                    out.append({"id": "uvo-" + norm(c[0])[:40], "nazov": c[0], "obstaravatel": obst,
                                "cpv": c[2] if len(c) > 2 else "", "nuts": c[3] if len(c) > 3 else "",
                                "datum": c[-1], "tema": rez})
    except Exception as e:
        out.append({"_error": f"ÚVO: {e}"})
    return out

# ---------------- ULOŽENIE + PANEL ----------------
def load_state():
    p = os.path.join(DATA, "state.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"seen": []}

def esc(s): return html.escape(str(s or ""))

def build_dashboard(recent):
    def sec(title, items, render):
        rows = "".join(render(x) for x in items) or "<p class='empty'>Žiadne nové položky.</p>"
        return f"<section><h2>{title} <span class='cnt'>{len(items)}</span></h2>{rows}</section>"
    def rn_parl(b):
        blok = b.get("blok", "")
        col = {"Opozícia": "#C0392B", "Koalícia": "#1F3864", "Koalícia (vláda)": "#1F3864"}.get(blok, "#777")
        lk = f" · <a href='{esc(b['url'])}' target='_blank'>znenie/tlač</a>" if b.get("url") else ""
        return f"<div class='item' data-t='{esc(b.get('tema'))}'><span class='pill' style='background:{col}'>{esc(blok)}</span> <b>ČPT {esc(b.get('cpt'))}</b> ({esc(b.get('datum'))}) — {esc(b.get('nazov'))} <span class='tema'>{esc(b.get('tema'))}</span>{lk}</div>"
    def rn_vlada(m):
        return f"<div class='item' data-t='{esc(m.get('tema'))}'><b>{esc(m.get('cislo'))}</b> ({esc(m.get('datum'))}) — {esc(m.get('nazov'))} <span class='tema'>{esc(m.get('rezort'))}</span> · {esc(m.get('predkladatel'))}</div>"
    def rn_uvo(z):
        return f"<div class='item' data-t='{esc(z.get('tema'))}'><b>{esc(z.get('obstaravatel'))}</b> — {esc(z.get('nazov'))} <span class='tema'>{esc(z.get('cpv'))} · {esc(z.get('tema'))}</span> ({esc(z.get('datum'))})</div>"
    p = [x for x in recent.get("parlament", []) if not x.get("_error")]
    v = [x for x in recent.get("vlada", []) if not x.get("_error")]
    u = [x for x in recent.get("uvo", []) if not x.get("_error")]
    body = sec("🏛️ Parlament — návrhy zákonov", p, rn_parl) + sec("🏢 Vláda — materiály na rokovanie", v, rn_vlada) + sec("📄 Verejné obstarávania (ÚVO) — sledované inštitúcie", u, rn_uvo)
    tmpl = f"""<!DOCTYPE html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SK monitor — {TODAY}</title><style>
body{{font-family:Arial,Helvetica,sans-serif;margin:0;background:#f4f6f9;color:#1a1a1a}}
header{{background:#1F3864;color:#fff;padding:16px 22px}}h1{{margin:0;font-size:19px}}header p{{margin:4px 0 0;opacity:.85;font-size:13px}}
.wrap{{max-width:1000px;margin:0 auto;padding:18px}}
input{{width:100%;padding:9px;border:1px solid #ccc;border-radius:8px;margin-bottom:14px;font-size:14px}}
h2{{color:#1F3864;font-size:16px;border-bottom:2px solid #1F3864;padding-bottom:5px;margin-top:26px}}
.cnt{{background:#1F3864;color:#fff;border-radius:10px;padding:1px 8px;font-size:12px}}
.item{{background:#fff;border-radius:8px;padding:9px 12px;margin:6px 0;box-shadow:0 1px 3px rgba(0,0,0,.07);font-size:14px;line-height:1.4}}
.pill{{color:#fff;border-radius:10px;padding:1px 8px;font-size:11px;font-weight:700}}
.tema{{color:#666;font-size:12px;font-style:italic}}.empty{{color:#888}}
a{{color:#1F3864}}
</style></head><body>
<header><h1>🇸🇰 SK monitor — parlament · vláda · zákazky</h1>
<p>Aktualizované {TODAY}. Zdroje: nrsr.sk, rokovania.gov.sk, uvo.gov.sk. Denný automatický zber (bez AI). Detailný rozbor (čo mení, uchádzači, vlastníci, médiá) je on-demand.</p></header>
<div class="wrap"><input id="q" placeholder="🔎 filtruj podľa slova (názov, téma, rezort)..." onkeyup="f()">{body}
<p class="tema">Stranícke zaradenie a témy sú orientačné (pravidlá). CRZ / obchodný register / RPVS sa používajú on-demand na overovanie.</p></div>
<script>function f(){{var q=document.getElementById('q').value.toLowerCase();document.querySelectorAll('.item').forEach(function(e){{e.style.display=e.textContent.toLowerCase().includes(q)?'':'none'}})}}</script>
</body></html>"""
    open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8").write(tmpl)

def brief_md(recent):
    L = [f"# SK monitor — {TODAY}", ""]
    for key, title in [("parlament", "Parlament"), ("vlada", "Vláda"), ("uvo", "Zákazky (ÚVO)")]:
        items = [x for x in recent.get(key, []) if not x.get("_error")]
        L.append(f"## {title} ({len(items)})")
        for x in items:
            L.append(f"- {x.get('cpt') or x.get('cislo') or ''} {x.get('nazov','')} — {x.get('tema') or x.get('rezort') or ''} ({x.get('datum','')})")
        L.append("")
    return "\n".join(L)

def main():
    state = load_state(); seen = set(state.get("seen", []))
    raw = {"parlament": collect_nrsr(), "vlada": collect_vlada(), "uvo": collect_uvo()}
    # len nové (dedupe) do dnešného výstupu; chyby ponechaj na logging
    new = {}
    for k, items in raw.items():
        errs = [i for i in items if i.get("_error")]
        fresh = [i for i in items if not i.get("_error") and i.get("id") not in seen]
        new[k] = fresh + errs
        for i in fresh: seen.add(i["id"])
    json.dump({"datum": TODAY, **new}, open(os.path.join(DATA, f"{TODAY}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(os.path.join(DATA, f"brief_{TODAY}.md"), "w", encoding="utf-8").write(brief_md(new))
    build_dashboard(new)
    json.dump({"seen": sorted(seen)[-5000:], "last_run": TODAY}, open(os.path.join(DATA, "state.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    counts = {k: len([i for i in v if not i.get("_error")]) for k, v in new.items()}
    print("Nové položky:", counts)

if __name__ == "__main__":
    main()
