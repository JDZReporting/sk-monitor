#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor v3 — denný/priebežný zber (bez AI pri scrapovaní) so záložkami.
Zdroje: Parlament (NR SR) · Vláda (rokovania.gov.sk) · Zákazky (ÚVO) · Kontrolné inštitúcie (ÚHP, NKÚ, PMÚ, GP, NBÚ, NKÚ… cez Google News RSS).
Rolujúci store (data/store.json) drží 30 dní; panel (docs/index.html) ukazuje udalosti za posledných 7 dní.
Panel: Novinky (posledné 2 dni) · Parlament · Vláda · Zákazky · Zmluvy · Kontrolné inštitúcie · Všetko (podľa dátumu). Témy sa vyberajú centrálne.
Určené pre GitHub Actions (cron).
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
NOW_TS = datetime.datetime.now(datetime.timezone.utc).isoformat()
PANEL_DNI = int(CFG.get("panel_dni", 7))
ARCHIV_DNI = int(CFG.get("uvo_dni_archiv", 30))

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

def _is_muni(text):
    """Je objednávateľ samospráva? Obec/mesto/mestská časť/VÚC alebo ich podnik (napr. 'Služby mesta ...')."""
    ob = norm(text or "")
    obp = " " + ob + " "
    return (ob.startswith("obec ") or ob.startswith("mesto ") or ob.startswith("mestsk") or ob.startswith("obecn")
            or "mestska cast" in ob or "samospravn" in ob
            or " mesta " in obp or " mesto " in obp or " obce " in obp or " obec " in obp)

_STAT_KW = ("ministerstvo", "narodna dialnicna", "slovenska posta", "zeleznice slovenskej",
            "zeleznicna spolocnost", "zssk", "socialna poistovna", "vseobecna zdravotna",
            "vodohospodarsky podnik", "lesy slovenskej", "lesy sr", "slovenska sprava ciest",
            "financne riaditelstvo", "financna sprava", "statna pokladnica", "urad vlady",
            "slovenska konsolidacna", "narodna banka slovenska", "slovensky pozemkovy fond",
            "environmentalny fond", "mh manazment", "transpetrol", "letove prevadzkove",
            "vojenske", "slovensky vodohospodarsky", "narodny bezpecnostny", "sprava statnych hmotnych rezerv")
def _is_stat(text):
    """Je obstarávateľ/objednávateľ štát? Ministerstvo, štátny podnik (š. p.) alebo veľká štátna firma/inštitúcia."""
    ob = norm(text or "")
    if "s.p." in ob.replace(" ", "") or "statny podnik" in ob:
        return True
    if any(k in ob for k in _STAT_KW):
        return True
    obp = " " + ob + " "
    return any(a in obp for a in (" nds ", " zsr ", " svp ", " ssc "))

def _cn(s):
    """Normalizovaný názov firmy na porovnanie: bez diakritiky, bodky/čiarky -> medzera, zjednotené medzery."""
    return re.sub(r"\s+", " ", re.sub(r"[.,]", " ", norm(s or ""))).strip()

def _je_firma(name):
    """Je to právnická osoba (firma), nie fyzická osoba? Podľa právnej formy v názve."""
    ln = _cn(name)
    return any(x in ln for x in (" s r o", " a s", "spol", "druzstv", " k s", " v o s", "nadacia", "obcianske zdruz", " n o"))

def rpo_info(name):
    """Z RPO (Štatistický úrad SR): {'vznik': dátum, 'krajina': krajina sídla} pre jednoznačnú AKTÍVNu firmu; {} inak."""
    try:
        r = requests.get("https://api.statistics.sk/rpo/v1/search", params={"fullName": name}, headers=UA, timeout=30)
        data = r.json()
    except Exception:
        return {}
    qn = _cn(name)
    for e in data.get("results", []):
        if e.get("termination"):
            continue
        names = e.get("fullNames", [])
        cur = next((n for n in names if not n.get("validTo")), (names[-1] if names else None))
        if cur and _cn(cur.get("value", "")) == qn:
            out = {"vznik": e.get("establishment", "") or ""}
            addrs = e.get("addresses", [])
            addr = next((a for a in addrs if not a.get("validTo")), (addrs[0] if addrs else None))
            if addr and isinstance(addr.get("country"), dict):
                out["krajina"] = addr["country"].get("value", "")
            return out
    return {}

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
    if s == "zmluvy":
        return _haiku("Napíš po SLOVENSKY 2 až 3 vety, o čom je táto zmluva, čo je jej predmetom a kto komu čo dodáva. Vecne, bez úvodných fráz.", "Zmluva: " + title + "\n" + meta)
    if s == "mpk":
        return _haiku("Napíš po SLOVENSKY 2 až 3 vety, čo tento návrh v medzirezortnom pripomienkovom konaní rieši a čo mení. Vecne, bez úvodných fráz.", "Návrh: " + title + "\n" + meta)
    return ""

def headline(it):
    """Krátky zrozumiteľný nadpis 'o čo ide' z názvu (bez AI)."""
    t = it.get("title", ""); s = it.get("source")
    if s in ("parlament", "mpk"):
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
    if s in ("aktuality", "kontrolne"):
        t = re.sub(r"\s+[-–]\s+[^-–]{2,45}$", "", t)
    return (t[:118] + "…") if len(t) > 120 else t

