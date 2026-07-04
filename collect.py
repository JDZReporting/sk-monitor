#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor v2 — denný zber (bez AI) s kategóriami a filtrovateľným panelom.
Parlament (NR SR) + Vláda (rokovania.gov.sk) = kompletne, kategorizované.
Zákazky (ÚVO) = posuvné okno: panel ukazuje posledných 7 dní, archív drží 30 dní (staršie sa mažú).
Rolujúci store (data/store.json) — panel ukazuje aktuálny stav, nielen "nové od behu".
Určené pre GitHub Actions (cron). Statický panel docs/index.html s filtrami (kategória/zdroj/blok/hľadanie).
"""
import os, re, json, datetime, unicodedata, html, hashlib, urllib.parse, email.utils
import xml.etree.ElementTree as ET
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    raise SystemExit("pip install -r requirements.txt")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data"); DOCS = os.path.join(ROOT, "docs")
os.makedirs(DATA, exist_ok=True); os.makedirs(DOCS, exist_ok=True)
CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "sk"}
TODAY = datetime.date.today()
ISO = TODAY.isoformat()

def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))

def get(url):
    try: return requests.get(url, headers=UA, timeout=45).text
    except Exception: return ""

def kategoria(text):
    n = norm(text)
    for kat, kws in CFG["kategorie"].items():
        if any(k in n for k in kws):
            return kat
    return "Ostatné"

def predkladatel(title):
    """Vytiahne predkladateľov z názvu návrhu (bez potreby zoznamu poslancov)."""
    low = title.lower()
    if "vládny návrh" in low:
        return "Vláda SR", "Vládny"
    if "vrátený prezident" in low or "prezidentom slovenskej republiky na opätovné" in low:
        return "Prezident SR (vrátený zákon)", "Iné"
    if "skupiny poslancov" in low:
        return "Skupina poslancov", "Poslanecký"
    m = re.search(r"republiky\s+(.+?)\s+na vydanie", title)
    if m and ("poslanc" in low or "poslank" in low):
        return m.group(1).strip(), "Poslanecký"
    return "", "Iné"

def _stem(s):
    return re.sub(r"(á|a|ý|y|é|e|o)$", "", s)

def load_poslanci():
    """Stiahne členov poslaneckých klubov z NR SR -> {priezvisko_norm: 'Koalícia'/'Opozícia'}."""
    mp = {}
    try:
        idx = BeautifulSoup(get("https://www.nrsr.sk/web/Default.aspx?sid=poslanci/kluby"), "html.parser")
    except Exception:
        return mp
    for a in idx.find_all("a", href=True):
        if "poslanci/kluby/klub" not in a["href"]:
            continue
        klub = norm(a.get_text(" ", strip=True))
        bloc = "Koalícia" if any(k in klub for k in CFG.get("koalicia_kluby", [])) else \
               "Opozícia" if any(k in klub for k in CFG.get("opozicia_kluby", [])) else None
        if not bloc:
            continue
        url = urllib.parse.urljoin("https://www.nrsr.sk/web/", a["href"])
        txt = BeautifulSoup(get(url), "html.parser").get_text("\n")
        for m in re.finditer(r"\n\s*([^\n,]{2,40}),\s*[^\n]{2,30}\n\s*(?:predseda|podpredseda|člen|členka|overovate)", txt):
            mp[norm(m.group(1).strip())] = bloc
    return mp

def blok_from(pk, typ, mp):
    if typ == "Vládny":
        return "Koalícia (vláda)"
    if not pk or pk == "Skupina poslancov" or not mp:
        return "Neurčené"
    low = norm(pk); found = set()
    for surn, bloc in mp.items():
        st = _stem(surn)
        if len(st) >= 4 and st in low:
            found.add(bloc)
    if found == {"Koalícia"}: return "Koalícia"
    if found == {"Opozícia"}: return "Opozícia"
    if len(found) > 1: return "Zmiešané"
    return "Neurčené"

def _doc_text(url):
    """Stiahne dokument (rtf/pdf/html) a vráti čistý text (úryvok)."""
    try:
        r = requests.get(url, headers=UA, timeout=45); data = r.content
        ct = r.headers.get("content-type", "").lower()
        if "pdf" in ct or url.lower().endswith(".pdf") or data[:4] == b"%PDF":
            import io
            from pdfminer.high_level import extract_text
            return extract_text(io.BytesIO(data))[:6000]
        if data[:5].lstrip() == b"{\\rtf" or url.lower().endswith(".rtf"):
            from striprtf.striprtf import rtf_to_text
            return rtf_to_text(data.decode("latin-1", "ignore"))[:6000]
        txt = data.decode("utf-8", "ignore")
        return (BeautifulSoup(txt, "html.parser").get_text(" ") if "<" in txt[:200] else txt)[:6000]
    except Exception:
        return ""

def dovodova_url(detail_url):
    """Nájde odkaz na dôvodovú správu (preferuje 'všeobecná časť') na detaile tlače."""
    try:
        soup = BeautifulSoup(get(detail_url), "html.parser")
    except Exception:
        return ""
    cand = []
    for a in soup.find_all("a", href=True):
        if "dovodova sprava" in norm(a.get_text(" ", strip=True)):
            cand.append(("vseobecn" in norm(a.get_text(" ", strip=True)), urllib.parse.urljoin(detail_url, a["href"])))
    cand.sort(reverse=True)
    return cand[0][1] if cand else ""

def _haiku(instruction, context):
    """Nízkoúrovňové volanie Haiku. Prázdne ak nie je kľúč/kontext."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not context or len(context) < 30:
        return ""
    try:
        r = requests.post("https://api.anthropic.com/v1/messages", timeout=60,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          data=json.dumps({"model": "claude-haiku-4-5-20251001", "max_tokens": 240,
                                           "messages": [{"role": "user", "content": instruction + "\n\n" + context[:4000]}]}))
        return r.json()["content"][0]["text"].strip()[:600]
    except Exception:
        return ""

