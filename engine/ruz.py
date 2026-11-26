#!/usr/bin/env python3
# SKMON-PUBLIC (kód; výstupy o konkrétnych subjektoch patria do súkromnej vrstvy)
"""
engine/ruz.py — klient Registra účtovných závierok (RÚZ Open API, registeruz.sk).

Licencia dát: CC0 (verejná doména). API bez autentifikácie.
Reťazec: ico -> uctovna-jednotka -> uctovna-zavierka(roky) -> uctovny-vykaz(Súvaha+VZaS).

METODICKÁ POZNÁMKA (dôležité, čítaj pred interpretáciou výstupu):
  - `cisty_obrat` / `vynosy` = ÚČTOVNE VYKÁZANÉ tržby za účtovné obdobie. NIE sú to platby od štátu.
  - Hodnota zmlúv z CRZ = ZMLUVNÝ záväzok (často viacročný / rámcový), NIE ročná platba.
  - Preto "objem CRZ zmlúv / ročný obrat" je len HRUBÝ PROXY, nie podiel príjmov firmy od štátu.
    Vždy ho označuj ako proxy s obmedzeniami (viď financial.py / financial.yaml).
  - Štruktúrované dáta (Súvaha/VZaS) NIE sú dostupné pre každého: IFRS a konsolidované závierky
    a historické roky 2009–2012 bývajú len ako PDF prílohy (pristupnostDat="Verejné prílohy").
    Takéto roky vraciame s financie=None a dovodom, nie ako nulové hodnoty.
  - Počet zamestnancov NIE je v štruktúrovaných dátach (len v poznámkach/PDF). Namiesto headcountu
    používame OSOBNÉ NÁKLADY (mzdy) ako lepší, dostupný proxy veľkosti prevádzky.

Použitie:
  python3 engine/ruz.py <ICO>                 # profil jednej firmy (JSON na stdout)
  python3 engine/ruz.py --selftest            # offline test parsera (bez siete)
  python3 engine/ruz.py --batch <store.json> <out.json> [max]   # pre top dodávateľov zo store
"""
import json, sys, os, time, re, unicodedata, urllib.request, urllib.parse, urllib.error

API = "https://www.registeruz.sk/cruz-public/api"
UA = {"User-Agent": "sk-monitor/ruz (public-interest research; registeruz CC0)"}
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache_ruz")
TPL_CACHE = {}  # idSablony -> template dict (pamäť počas behu)

# --- Normalizácia textu pre párovanie riadkov výkazu ---
def _norm(s):
    s = (s or "").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))  # odstráň diakritiku
    s = re.sub(r"\s+", " ", s)
    return s.strip()

# Kotvy: kanonický metrika -> (názov tabuľky obsahuje, text riadku začína/obsahuje, ktorý dátový stĺpec)
# col: index dátového stĺpca v riadku. Pre VZaS/pasíva (2 stĺpce): 0=bežné. Pre aktíva (4): 2=netto bežné.
ANCHORS = {
    "cisty_obrat":   ("ziskov",   "cisty obrat",                                 0),
    "vynosy_hc":     ("ziskov",   "vynosy z hospodarskej cinnosti spolu",        0),
    "vysledok_po_dani": ("ziskov", "vysledok hospodarenia za uctovne obdobie po zdaneni", 0),
    "pridana_hodnota": ("ziskov", "pridana hodnota",                             0),
    "osobne_naklady": ("ziskov",  "osobne naklady",                              0),
    "mzdove_naklady": ("ziskov",  "mzdove naklady",                              0),
    "aktiva_spolu":  ("aktiv",    "spolu majetok",                               2),
    "vlastne_imanie": ("pasiv",   "vlastne imanie r.",                           0),
    "zavazky":       ("pasiv",    "zavazky r.",                                  0),
}