def fetch_uvo_detail(url):
    """Z detailu zákazky ÚVO (server-rendered TYPO3) vytiahne stav, druh, CPV, EÚ fondy a príp. hodnotu.
    Pozn.: predpokladaná/zmluvná hodnota a uchádzači väčšinou NIE sú na prehľade zákazky — bývajú až v dokumentoch Vestníka."""
    out = {}
    try:
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", get(url)))
    except Exception:
        return out
    def g(p):
        m = re.search(p, txt); return m.group(1).strip() if m else ""
    out["stav"] = g(r"Stav zákazky:\s*(\S+)")
    out["druh"] = g(r"Druh zákazky:\s*(\S+)")
    out["fondy"] = g(r"fondov E[ÚU]:\s*(\S+)")
    m = re.search(r"CPV zákazky:\s*[0-9-]+\s+(.+?)\s+NUTS", txt)
    if m: out["cpv"] = m.group(1).strip()[:70]
    m = re.search(r"[Pp]redpokladan[áa] hodnota[^0-9]{0,25}([0-9][0-9\s .,]{2,})\s*(?:EUR|€|Eur)", txt)
    if m: out["suma"] = re.sub(r"\s+", " ", m.group(1)).strip() + " €"
    return {k: v for k, v in out.items() if v}

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

SK_MES = {"januar": 1, "februar": 2, "marec": 3, "april": 4, "maj": 5, "jun": 6,
          "jul": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "december": 12}
def parse_sk_date(s):
    """Dátum typu '3. Júl 2026' (slovný mesiac) -> ISO."""
    m = re.search(r"(\d{1,2})\.?\s*([A-Za-zÁ-Žá-ž]+)\s*(\d{4})", s or "")
    if m:
        mes = SK_MES.get(norm(m.group(2)))
        if mes:
            try: return datetime.date(int(m.group(3)), mes, int(m.group(1))).isoformat()
            except ValueError: return ""
    return parse_date(s)

def days_old(iso):
    try: return (TODAY - datetime.date.fromisoformat((iso or "")[:10])).days
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
                    "category": kategoria(title), "blok": "", "stav": "", "meta": meta,
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
                url2 = urllib.parse.urljoin("https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek", a["href"]) if a else "https://www.uvo.gov.sk/vyhladavanie/vyhladavanie-zakaziek"
                cat = "Samospráva" if _is_muni(obst) else ("Štát a štátne podniky" if _is_stat(obst) else kategoria(c[0] + " " + (c[2] if len(c) > 2 else "") + " " + obst))
                out.append({"id": "u-" + norm(c[0])[:45], "source": "uvo", "title": c[0], "date": datum,
                            "category": cat, "blok": "", "meta": "Obstarávateľ: " + obst, "url": url2})
                rows += 1
        if rows == 0: break
    return out

def collect_mpk():
    """Medzirezortné pripomienkové konanie (MPK) — oficiálny RSS Slov-Lexu (Min. spravodlivosti SR).
    Najnovšie legislatívne procesy v pripomienkovom konaní: názov, číslo (LP/PI), rezort, dátum."""
    out = []
    xml = get("https://vyhladavanie.slov-lex.sk/rss/legislativnyMaterial")
    if not xml:
        return out
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    DC_CREATOR = "{http://purl.org/dc/elements/1.1/}creator"
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        cislo = (item.findtext("description") or "").strip()
        rezort = (item.findtext(DC_CREATOR) or "").strip()
        try:
            d = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "").date().isoformat()
        except Exception:
            d = ""
        if not title:
            continue
        out.append({"id": "m-" + (cislo or hashlib.md5(link.encode()).hexdigest()[:10]),
                    "source": "mpk", "title": title, "date": d, "category": kategoria(title), "blok": "",
                    "meta": (cislo + " · " if cislo else "") + ("predkladateľ: " + rezort if rezort else ""),
                    "url": link})
    return out

def collect_kontrolne(days=None):
    """Kontrolné/dozorné úrady — OFICIÁLNE RSS feedy (NKÚ, PMÚ…) z ich webov. Žiadne médiá."""
    days = ARCHIV_DNI if days is None else days
    out = []
    try:
        feeds = json.load(open(os.path.join(ROOT, "feeds.json"), encoding="utf-8")).get("kontrolne", [])
    except Exception:
        return out
    for f in feeds:
        rss = f.get("rss")
        if not rss:
            continue
        xml = get(rss)
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
            cat = kategoria(title)
            if cat == "Ostatné":
                cat = f.get("kat", "Ostatné")
            out.append({"id": "k-" + hashlib.md5((link or title).encode()).hexdigest()[:12], "source": "kontrolne",
                        "title": title, "date": d, "category": cat, "blok": "",
                        "meta": f["nazov"], "url": link})
    return out