def ai_popis(it):
    """Krátky popis 'o čo ide / čo sa mení' pre parlament (z dôvodovej správy), vládu a zákazky (z názvu)."""
    s = it.get("source"); title = it.get("title", ""); meta = it.get("meta", "")
    if s == "parlament":
        dv = dovodova_url(it.get("url", "")); text = _doc_text(dv) if dv else ""
        ctx = text if len(text) >= 120 else ("Názov návrhu zákona: " + title)
        return _haiku("Na základe textu napíš po SLOVENSKY 2 až 3 vety, ČO tento návrh zákona konkrétne mení a o čom je. Vecne, zrozumiteľne, bez úvodných fráz.", ctx)
    if s == "vlada":
        return _haiku("Napíš po SLOVENSKY 2 až 3 vety, o čom je tento vládny materiál, čo rieši a aký má dopad. Vecne, bez úvodných fráz.", "Názov: " + title + "\n" + meta)
    if s == "uvo":
        return _haiku("Napíš po SLOVENSKY 2 až 3 vety, čo sa v tejto verejnej zákazke obstaráva, pre koho a načo slúži. Vecne, bez úvodných fráz.", "Zákazka: " + title + "\n" + meta)
    return ""

def headline(it):
    """Krátky zrozumiteľný nadpis 'o čo ide' z názvu (bez AI)."""
    t = it.get("title", ""); s = it.get("source")
    if s == "parlament":
        low = t.lower()
        je_novela = ("ktorým sa mení" in low or "ktorým sa dopĺňa" in low or "ktorou sa mení" in low or "ktorou sa dopĺňa" in low)
        if "460/1992" in t:
            return "Novela Ústavy SR" if je_novela else "Ústavný zákon"
        if "trestný zákon" in low:
            return "Novela Trestného zákona"
        m = re.search(r"(?:Z\. ?z\.|Zb\.)\s+o\s+(.+?)(?:\s+v znení|\s+a o zmene|\s+a ktor|,|\.|\(|$)", t) \
            or re.search(r"z[aá]kona?\s+o\s+(.+?)(?:\s+v znení|\s+a o zmene|\s+a ktor|,|\.|\(|$)", t)
        if m:
            return ("Novela zákona o " if je_novela else "Zákon o ") + m.group(1).strip()
        return t[:110]
    if s == "aktuality":
        t = re.sub(r"\s+[-–]\s+[^-–]{2,45}$", "", t)
    return (t[:118] + "…") if len(t) > 120 else t

def fetch_uvo_value(url):
    try:
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", get(url)))
        m = re.search(r"[Pp]redpokladan[áa] hodnota[^0-9]{0,25}([0-9][0-9\s .,]{2,})\s*(?:EUR|€|Eur)", txt)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip() + " €"
    except Exception:
        pass
    return ""