def _get(url, tries=4, sleep=0.5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(sleep * (i + 1))
    raise RuntimeError(f"RÚZ API zlyhalo: {url} :: {last}")

def _q(path, **params):
    return f"{API}/{path}?" + urllib.parse.urlencode(params)

def entity_id_for_ico(ico):
    """ico -> id účtovnej jednotky (alebo None)."""
    d = _get(_q("uctovne-jednotky", **{"zmenene-od": "2000-01-01", "ico": str(ico)}))
    ids = (d or {}).get("id") or []
    return ids[0] if ids else None

def entity_detail(uj_id):
    return _get(_q("uctovna-jednotka", id=uj_id))

def zavierka(z_id):
    return _get(_q("uctovna-zavierka", id=z_id))

def vykaz(v_id):
    return _get(_q("uctovny-vykaz", id=v_id))

def sablona(s_id):
    if s_id in TPL_CACHE:
        return TPL_CACHE[s_id]
    os.makedirs(CACHE_DIR, exist_ok=True)
    fp = os.path.join(CACHE_DIR, f"tpl_{s_id}.json")
    if os.path.exists(fp):
        try:
            t = json.load(open(fp, encoding="utf-8")); TPL_CACHE[s_id] = t; return t
        except Exception:
            pass
    t = _get(_q("sablona", id=s_id))
    if t:
        TPL_CACHE[s_id] = t
        try:
            json.dump(t, open(fp, "w", encoding="utf-8"))
        except Exception:
            pass
    return t

def _extract_from_vykaz(v, tpl):
    """Zo štruktúrovaného výkazu + jeho šablóny vytiahni kanonické metriky.
    Vracia dict metrika->hodnota(float) pre tie, ktoré sa našli."""
    out = {}
    obsah = (v or {}).get("obsah") or {}
    tabs = obsah.get("tabulky") or []
    tpl_tabs = (tpl or {}).get("tabulky") or []
    if not tabs or not tpl_tabs:
        return out
    # spáruj tabuľky výkazu so šablónou podľa poradia (RÚZ ich drží v rovnakom poradí)
    for ti, tab in enumerate(tabs):
        if ti >= len(tpl_tabs):
            break
        tpl_tab = tpl_tabs[ti]
        ncols = tpl_tab.get("pocetDatovychStlpcov") or 1
        riadky = tpl_tab.get("riadky") or []
        data = tab.get("data") or []
        tname = _norm((tab.get("nazov") or {}).get("sk"))
        for metric, (tkey, rkey, col) in ANCHORS.items():
            if metric in out:
                continue
            if tkey not in tname:
                continue
            for ri, rr in enumerate(riadky):
                rtext = _norm((rr.get("text") or {}).get("sk"))
                if rkey in rtext:
                    idx = ri * ncols + col
                    if 0 <= idx < len(data):
                        raw = (data[idx] or "").strip()
                        if raw not in ("", "-"):
                            try:
                                out[metric] = float(raw)
                            except ValueError:
                                pass
                    break
    return out

def financie_za_rok(z):
    """Pre jednu závierku vráti ročné financie alebo dôvod nedostupnosti."""
    rok = None
    od = z.get("obdobieDo") or z.get("obdobieOd") or ""
    m = re.match(r"(\d{4})", od)
    if m: rok = int(m.group(1))
    res = {"rok": rok, "obdobie_od": z.get("obdobieOd"), "obdobie_do": z.get("obdobieDo"),
           "typ": z.get("typ"), "konsolidovana": z.get("konsolidovana"),
           "id_zavierky": z.get("id"), "financie": None, "dovod": None, "metriky": {}}
    best = {}
    stav = None
    for vid in (z.get("idUctovnychVykazov") or []):
        v = vykaz(vid)
        if not v:
            continue
        pd = v.get("pristupnostDat")
        if (v.get("obsah") or {}).get("tabulky"):
            tpl = sablona(v.get("idSablony"))
            got = _extract_from_vykaz(v, tpl)
            # uprednostni výkaz s čistým obratom / výnosmi (VZaS) a aktívami (Súvaha)
            for k, val in got.items():
                best.setdefault(k, val)
        else:
            stav = stav or pd  # napr. "Verejné prílohy" (len PDF/IFRS)
    if best:
        res["metriky"] = best
        res["financie"] = {
            "cisty_obrat": best.get("cisty_obrat"),
            "vynosy": best.get("vynosy_hc"),
            "vysledok_po_dani": best.get("vysledok_po_dani"),
            "pridana_hodnota": best.get("pridana_hodnota"),
            "osobne_naklady": best.get("osobne_naklady"),
            "mzdove_naklady": best.get("mzdove_naklady"),
            "aktiva_spolu": best.get("aktiva_spolu"),
            "vlastne_imanie": best.get("vlastne_imanie"),
            "zavazky": best.get("zavazky"),
        }
    else:
        res["dovod"] = (f"štruktúrované dáta nedostupné ({stav or 'bez obsahu'}) — "
                        f"IFRS/konsolidovaná/historická závierka len ako PDF")
    return res

def profil_firmy(ico, max_rokov=12, sleep=0.3):
    """Hlavná funkcia: finančný profil firmy podľa IČO (časový rad + metadáta)."""
    uj_id = entity_id_for_ico(ico)
    if not uj_id:
        return {"ico": str(ico), "najdene": False, "dovod": "IČO nie je v RÚZ"}
    d = entity_detail(uj_id) or {}
    rady = []
    zids = d.get("idUctovnychZavierok") or []
    # zoberieme najnovšie roky — závierky nie sú zoradené, stiahneme hlavičky a utriedime
    heads = []
    for zid in zids:
        z = zavierka(zid)
        if z: heads.append(z)
        time.sleep(sleep)
    heads.sort(key=lambda z: (z.get("obdobieDo") or ""), reverse=True)
    for z in heads[:max_rokov]:
        rady.append(financie_za_rok(z))
        time.sleep(sleep)
    # odvodené časové signály (len ekonomická deskripcia, nie hodnotenie)
    obraty = [(r["rok"], r["financie"]["cisty_obrat"] or r["financie"]["vynosy"])
              for r in rady if r.get("financie") and (r["financie"].get("cisty_obrat") or r["financie"].get("vynosy"))]
    obraty = [(y, v) for y, v in obraty if y and v]
    obraty.sort()
    return {
        "ico": str(ico),
        "najdene": True,
        "nazov": d.get("nazovUJ"),
        "datum_zalozenia": d.get("datumZalozenia"),
        "pravna_forma": d.get("pravnaForma"),
        "sk_nace": d.get("skNace"),
        "velkost_organizacie": d.get("velkostOrganizacie"),
        "druh_vlastnictva": d.get("druhVlastnictva"),
        "konsolidovana": d.get("konsolidovana"),
        "pocet_zavierok": len(zids),
        "rokov_so_strukt_datami": sum(1 for r in rady if r.get("financie")),
        "casovy_rad": rady,
        "obrat_rad": obraty,  # [(rok, obrat)] vzostupne — pre temporálnu analytiku
        "zdroj": "RÚZ registeruz.sk (CC0)",
        "metodicka_poznamka": "Obrat = účtovne vykázané tržby, NIE platby od štátu.",
    }

# ---------------- OFFLINE SELFTEST (bez siete) ----------------
def _selftest():
    # Syntetická šablóna a výkaz s reálnymi číslami Slovanetu (overenie indexovej matematiky a kotiev)
    tpl = {"tabulky": [
        {"nazov": {"sk": "Strana aktív"}, "pocetDatovychStlpcov": 4,
         "riadky": [{"text": {"sk": "SPOLU MAJETOK r. 02 + r. 33 + r. 74"}}]},
        {"nazov": {"sk": "Strana pasív"}, "pocetDatovychStlpcov": 2,
         "riadky": [{"text": {"sk": "SPOLU VLASTNÉ IMANIE A ZÁVÄZKY"}},
                    {"text": {"sk": "Vlastné imanie r. 81 + ..."}},
                    {"text": {"sk": "Záväzky r. 102 + ..."}}]},
        {"nazov": {"sk": "Výkaz ziskov a strát"}, "pocetDatovychStlpcov": 2,
         "riadky": [{"text": {"sk": "Čistý obrat (časť účt. tr. 6 podľa zákona)"}},
                    {"text": {"sk": "Výnosy z hospodárskej činnosti spolu súčet"}},
                    {"text": {"sk": "Osobné náklady (r. 16 až r. 19)"}},
                    {"text": {"sk": "Mzdové náklady (521, 522)"}},
                    {"text": {"sk": "Výsledok hospodárenia za účtovné obdobie po zdanení (+/-)"}}]},
    ]}
    v = {"obsah": {"tabulky": [
        {"nazov": {"sk": "Strana aktív"}, "data": ["142309743", "100787458", "41522285", "41839138"]},
        {"nazov": {"sk": "Strana pasív"}, "data": ["41522285", "41839138", "8724830", "6372358", "29998962", "31892121"]},
        {"nazov": {"sk": "Výkaz ziskov a strát"},
         "data": ["69986102", "51099475", "70681972", "51626436",
                  "3971712", "-497576", "2906204", "2737196", "2352472", "-1357680"]},
    ]}}
    got = _extract_from_vykaz(v, tpl)
    exp = {"cisty_obrat": 69986102.0, "vynosy_hc": 70681972.0, "vysledok_po_dani": 2352472.0,
           "osobne_naklady": 3971712.0, "mzdove_naklady": 2906204.0,
           "aktiva_spolu": 41522285.0, "vlastne_imanie": 8724830.0, "zavazky": 29998962.0}
    ok = True
    for k, ev in exp.items():
        av = got.get(k)
        flag = "OK" if av == ev else "!!"
        if av != ev: ok = False
        print(f"  [{flag}] {k}: got={av} exp={ev}")
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    if argv[0] == "--selftest":
        return _selftest()
    if argv[0] == "--batch":
        store_path, out_path = argv[1], argv[2]
        maxn = int(argv[3]) if len(argv) > 3 else 25
        store = json.load(open(store_path, encoding="utf-8"))
        # pozbieraj IČO top dodávateľov podľa objemu zmlúv
        from collections import defaultdict
        objem = defaultdict(float); ico_of = {}
        for it in store.get("items", store if isinstance(store, list) else []):
            ico = it.get("dod_ico");
            if not ico: continue
            nm = it.get("dodavatel") or ""
            try: s = float(it.get("suma") or 0)
            except Exception: s = 0
            objem[ico] += s; ico_of[ico] = nm
        top = sorted(objem.items(), key=lambda kv: kv[1], reverse=True)[:maxn]
        res = {"SKMON-PRIVATE-DO-NOT-PUBLISH": True, "zdroj": "RÚZ (CC0)", "firmy": []}
        for ico, _s in top:
            try:
                p = profil_firmy(ico)
                p["crz_objem_zmluv"] = round(objem[ico])
                res["firmy"].append(p)
                print(f"  {ico} {ico_of.get(ico,'')[:40]}: rokov_data={p.get('rokov_so_strukt_datami')}", file=sys.stderr)
            except Exception as e:
                res["firmy"].append({"ico": ico, "chyba": str(e)})
        json.dump(res, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"Zapísané: {out_path} ({len(res['firmy'])} firiem)")
        return 0
    # inak: jedno IČO
    ico = argv[0]
    print(json.dumps(profil_firmy(ico), ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