def collect_crz():
    """Centrálny register zmlúv — najnovšie VÝZNAMNÉ zmluvy (nad prahom sumy), zoradené podľa dátumu zostupne."""
    out = []
    thr = int(CFG.get("crz_suma_od", 100000))
    url = "https://www.crz.gov.sk/?art_suma_spolu_od=%d&order=2&search=1" % thr
    soup = BeautifulSoup(get(url), "html.parser")
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        a = tds[1].find("a", href=re.compile(r"/zmluva/\d+"))
        if not a:
            continue
        nazov = a.get_text(" ", strip=True)
        cislo = tds[1].get_text(" ", strip=True).replace(nazov, "").strip()
        cena = tds[2].get_text(" ", strip=True)
        dod = tds[3].get_text(" ", strip=True)
        obj = tds[4].get_text(" ", strip=True)
        datum = parse_sk_date(tds[0].get_text(" ", strip=True))
        mid = re.search(r"/zmluva/(\d+)", a["href"])
        if not mid:
            continue
        cat = "Samospráva" if _is_muni(obj) else ("Štát a štátne podniky" if _is_stat(obj) else kategoria(nazov + " " + obj + " " + dod))
        # strana na preverenie = tá, čo nie je štát ani samospráva (súkromná firma/osoba)
        overit = next((c for c in (dod, obj) if c and not _is_stat(c) and not _is_muni(c)), "")
        out.append({"id": "z-" + mid.group(1), "source": "zmluvy", "title": nazov, "date": datum,
                    "category": cat, "blok": "", "suma": cena, "dod": dod, "overit": overit,
                    "meta": "Dodávateľ: " + dod + " → Objednávateľ: " + obj + (" · č. " + cislo if cislo else ""),
                    "url": "https://www.crz.gov.sk" + a["href"]})
    return out