def fetch_stav(url):
    try:
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", get(url)))
        m = re.search(r"Stav legislat[ií]vneho procesu:\s*(.+?)\s+(?:grafick|N[áa]vrh|V[lá]dny|Z[áa]kon z)", txt)
        return m.group(1).strip()[:70] if m else ""
    except Exception:
        return ""

def parse_date(s):
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s or "")
    if m:
        d, mo, y = map(int, m.groups())
        try: return datetime.date(y, mo, d).isoformat()
        except ValueError: return ""
    return ""

def days_old(iso):
    try: return (TODAY - datetime.date.fromisoformat(iso)).days
    except Exception: return 99999

# ---------------- ZBER ----------------
def collect_nrsr(mp=None):
    mp = mp or {}
    out = []
    soup = BeautifulSoup(get("https://www.nrsr.sk/web/Default.aspx?sid=zakony/prehlad/predlozene"), "html.parser")
    for a in soup.select('a[href*="MasterID"]'):
        title = a.get_text(" ", strip=True)
        if len(title) < 8: continue
        tr = a.find_parent("tr"); cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")] if tr else []
        cpt = next((c for c in cells if re.fullmatch(r"\d{3,4}", c)), "")
        datum = parse_date(next((c for c in cells if parse_date(c)), ""))
        mid = re.search(r"MasterID=(\d+)", a.get("href", ""))
        pk, typ = predkladatel(title)
        meta = "ČPT " + cpt + " · " + typ + (" · predkladateľ: " + pk if pk else "")
        out.append({"id": "p-" + (cpt or norm(title)[:20]), "source": "parlament", "title": title, "date": datum,
                    "category": kategoria(title), "blok": blok_from(pk, typ, mp), "stav": "", "meta": meta,
                    "url": "https://www.nrsr.sk/web/Default.aspx?sid=zakony/zakon&MasterID=" + mid.group(1) if mid else ""})
    return out

def collect_vlada():
    out = []
    soup = BeautifulSoup(get("https://rokovania.gov.sk/RVL/Material"), "html.parser")
    for tr in soup.select("tr"):
        c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(c) >= 6 and re.search(r"UV-\d+", c[2] if len(c) > 2 else ""):
            a = tr.find("a", href=True)
            url = urllib.parse.urljoin("https://rokovania.gov.sk/RVL/Material", a["href"]) if a else "https://rokovania.gov.sk/RVL/Material"
            out.append({"id": "v-" + c[2], "source": "vlada", "title": c[1], "date": parse_date(c[5]),
                        "category": kategoria(c[1] + " " + c[3]), "blok": "", "meta": c[3] + " · " + c[4],
                        "url": url})
    return out

def collect_uvo(max_pages=6):
    out = []
    for p in range(1, max_pages + 1):
        url = "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek" + (f"?page={p}" if p > 1 else "")
        soup = BeautifulSoup(get(url), "html.parser")
        rows = 0
        for tr in soup.select("tr"):
            c = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(c) >= 2 and c[0] and c[1] and c[0].lower() != "názov zákazky":
                datum = parse_date(next((x for x in c if parse_date(x)), ""))
                obst = c[1]
                a = tr.find("a", href=re.compile("detail"))
                url = urllib.parse.urljoin("https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek", a["href"]) if a else "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek"
                out.append({"id": "u-" + norm(c[0])[:45], "source": "uvo", "title": c[0], "date": datum,
                            "category": kategoria(c[0] + " " + (c[2] if len(c) > 2 else "") + " " + obst),
                            "blok": "", "meta": "Obstarávateľ: " + obst, "url": url})
                rows += 1
        if rows == 0: break
    return out

def collect_aktuality(days=7):
    out = []
    try:
        feeds = json.load(open(os.path.join(ROOT, "feeds.json"), encoding="utf-8")).get("institucie", [])
    except Exception:
        return out
    for f in feeds:
        url = f.get("rss") or ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f["q"]) + "&hl=sk&gl=SK&ceid=SK:sk")
        xml = get(url)
        if not xml:
            continue
        try:
            root = ET.fromstring(xml)
        except Exception:
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            try:
                d = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
            except Exception:
                d = ""
            if not title or (d and days_old(d) > days):
                continue
            out.append({"id": "a-" + hashlib.md5(link.encode()).hexdigest()[:12], "source": "aktuality",
                        "title": title, "date": d, "category": kategoria(title), "blok": "",
                        "meta": f["nazov"], "url": link})
    return out

