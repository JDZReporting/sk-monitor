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
    # stav procesu — len pre NOVÉ parlamentné tlače (lacné, bez AI)
    for it in fetched:
        if it.get("source") == "parlament" and it.get("url") and it["id"] not in by_id:
            it["stav"] = fetch_stav(it["url"])
    new = 0
    for it in fetched:
        if it["id"] in by_id:
            by_id[it["id"]].update({k: it[k] for k in ("title", "category", "blok", "meta", "url", "date", "stav") if it.get(k)})
        else:
            it["first_seen"] = ISO
            by_id[it["id"]] = it; new += 1
    items = list(by_id.values())
    # prune: ÚVO staršie ako archív (30 dní) zmazať; parlament+vláda ponechať
    arch = CFG.get("uvo_dni_archiv", 30)
    items = [it for it in items if not (it["source"] in ("uvo", "aktuality") and days_old(it.get("date") or it.get("first_seen", ISO)) > arch)]
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
    data_js = json.dumps(items, ensure_ascii=False)
    cat_chips = "".join(f'<label class="chip"><input type="checkbox" value="{html.escape(c)}" checked onchange="render()"> {html.escape(c)}</label>' for c in cats)
    tmpl = """<!DOCTYPE html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SK monitor</title><style>
*{box-sizing:border-box}body{font-family:Arial,Helvetica,sans-serif;margin:0;background:#f4f6f9;color:#1a1a1a}
header{background:#1F3864;color:#fff;padding:14px 20px}h1{margin:0;font-size:18px}header p{margin:3px 0 0;opacity:.85;font-size:12px}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
.controls{background:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.07);margin-bottom:14px}
input[type=text]{width:100%;padding:9px;border:1px solid #ccc;border-radius:8px;font-size:14px;margin-bottom:10px}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:6px 0}
.chip{font-size:12px;background:#eef1f6;border-radius:14px;padding:3px 9px;cursor:pointer;user-select:none;border:1px solid #dde3ec}
.chip input{margin-right:4px;vertical-align:middle}
.seg{font-size:12px;margin-right:10px}.seg b{color:#1F3864}
.item{background:#fff;border-radius:8px;padding:9px 12px;margin:6px 0;box-shadow:0 1px 3px rgba(0,0,0,.06);font-size:14px;line-height:1.45}
.tag{display:inline-block;font-size:11px;border-radius:10px;padding:1px 8px;color:#fff;margin-right:5px}
.src-parlament{background:#1F3864}.src-vlada{background:#6b3fa0}.src-uvo{background:#1E8449}.src-aktuality{background:#B9770E}
.cat{color:#555;font-size:12px}.blok{font-size:11px;font-weight:700;margin-left:5px}
.o{color:#C0392B}.k{color:#1F3864}.small{color:#777;font-size:12px}a{color:#1F3864}
button.mini{font-size:11px;border:1px solid #ccc;background:#fff;border-radius:6px;padding:2px 8px;cursor:pointer}
</style></head><body>
<header><h1>🇸🇰 SK monitor — parlament · vláda · verejné zákazky</h1>
<p>Denne aktualizované, verejné zdroje (nrsr.sk, rokovania.gov.sk, uvo.gov.sk). ÚVO: posledných 7 dní. Filtre sú lokálne v prehliadači.</p></header>
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
function sel(cls){return [...document.querySelectorAll('.'+cls+':checked')].map(e=>e.value)}
function allCats(v){document.querySelectorAll('#cats input').forEach(e=>e.checked=v);render()}
function render(){
 const q=document.getElementById('q').value.toLowerCase();
 const srcs=sel('src'), cats=sel('catcb'), bloks=sel('blok');
 let n=0,html2='';
 for(const it of DATA){
  if(!srcs.includes(it.source))continue;
  if(!cats.includes(it.category))continue;
  const bl=(it.blok&&it.blok.indexOf('Koal')===0)?'Koalícia':(it.blok==='Opozícia'?'Opozícia':'ine');
  if(it.source==='parlament' && !bloks.includes(bl))continue;
  const txt=(it.title+' '+(it.meta||'')+' '+it.category).toLowerCase();
  if(q && !txt.includes(q))continue;
  n++;
  const blokHtml=(it.source==='parlament'&&it.blok)?` <span class="blok ${bl==='Opozícia'?'o':'k'}">${it.blok}</span>`:'';
  const stavHtml=it.stav?` · <b>stav:</b> ${it.stav}`:'';
  const lbl=it.source==='parlament'?'→ znenie a dôvodová správa':'→ zdroj';
  const link=it.url?` · <a href="${it.url}" target="_blank">${lbl}</a>`:'';
  html2+=`<div class="item"><span class="tag src-${it.source}">${it.source}</span> ${it.title}${blokHtml}<br><span class="cat">${it.category} · ${it.meta||''}${stavHtml} · ${it.date||''}${link}</span></div>`;
 }
 document.getElementById('stat').innerHTML=`Zobrazené: <b>${n}</b> z ${DATA.length}`;
 document.getElementById('list').innerHTML=html2||'<p class="small">Nič nezodpovedá filtru.</p>';
}
render();
</script>
</body></html>"""
    tmpl = tmpl.replace("__CATS__", cat_chips).replace("__DATA__", data_js)
    # oprava: category checkboxy potrebujú triedu catcb
    tmpl = tmpl.replace('class="chip"><input type="checkbox" value="', 'class="chip"><input type="checkbox" class="catcb" value="')
    open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8").write(tmpl)

if __name__ == "__main__":
    main()