# ---------------- STORE (rolujúci archív) ----------------
def load_store():
    p = os.path.join(DATA, "store.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"items": []}

def main():
    store = load_store()
    by_id = {it["id"]: it for it in store.get("items", [])}
    firmy = store.get("firmy", {})   # cache: normalizovaný názov firmy -> {'vznik': dátum}
    fetched = []
    try: fetched += collect_nrsr()
    except Exception as e: print("WARN nrsr", e)
    for fn in (collect_vlada, collect_uvo, collect_mpk, collect_crz, collect_kontrolne):
        try: fetched += fn()
        except Exception as e: print("WARN", fn.__name__, e)
    new = 0
    for it in fetched:
        if it["id"] in by_id:
            by_id[it["id"]].update({k: it[k] for k in ("title", "category", "blok", "meta", "url", "date", "stav", "suma", "popis", "dod", "overit") if it.get(k)})
        else:
            it["first_seen"] = NOW_TS
            by_id[it["id"]] = it; new += 1
        by_id[it["id"]]["last_seen"] = ISO  # naposledy videné v zdroji (pre agendu parlament/vláda)
    items = list(by_id.values())
    # auto-čistenie: zahoď staré/neznáme zdroje (napr. legacy 'aktuality')
    ZNAME = ("parlament", "vlada", "uvo", "zmluvy", "mpk", "kontrolne")
    items = [it for it in items if it["source"] in ZNAME]
    # prune: ÚVO + zmluvy + MPK + kontrolné staršie ako archív (30 dní) zmazať
    items = [it for it in items if not (it["source"] in ("uvo", "mpk", "zmluvy", "kontrolne") and days_old(it.get("date") or it.get("first_seen", ISO)) > ARCHIV_DNI)]
    # kontrolné: ponechaj len položky z OFICIÁLNYCH domén (feeds.json) — vyčisti staré mediálne (Google News) zvyšky
    try:
        _kf = json.load(open(os.path.join(ROOT, "feeds.json"), encoding="utf-8")).get("kontrolne", [])
        _kdoms = [urllib.parse.urlparse(f.get("rss", "")).netloc for f in _kf if f.get("rss")]
    except Exception:
        _kdoms = []
    if _kdoms:
        items = [it for it in items if it["source"] != "kontrolne" or any(d and d in it.get("url", "") for d in _kdoms)]
    # prune: parlament/vláda, ktoré už vypadli z aktuálneho zoznamu (naposledy videné pred >slow_keep dňami)
    slow_keep = int(CFG.get("slow_keep_dni", 21))
    items = [it for it in items if not (it["source"] in ("parlament", "vlada") and days_old(it.get("last_seen") or it.get("first_seen") or ISO) > slow_keep)]
    # migrácia: starý názov kategórie -> nové (Samospráva / Verejná správa) podľa titulku
    for it in items:
        if it.get("category") == "Verejná správa a samospráva":
            it["category"] = kategoria(it.get("title", ""))
    # Zmluvy (CRZ) + Zákazky (ÚVO): podľa obstarávateľa/objednávateľa -> Samospráva alebo Štát a štátne podniky (dotriedi aj staré)
    for it in items:
        if it.get("source") in ("zmluvy", "uvo"):
            m = re.search(r"(?:Objednávate[ľl]|Obstarávate[ľl]):\s*([^·]+)", it.get("meta", ""))
            who = m.group(1) if m else ""
            if _is_muni(who):
                it["category"] = "Samospráva"
            elif _is_stat(who):
                it["category"] = "Štát a štátne podniky"

    # BACKFILL (capped per run, self-healing): stav (parlament), detail zákazky (ÚVO), AI popis
    HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
    ai_cap, ai_done, uvo_done = int(CFG.get("ai_max_per_run", 120)), 0, 0
    rpo_cap, rpo_done = int(CFG.get("rpo_max_per_run", 40)), 0
    for it in items:
        s = it.get("source")
        if s == "zmluvy" and not it.get("_overit_checked") and it.get("overit") and _je_firma(it["overit"]) and rpo_done < rpo_cap:
            key = _cn(it["overit"])
            if key in firmy:
                info = firmy[key]
            else:
                info = rpo_info(it["overit"]); firmy[key] = info; rpo_done += 1
            it["_overit_checked"] = True
            if info.get("vznik"):
                it["dod_vznik"] = info["vznik"]
            if info.get("krajina"):
                it["dod_krajina"] = info["krajina"]
        if s == "parlament" and it.get("url"):
            ns = fetch_stav(it["url"])
            if ns and ns != it.get("stav"):
                if it.get("stav"):
                    it["_changed"] = ISO  # stav sa zmenil (napr. I. -> II. čítanie)
                it["stav"] = ns
        if s == "uvo" and it.get("url") and not it.get("_uvo_done") and uvo_done < 80:
            dd = fetch_uvo_detail(it["url"]); it["_uvo_done"] = True; uvo_done += 1
            for k in ("stav", "druh", "cpv", "fondy", "suma"):
                if dd.get(k):
                    it[k] = dd[k]
        # AI popis LEN ak je kľúč (inak nemarkujeme _ai_tried, nech sa po pridaní kľúča doplnia)
        if HAS_KEY and s in ("parlament", "vlada", "uvo", "zmluvy", "mpk") and not it.get("popis") and not it.get("_ai_tried") and ai_done < ai_cap:
            p = ai_popis(it); it["_ai_tried"] = True
            if p:
                it["popis"] = p
            ai_done += 1
    print("AI popisov (tento beh):", ai_done, "| kľúč prítomný:", HAS_KEY, "| RPO firiem overených:", rpo_done)
    store = {"items": items, "updated": ISO, "firmy": firmy}
    json.dump(store, open(os.path.join(DATA, "store.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # panel: všetky zdroje jednotne za posledných PANEL_DNI dní (7)
    def _age(it): return days_old(it.get("date") or it.get("first_seen") or ISO)
    panel = [it for it in items if _age(it) <= PANEL_DNI]
    panel.sort(key=lambda x: (x.get("date") or x.get("first_seen") or "", x["id"]), reverse=True)
    build_dashboard(panel)
    print(f"Store: {len(items)} položiek (+{new} nových). Panel (do {PANEL_DNI} dní): {len(panel)}.")

# ---------------- PANEL ----------------
def build_dashboard(items):
    cats = list(CFG["kategorie"].keys()) + ["Ostatné"]
    def _info(it):
        base = it.get("meta", "")
        extra = []
        if it.get("druh"): extra.append("Druh: " + it["druh"])
        if it.get("cpv"): extra.append("CPV: " + it["cpv"])
        if it.get("fondy") == "Áno": extra.append("EÚ fondy")
        return base + ((" · " if base else "") + " · ".join(extra) if extra else "")
    view = [{"source": it["source"], "category": it.get("category", "Ostatné"), "blok": it.get("blok", ""),
             "date": it.get("date", "") or (it.get("first_seen", "") or "")[:10], "url": it.get("url", ""), "h": headline(it),
             "full": it.get("title", ""), "info": _info(it), "stav": it.get("stav", ""),
             "suma": it.get("suma", ""), "popis": it.get("popis", ""), "fs": it.get("first_seen", ""), "chg": it.get("_changed", ""), "vznik": it.get("dod_vznik", ""), "overit": it.get("overit", ""), "krajina": it.get("dod_krajina", "")} for it in items]
    data_js = json.dumps(view, ensure_ascii=False)
    cats_js = json.dumps(cats, ensure_ascii=False)
    cat_chips = "".join(f'<label class="chip"><input type="checkbox" class="catcb" value="{html.escape(c)}" checked onchange="render()"> {html.escape(c)}</label>' for c in cats)
    tmpl = r"""<!DOCTYPE html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SK monitor</title><style>
:root{--bg:#f4f6f9;--card:#fff;--ink:#1a2230;--muted:#6b7688;--line:#e3e8ef;--brand:#1F3864}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:var(--bg);color:var(--ink)}
header{background:var(--brand);color:#fff;padding:12px 20px}
h1{margin:0;font-size:17px}header p{margin:3px 0 0;opacity:.9;font-size:12px}
.tabs{display:flex;gap:7px;background:var(--card);padding:9px 12px;border-bottom:1px solid var(--line);box-shadow:0 2px 6px rgba(0,0,0,.06);position:sticky;top:0;z-index:30;overflow-x:auto}
.tab{flex:0 0 auto;color:#33415a;background:var(--bg);border:1.5px solid var(--line);border-radius:9px;padding:8px 15px;font-size:13.5px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all .12s}
.tab:hover{border-color:var(--brand);color:var(--brand)}
.tab.active{color:#fff;background:var(--brand);border-color:var(--brand);box-shadow:0 2px 5px rgba(31,56,100,.3)}
.tcount{font-size:10px;background:var(--line);color:var(--muted);border-radius:9px;padding:0 6px;margin-left:6px;font-weight:700}
.tab.active .tcount{background:rgba(255,255,255,.28);color:#fff}
.wrap{max-width:1000px;margin:0 auto;padding:14px}
.controls{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:11px 13px;margin-bottom:12px;position:sticky;top:56px;z-index:20}
input[type=text]{width:100%;padding:10px;border:1px solid var(--line);border-radius:9px;font-size:14px;margin-bottom:9px;background:var(--bg);color:var(--ink)}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:5px 0}
.chip{font-size:12px;background:transparent;border-radius:14px;padding:3px 10px;cursor:pointer;user-select:none;border:1px solid var(--line);color:var(--ink)}
.chip input{margin-right:4px;vertical-align:middle}
.small{color:var(--muted);font-size:12px}
button.mini{font-size:11px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:6px;padding:2px 8px;cursor:pointer}
details.cats{margin-top:2px}details.cats summary{cursor:pointer;font-size:12px;color:var(--brand)}
.seg{font-size:12px;margin:2px 0 10px;color:var(--muted)}.seg b{color:var(--brand)}
.daydiv{font-size:13px;font-weight:700;color:var(--brand);margin:16px 0 8px;border-bottom:2px solid var(--line);padding-bottom:5px;text-transform:capitalize}
.secbody{display:flex;flex-direction:column;gap:6px}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid #99a;border-radius:9px;padding:8px 11px}
.card.parlament{border-left-color:#3b6fd4}.card.mpk{border-left-color:#e08a1e}.card.vlada{border-left-color:#8a5cd0}.card.uvo{border-left-color:#22a35a}.card.zmluvy{border-left-color:#0f9d8f}.card.kontrolne{border-left-color:#64748b}
.chead{display:flex;flex-wrap:wrap;gap:5px;align-items:center;margin-bottom:2px}
.srcpill{font-size:10px;font-weight:700;color:#fff;border-radius:10px;padding:1px 8px;text-transform:uppercase;letter-spacing:.3px}
.srcpill.parlament{background:#3b6fd4}.srcpill.mpk{background:#e08a1e}.srcpill.vlada{background:#8a5cd0}.srcpill.uvo{background:#22a35a}.srcpill.zmluvy{background:#0f9d8f}.srcpill.kontrolne{background:#64748b}
.badge{font-size:10px;font-weight:700;border-radius:10px;padding:1px 8px}
.b-o{background:#fde2e0;color:#C0392B}.b-k{background:#e2ecff;color:#1F3864}.b-suma{background:#1E8449;color:#fff}.b-new{background:#ffd54a;color:#5a4600}.b-watch{background:#7c3aed;color:#fff}.b-chg{background:#0ea5e9;color:#fff}.b-nova{background:#dc2626;color:#fff}.b-zahr{background:#b45309;color:#fff}
.card.watched{box-shadow:0 0 0 2px #7c3aed inset}
.wbox{background:var(--card);border:1px solid var(--line);border-left:4px solid #7c3aed;border-radius:10px;padding:10px 12px;margin-bottom:12px}
.wsum-h{font-weight:700;color:#7c3aed;font-size:13px;margin-bottom:5px}
.wsum{font-size:13px;margin:2px 0}.wsum b{color:var(--ink)}
.cdate{margin-left:auto;color:var(--muted);font-size:11px}
.title{display:block;font-weight:700;color:var(--ink);text-decoration:none;font-size:14px;line-height:1.3;margin:1px 0}
.title[href]:hover{color:var(--brand);text-decoration:underline}
.desc{opacity:.92;font-size:12.5px;line-height:1.4;margin:3px 0;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.facts{color:var(--muted);font-size:11px;margin-top:2px}
.regl{font-size:10.5px;margin-top:4px;color:var(--muted)}.regl a{color:var(--brand);text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:0 5px;margin-left:2px}.regl a:hover{text-decoration:underline}
.loadmore{display:block;width:100%;margin:14px 0;padding:11px;border:1px dashed var(--line);background:var(--card);color:var(--brand);border-radius:10px;font-size:13px;font-weight:700;cursor:pointer}
.endnote{text-align:center;color:var(--muted);font-size:12px;margin:16px 0}
#toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--brand);color:#fff;padding:9px 15px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .3s;z-index:100;pointer-events:none;box-shadow:0 3px 10px rgba(0,0,0,.25)}
.wsum a{color:#7c3aed;font-size:11px;text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:0 5px;margin-left:3px}.wsum a:hover{text-decoration:underline}
@media(max-width:600px){.controls{top:54px}.wrap{padding:10px}}
</style></head><body>
<header><h1>🇸🇰 SK monitor</h1>
<p>Aktualizované __UPDATED__ · oficiálne zdroje: NR SR, MPK (Slov-Lex), rokovania vlády, ÚVO, register zmlúv (CRZ), kontrolné úrady (NKÚ, PMÚ) · prehľad udalostí za posledných 7 dní.</p></header>
<div class="tabs" id="tabs"></div>
<div class="wrap">
 <div class="controls">
  <input type="text" id="q" placeholder="🔎 hľadať v názve / metadátach..." oninput="render()">
  <div class="row" style="gap:8px">
    <input type="text" id="watch" placeholder="⭐ sledované mená / firmy (oddeľ čiarkou)…" style="flex:1;margin:0;width:auto" oninput="saveState();render()">
    <label class="chip"><input type="checkbox" id="onlywatch" onchange="saveState();render()"> len sledované</label>
  </div>
  <div class="row"><span class="small">Rýchly filter:</span>
    <button class="mini" onclick="preset('stat')">🏛️ Štát a š. p.</button>
    <button class="mini" onclick="preset('samo')">🏘️ Samospráva</button>
    <button class="mini" onclick="preset('hival')">💶 Nad 1 mil. €</button>
    <button class="mini" onclick="preset('dnes')">📅 Dnes</button>
    <button class="mini" onclick="preset('reset')">↺ Zrušiť filtre</button>
  </div>
  <div class="row"><span class="small">Pohľad:</span>
    <button class="mini" onclick="shareView()">🔗 Zdieľať / uložiť</button>
    <button class="mini" onclick="exportCsv()">⬇️ Export CSV</button>
  </div>
  <div class="row" id="subrow"><span class="small">Zobraziť:</span>
    <label class="chip"><input type="checkbox" class="src" value="parlament" checked onchange="render()"> Parlament</label>
    <label class="chip"><input type="checkbox" class="src" value="vlada" checked onchange="render()"> Vláda</label>
    <label class="chip"><input type="checkbox" class="src" value="uvo" checked onchange="render()"> Zákazky</label>
    <label class="chip"><input type="checkbox" class="src" value="zmluvy" checked onchange="render()"> Zmluvy (CRZ)</label>
    <label class="chip"><input type="checkbox" class="src" value="mpk" checked onchange="render()"> MPK</label>
    <label class="chip"><input type="checkbox" class="src" value="kontrolne" checked onchange="render()"> Kontrolné úrady</label>
  </div>
  <details class="cats"><summary>Témy (centrálny filter — platí pre všetky záložky)</summary>
   <div class="row" style="margin-top:6px"><button class="mini" onclick="allCats(true)">všetky</button> <button class="mini" onclick="allCats(false)">žiadne</button></div>
   <div class="row" id="cats">__CATS__</div>
  </details>
 </div>
 <div id="stat" class="seg"></div>
 <div id="wprep"></div>
 <div id="list"></div>
</div>
<div id="toast"></div>
<script>
const DATA=__DATA__, CATS=__CATSORDER__;
const TABS=[['novinky','Novinky'],['parlament','Parlament'],['mpk','MPK'],['vlada','Vláda'],['uvo','Zákazky'],['zmluvy','Zmluvy'],['kontrolne','Kontrolné inštitúcie'],['vsetko','Všetko']];
const SRCL={parlament:'Parlament',mpk:'MPK',vlada:'Vláda',uvo:'Zákazky',zmluvy:'Zmluva',kontrolne:'Kontrola'};
let TAB='novinky';
const LOAD={};  // tab -> počet dní zobrazeného okna
const MAXW={parlament:7,mpk:7,vlada:7,uvo:7,zmluvy:7,kontrolne:7,vsetko:7};
function defWin(t){return 2;}
function sel(cls){return [...document.querySelectorAll('.'+cls+':checked')].map(e=>e.value)}
function allCats(v){document.querySelectorAll('#cats input').forEach(e=>e.checked=v);render()}
function esc(s){return (s||'').replace(/"/g,'&quot;')}
function parseWatch(){return (document.getElementById('watch').value||'').toLowerCase().split(',').map(s=>s.trim()).filter(Boolean);}
function isWatched(it){const w=parseWatch();if(!w.length)return false;const t=((it.full||'')+' '+(it.info||'')+' '+(it.h||'')).toLowerCase();return w.some(x=>t.includes(x));}
function watchSummary(){
 const w=parseWatch(); if(!w.length) return '';
 let rows='';
 for(const term of w){
  const items=DATA.filter(it=>((it.full||'')+' '+(it.info||'')+' '+(it.h||'')).toLowerCase().includes(term));
  if(!items.length) continue;
  const bySrc={}; let sum=0;
  for(const it of items){bySrc[it.source]=(bySrc[it.source]||0)+1; sum+=sumaNum(it.suma);}
  const parts=Object.keys(bySrc).map(s=>bySrc[s]+'× '+(SRCL[s]||s));
  const sumStr = sum>0 ? ' · spolu <b>'+sum.toLocaleString('sk-SK')+' €</b>' : '';
  rows+=`<div class="wsum"><b>⭐ ${term}</b> — ${items.length} záznamov (${parts.join(', ')})${sumStr}</div>`;
 }
 return rows?`<div class="wbox"><div class="wsum-h">Prepojenia sledovaných (za posledných 7 dní):</div>${rows}</div>`:'';
}
function saveState(){try{localStorage.setItem('skmon',JSON.stringify({w:document.getElementById('watch').value,o:document.getElementById('onlywatch').checked,t:TAB}));}catch(e){}}
let HIVAL=false, DNES=false;
function sumaNum(s){const m=(s||'').replace(/\s/g,'').match(/([0-9]+(?:[.,][0-9]+)?)/);return m?parseFloat(m[1].replace(',','.')):0;}
function preset(p){
 const cb=[...document.querySelectorAll('#cats input')];
 if(p==='stat'){cb.forEach(e=>e.checked=(e.value==='Štát a štátne podniky'));}
 else if(p==='samo'){cb.forEach(e=>e.checked=(e.value==='Samospráva'));}
 else if(p==='hival'){HIVAL=!HIVAL;}
 else if(p==='dnes'){DNES=!DNES;}
 else if(p==='reset'){cb.forEach(e=>e.checked=true);HIVAL=false;DNES=false;document.getElementById('onlywatch').checked=false;document.getElementById('q').value='';}
 saveState();render();
}
function toast(msg){const el=document.getElementById('toast');el.textContent=msg;el.style.opacity='1';clearTimeout(el._t);el._t=setTimeout(()=>{el.style.opacity='0';},2600);}
function shareView(){
 const off=[...document.querySelectorAll('#cats input')].filter(e=>!e.checked).map(e=>e.value);
 const p=new URLSearchParams();
 const w=document.getElementById('watch').value.trim(); if(w)p.set('w',w);
 if(document.getElementById('onlywatch').checked)p.set('o','1');
 const q=document.getElementById('q').value.trim(); if(q)p.set('q',q);
 if(TAB&&TAB!=='novinky')p.set('tab',TAB);
 if(HIVAL)p.set('hv','1'); if(DNES)p.set('dn','1');
 if(off.length)p.set('off',off.join('~'));
 location.hash=p.toString();
 const url=location.href;
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(url).then(()=>toast('Odkaz na tvoj pohľad skopírovaný do schránky'),()=>toast('Odkaz máš v adresnom riadku (skopíruj ho)'));}
 else toast('Odkaz máš v adresnom riadku (skopíruj ho)');
}
function exportCsv(){
 const rows=baseFilter();
 const q=s=>'"'+String(s==null?'':s).replace(/"/g,'""')+'"';
 const head=['Zdroj','Dátum','Kategória','Nadpis','Suma','Stav','Info','Odkaz'];
 const lines=[head.join(';')];
 for(const it of rows){lines.push([SRCL[it.source]||it.source,it.date,it.category,it.full||it.h,it.suma,it.stav,it.info,it.url].map(q).join(';'));}
 const blob=new Blob(['﻿'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='sk-monitor.csv';document.body.appendChild(a);a.click();a.remove();
 toast(rows.length+' záznamov exportovaných do CSV');
}
function applyHash(){
 if(!location.hash||location.hash.length<2)return false;
 const p=new URLSearchParams(location.hash.slice(1));
 if(p.has('w'))document.getElementById('watch').value=p.get('w');
 document.getElementById('onlywatch').checked=(p.get('o')==='1');
 if(p.has('q'))document.getElementById('q').value=p.get('q');
 if(p.has('tab'))TAB=p.get('tab');
 HIVAL=(p.get('hv')==='1'); DNES=(p.get('dn')==='1');
 if(p.has('off')){const off=p.get('off').split('~');[...document.querySelectorAll('#cats input')].forEach(e=>{e.checked=!off.includes(e.value);});}
 return true;
}
function ageDays(d){if(!d)return 99999;return Math.floor((new Date(new Date().toDateString())-new Date(d))/86400000);}
function hoursSince(ts){if(!ts)return 1e9;const t=new Date(ts);if(isNaN(t))return 1e9;return (Date.now()-t.getTime())/3600000;}
function relDate(d){const dd=ageDays(d);if(dd<=0)return'dnes';if(dd===1)return'včera';if(dd<7)return'pred '+dd+' dňami';return d;}
function isNew(it){return hoursSince(it.fs)<=12;}
function isNova(it){if(!it.vznik)return false;const d=(Date.now()-new Date(it.vznik).getTime())/86400000;return d>=0 && d<365;}
function dayLabel(d){const dd=ageDays(d);if(dd<=0)return'Dnes';if(dd===1)return'Včera';const D=new Date(d);return D.toLocaleDateString('sk-SK',{weekday:'long',day:'numeric',month:'long'});}
function card(it){
 const w=isWatched(it);
 const watchHtml=w?`<span class="badge b-watch">⭐ sledované</span>`:'';
 const sumaHtml=it.suma?`<span class="badge b-suma">💶 ${it.suma}</span>`:'';
 const newHtml=isNew(it)?`<span class="badge b-new">NOVÉ</span>`:'';
 const chgHtml=(it.chg && ageDays(it.chg)<=3)?`<span class="badge b-chg">🔄 zmena stavu</span>`:'';
 const novaHtml=isNova(it)?`<span class="badge b-nova" title="Firma vznikla ${it.vznik}">⚠️ nová firma</span>`:'';
 const zahrHtml=(it.krajina && it.krajina!=='Slovenská republika')?`<span class="badge b-zahr" title="Sídlo: ${it.krajina}">🌍 sídlo mimo SR</span>`:'';
 const stavHtml=it.stav?` · stav: ${it.stav}`:'';
 const hh=it.url?`<a class="title" href="${it.url}" target="_blank" title="${esc(it.full)}">${it.h||it.full}</a>`:`<span class="title">${it.h||it.full}</span>`;
 const popisHtml=it.popis?`<div class="desc">${it.popis}</div>`:'';
 const de=encodeURIComponent(it.overit||'');
 const regHtml=(it.source==='zmluvy'&&it.overit)?`<div class="regl">preveriť ${it.overit}: <a href="https://www.orsr.sk/hladaj_subjekt.asp?OBMENO=${de}&PF=0&SID=0&S=on&R=on" target="_blank">ORSR</a> · <a href="https://finstat.sk/hladaj?q=${de}" target="_blank">FinStat</a> · <a href="https://rpvs.gov.sk/rpvs" target="_blank">RPVS</a></div>`:'';
 return `<div class="card ${it.source}${w?' watched':''}"><div class="chead"><span class="srcpill ${it.source}">${SRCL[it.source]||it.source}</span> ${watchHtml} ${sumaHtml} ${novaHtml} ${zahrHtml} ${newHtml} ${chgHtml} <span class="cdate">${relDate(it.date)}</span></div>${hh}${popisHtml}<div class="facts">${it.info||''}${stavHtml}</div>${regHtml}</div>`;
}
function baseFilter(){
 const q=document.getElementById('q').value.toLowerCase();
 const csel=sel('catcb');
 const only=document.getElementById('onlywatch').checked;
 return DATA.filter(it=>{
  if(!csel.includes(it.category))return false;
  if(only && !isWatched(it))return false;
  if(HIVAL && sumaNum(it.suma) < 1000000)return false;
  if(DNES && ageDays(it.date) > 0)return false;
  if(q){const txt=((it.h||'')+' '+(it.full||'')+' '+(it.info||'')+' '+it.category).toLowerCase();if(!txt.includes(q))return false;}
  return true;
 });
}
function setTab(t){TAB=t;saveState();window.scrollTo(0,0);render();}
function more(){LOAD[TAB]=Math.min((LOAD[TAB]||defWin(TAB))+2,MAXW[TAB]||7);render();}
function renderTabs(base){
 const cnt={};for(const it of base)cnt[it.source]=(cnt[it.source]||0)+1;
 const nov=base.filter(it=>ageDays(it.date)<=1).length;
 document.getElementById('tabs').innerHTML=TABS.map(function(t){
  const id=t[0], lbl=t[1];
  const c = id==='novinky'?nov : id==='vsetko'?base.length : (cnt[id]||0);
  return `<button class="tab ${TAB===id?'active':''}" onclick="setTab('${id}')">${lbl}<span class="tcount">${c}</span></button>`;
 }).join('');
}
function render(){
 const base=baseFilter();
 renderTabs(base);
 document.getElementById('wprep').innerHTML=watchSummary();
 document.getElementById('subrow').style.display = TAB==='novinky' ? 'flex':'none';
 let list, out='', note='';
 if(TAB==='novinky'){
  const srcs=sel('src');
  list=base.filter(it=>ageDays(it.date)<=1 && srcs.includes(it.source));
  list.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
  out = list.length?('<div class="secbody">'+list.map(card).join('')+'</div>'):'<p class="small">Za posledné 2 dni zatiaľ nič nové.</p>';
  document.getElementById('stat').innerHTML=`Novinky (za posledné 2 dni): <b>${list.length}</b>`;
  document.getElementById('list').innerHTML=out; return;
 }
 const maxw=MAXW[TAB]||7;
 const win=LOAD[TAB]||defWin(TAB);
 list = (TAB==='vsetko') ? base.slice() : base.filter(it=>it.source===TAB);
 list.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
 const total=list.length;
 const shown=list.filter(it=>ageDays(it.date)<=win);
 if(TAB==='vsetko'){
  let lastDay=null;
  for(const it of shown){const dl=dayLabel(it.date);if(dl!==lastDay){out+=`<div class="daydiv">${dl}</div>`;lastDay=dl;}out+=card(it);}
  if(!out)out='<p class="small">Nič nezodpovedá filtru.</p>';
 } else {
  out = shown.length?('<div class="secbody">'+shown.map(card).join('')+'</div>'):'<p class="small">Za posledných 7 dní nič — pozri záložku Všetko alebo zmeň filter.</p>';
 }
 if(win<maxw && shown.length<total){ note=`<button class="loadmore" onclick="more()">▾ Načítať staršie (+2 dni)</button>`; }
 else { note=`<div class="endnote">— Prehľad udalostí za posledných ${maxw} dní. —</div>`; }
 document.getElementById('stat').innerHTML=`Zobrazené: <b>${shown.length}</b> z ${total} (za posledných ${Math.min(win,maxw)} dní)`;
 document.getElementById('list').innerHTML=out+note;
}
(function initState(){let fromHash=false;try{fromHash=applyHash();}catch(e){}if(!fromHash){try{const s=JSON.parse(localStorage.getItem('skmon')||'{}');if(s.w)document.getElementById('watch').value=s.w;if(s.o)document.getElementById('onlywatch').checked=true;if(s.t&&TABS.some(t=>t[0]===s.t))TAB=s.t;}catch(e){}}})();
render();
</script>
</body></html>"""
    tmpl = tmpl.replace("__CATS__", cat_chips).replace("__DATA__", data_js).replace("__CATSORDER__", cats_js).replace("__UPDATED__", ISO)
    open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8").write(tmpl)

if __name__ == "__main__":
    main()