# ---------------- STORE (rolujúci archív) ----------------
def load_store():
    p = os.path.join(DATA, "store.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"items": []}

def main():
    store = load_store()
    by_id = {it["id"]: it for it in store.get("items", [])}
    mp = load_poslanci()
    print("Poslancov v klubovej mape:", len(mp))
    fetched = []
    try: fetched += collect_nrsr(mp)
    except Exception as e: print("WARN nrsr", e)
    for fn in (collect_vlada, collect_uvo, collect_aktuality):
        try: fetched += fn()
        except Exception as e: print("WARN", fn.__name__, e)
    new = 0
    for it in fetched:
        if it["id"] in by_id:
            by_id[it["id"]].update({k: it[k] for k in ("title", "category", "blok", "meta", "url", "date", "stav", "suma", "popis") if it.get(k)})
        else:
            it["first_seen"] = ISO
            by_id[it["id"]] = it; new += 1
    items = list(by_id.values())
    # prune: ÚVO staršie ako archív (30 dní) zmazať; parlament+vláda ponechať
    arch = CFG.get("uvo_dni_archiv", 30)
    items = [it for it in items if not (it["source"] in ("uvo", "aktuality") and days_old(it.get("date") or it.get("first_seen", ISO)) > arch)]

    # BACKFILL (capped per run, self-healing): stav (parlament), suma (ÚVO), AI popis (parlament/vláda/ÚVO)
    ai_cap, ai_done, uvo_done = int(CFG.get("ai_max_per_run", 120)), 0, 0
    for it in items:
        s = it.get("source")
        if s == "parlament" and it.get("url") and not it.get("stav"):
            it["stav"] = fetch_stav(it["url"])
        if s == "uvo" and it.get("url") and "suma" not in it and uvo_done < 80:
            it["suma"] = fetch_uvo_value(it["url"]); uvo_done += 1
        if s in ("parlament", "vlada", "uvo") and not it.get("popis") and not it.get("_ai_tried") and ai_done < ai_cap:
            p = ai_popis(it); it["_ai_tried"] = True
            if p:
                it["popis"] = p
            ai_done += 1
    print("AI popisov (tento beh):", ai_done)
    store = {"items": items, "updated": ISO}
    json.dump(store, open(os.path.join(DATA, "store.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # panel: parlament+vláda všetko; ÚVO len posledných N dní
    pan = CFG.get("uvo_dni_panel", 7)
    panel = [it for it in items if it["source"] not in ("uvo", "aktuality") or days_old(it.get("date") or ISO) <= pan]
    panel.sort(key=lambda x: (x.get("date") or "", x["id"]), reverse=True)
    build_dashboard(panel)
    print(f"Store: {len(items)} položiek (+{new} nových). Panel: {len(panel)}.")

# ---------------- PANEL ----------------
def build_dashboard(items):
    cats = list(CFG["kategorie"].keys()) + ["Ostatné"]
    view = [{"source": it["source"], "category": it.get("category", "Ostatné"), "blok": it.get("blok", ""),
             "date": it.get("date", ""), "url": it.get("url", ""), "h": headline(it), "full": it.get("title", ""),
             "info": it.get("meta", ""), "stav": it.get("stav", ""), "suma": it.get("suma", ""), "popis": it.get("popis", "")} for it in items]
    data_js = json.dumps(view, ensure_ascii=False)
    cats_js = json.dumps(cats, ensure_ascii=False)
    cat_chips = "".join(f'<label class="chip"><input type="checkbox" value="{html.escape(c)}" checked onchange="render()"> {html.escape(c)}</label>' for c in cats)
    tmpl = """<!DOCTYPE html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SK monitor</title><style>
:root{--bg:#f4f6f9;--card:#fff;--ink:#1a2230;--muted:#6b7688;--line:#e3e8ef;--brand:#1F3864}
@media (prefers-color-scheme:dark){:root{--bg:#0f141b;--card:#182230;--ink:#e6eaf0;--muted:#9aa7b8;--line:#2a3646;--brand:#8fb0ea}}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
header{background:var(--brand);color:#fff;padding:13px 20px;position:sticky;top:0;z-index:20}
h1{margin:0;font-size:17px}header p{margin:3px 0 0;opacity:.9;font-size:12px}
.wrap{max-width:1000px;margin:0 auto;padding:14px}
.controls{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px;margin-bottom:14px;position:sticky;top:60px;z-index:10}
input[type=text]{width:100%;padding:10px;border:1px solid var(--line);border-radius:9px;font-size:14px;margin-bottom:9px;background:var(--bg);color:var(--ink)}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:5px 0}
.chip{font-size:12px;background:transparent;border-radius:14px;padding:3px 10px;cursor:pointer;user-select:none;border:1px solid var(--line);color:var(--ink)}
.chip input{margin-right:4px;vertical-align:middle}
.small{color:var(--muted);font-size:12px}
button.mini{font-size:11px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:2px 8px;cursor:pointer}
.seg{font-size:12px;margin:2px 0 10px;color:var(--muted)}.seg b{color:var(--brand)}
.section{margin-bottom:8px}
.sechead{cursor:pointer;font-size:15px;color:var(--brand);margin:16px 0 8px;border-bottom:2px solid var(--line);padding-bottom:5px;user-select:none}
.caret{display:inline-block;width:14px}
.cnt{background:var(--brand);color:#fff;border-radius:10px;padding:0 8px;font-size:11px;font-weight:700}
.secbody{display:flex;flex-direction:column;gap:8px}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid #99a;border-radius:10px;padding:10px 12px}
.card.parlament{border-left-color:#3b6fd4}.card.vlada{border-left-color:#8a5cd0}.card.uvo{border-left-color:#22a35a}.card.aktuality{border-left-color:#d38a1a}
.chead{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:3px}
.srcpill{font-size:10px;font-weight:700;color:#fff;border-radius:10px;padding:1px 8px;text-transform:uppercase;letter-spacing:.3px}
.srcpill.parlament{background:#3b6fd4}.srcpill.vlada{background:#8a5cd0}.srcpill.uvo{background:#22a35a}.srcpill.aktuality{background:#d38a1a}
.badge{font-size:10px;font-weight:700;border-radius:10px;padding:1px 8px}
.b-o{background:#fde2e0;color:#C0392B}.b-k{background:#e2ecff;color:#1F3864}.b-suma{background:#1E8449;color:#fff}.b-new{background:#ffd54a;color:#5a4600}
.cdate{margin-left:auto;color:var(--muted);font-size:11px}
.title{display:block;font-weight:700;color:var(--ink);text-decoration:none;font-size:15px;margin:2px 0}
.title[href]:hover{color:var(--brand);text-decoration:underline}
.desc{opacity:.92;font-size:13px;line-height:1.45;margin:3px 0}
.facts{color:var(--muted);font-size:11.5px;margin-top:3px}
@media(max-width:600px){.controls{top:56px}.wrap{padding:10px}}
</style></head><body>
<header><h1>🇸🇰 SK monitor — parlament · vláda · zákazky · aktuality</h1>
<p>Aktualizované __UPDATED__ · verejné zdroje (NR SR, rokovania vlády, ÚVO, novinky inštitúcií). Zákazky a aktuality: posledných 7 dní. Klikni na nadpis kategórie na zbalenie/rozbalenie.</p></header>
<div class="wrap">
 <div class="controls">
  <input type="text" id="q" placeholder="🔎 hľadať v názve / metadátach..." oninput="render()">
  <div class="row"><span class="small">Zdroj:</span>
    <label class="chip"><input type="checkbox" class="src" value="parlament" checked onchange="render()"> Parlament</label>
    <label class="chip"><input type="checkbox" class="src" value="vlada" checked onchange="render()"> Vláda</label>
    <label class="chip"><input type="checkbox" class="src" value="uvo" checked onchange="render()"> Zákazky</label>
    <label class="chip"><input type="checkbox" class="src" value="aktuality" checked onchange="render()"> Aktuality</label>
    <span class="small" style="margin-left:12px">Blok (parlament):</span>
    <label class="chip"><input type="checkbox" class="blok" value="Koalícia" checked onchange="render()"> Koalícia</label>
    <label class="chip"><input type="checkbox" class="blok" value="Opozícia" checked onchange="render()"> Opozícia</label>
    <label class="chip"><input type="checkbox" class="blok" value="ine" checked onchange="render()"> neurčené</label>
  </div>
  <div class="row"><span class="small">Kategórie:</span> <button class="mini" onclick="allCats(true)">všetky</button> <button class="mini" onclick="allCats(false)">žiadne</button></div>
  <div class="row" id="cats">__CATS__</div>
 </div>
 <div id="stat" class="seg"></div>
 <div id="list"></div>
</div>
<script>
const DATA = __DATA__;
const CATS = __CATSORDER__;
function sel(cls){return [...document.querySelectorAll('.'+cls+':checked')].map(e=>e.value)}
function allCats(v){document.querySelectorAll('#cats input').forEach(e=>e.checked=v);render()}
function esc(s){return (s||'').replace(/"/g,'&quot;')}
const COL={};
const SRCL={parlament:'Parlament',vlada:'Vláda',uvo:'Zákazky',aktuality:'Aktuality'};
function toggle(c){COL[c]=!COL[c];render();}
function relDate(d){if(!d)return'';const dd=Math.round((new Date()-new Date(d))/86400000);if(dd<=0)return'dnes';if(dd===1)return'včera';if(dd<7)return'pred '+dd+' dňami';return d;}
function isNew(d){if(!d)return false;return Math.round((new Date()-new Date(d))/86400000)<=2;}
function render(){
 const q=document.getElementById('q').value.toLowerCase();
 const srcs=sel('src'), csel=sel('catcb'), bloks=sel('blok');
 const groups={}; let n=0;
 for(const it of DATA){
  if(!srcs.includes(it.source))continue;
  if(!csel.includes(it.category))continue;
  const bl=(it.blok&&it.blok.indexOf('Koal')===0)?'Koalícia':(it.blok==='Opozícia'?'Opozícia':'ine');
  if(it.source==='parlament' && !bloks.includes(bl))continue;
  const txt=((it.h||'')+' '+(it.full||'')+' '+(it.info||'')+' '+it.category).toLowerCase();
  if(q && !txt.includes(q))continue;
  (groups[it.category]=groups[it.category]||[]).push(it); n++;
 }
 let out='';
 for(const cat of CATS){
  const arr=groups[cat]; if(!arr||!arr.length)continue;
  arr.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
  const op=!COL[cat];
  out+=`<div class="section"><h2 class="sechead" onclick="toggle('${cat.replace(/'/g,'')}')"><span class="caret">${op?'▾':'▸'}</span> ${cat} <span class="cnt">${arr.length}</span></h2>`;
  if(op){out+='<div class="secbody">';
   for(const it of arr){
    const bl=(it.blok&&it.blok.indexOf('Koal')===0)?'Koalícia':(it.blok==='Opozícia'?'Opozícia':'ine');
    const blokHtml=(it.source==='parlament'&&it.blok)?`<span class="badge ${bl==='Opozícia'?'b-o':'b-k'}">${it.blok}</span>`:'';
    const sumaHtml=it.suma?`<span class="badge b-suma">💶 ${it.suma}</span>`:'';
    const newHtml=isNew(it.date)?`<span class="badge b-new">NOVÉ</span>`:'';
    const stavHtml=it.stav?` · stav: ${it.stav}`:'';
    const hh=it.url?`<a class="title" href="${it.url}" target="_blank" title="${esc(it.full)}">${it.h||it.full}</a>`:`<span class="title">${it.h||it.full}</span>`;
    const popisHtml=it.popis?`<div class="desc">${it.popis}</div>`:'';
    out+=`<div class="card ${it.source}"><div class="chead"><span class="srcpill ${it.source}">${SRCL[it.source]||it.source}</span> ${blokHtml} ${sumaHtml} ${newHtml} <span class="cdate">${relDate(it.date)}</span></div>${hh}${popisHtml}<div class="facts">${it.info||''}${stavHtml}</div></div>`;
   }
   out+='</div>';}
  out+='</div>';
 }
 document.getElementById('stat').innerHTML=`Zobrazené: <b>${n}</b> z ${DATA.length}`;
 document.getElementById('list').innerHTML=out||'<p class="small">Nič nezodpovedá filtru.</p>';
}
render();
</script>
</body></html>"""
    tmpl = tmpl.replace("__CATS__", cat_chips).replace("__DATA__", data_js).replace("__CATSORDER__", cats_js).replace("__UPDATED__", ISO)
    # oprava: category checkboxy potrebujú triedu catcb
    tmpl = tmpl.replace('class="chip"><input type="checkbox" value="', 'class="chip"><input type="checkbox" class="catcb" value="')
    open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8").write(tmpl)

if __name__ == "__main__":
    main()
