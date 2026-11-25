#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — generátor investigatívneho prehľadu (engine).
Z findings/risk_scored.json urobí čitateľný markdown: top nálezy, dôkazy, preklik na registre.
Výstup je SÚKROMNÝ (menuje subjekty) — patrí do sk-monitor-intelligence/findings/.
Použitie: python report.py findings/risk_scored.json findings/report.md
"""
import json, sys, urllib.parse, datetime

LABEL = {
 "SK-SUP-NEW":"🆕 nová firma (<1 rok)",
 "SK-SUP-FOREIGN":"🌍 sídlo mimo SR",
 "SK-HIGHVALUE":"💶 vysoká suma (nad 90. percentil kategórie)",
 "SK-COMBO":"⚠️ kombinácia (vysoká suma + riziková firma)",
 "SK-BUYER-CONC":"🔁 opakovaný víťaz (>50 % zmlúv obstarávateľa)",
 "SK-MARKET-HHI":"📊 koncentrovaný trh (HHI)",
 "SK-OWN-PUBOFFICIAL":"🏛️ vlastník je verejný činiteľ",
 "SK-OWN-FOREIGN-KUV":"🌐 zahraničný konečný užívateľ výhod",
 "SK-OWN-CHALLENGED":"❗ napadnuté vlastníctvo (kvalifikovaný podnet)",
 "SK-OWN-NO-KUV":"🫥 bez aktívneho konečného užívateľa výhod",
 "SK-OWN-SHARED":"🔗 spoločný vlastník s iným dodávateľom",
}
EV = {
 "vek_firmy_dni":"vek firmy (dni)","krajina":"krajina sídla","suma":"suma (€)",
 "p90_kategorie":"90. percentil kategórie (€)","podiel_u_obstaravatela":"podiel u obstarávateľa",
 "pocet_zmluv_dvojice":"počet zmlúv dvojice","obstaravatel":"obstarávateľ","hhi_kategorie":"HHI kategórie",
 "kuv_verejny_cinitel":"KÚV verejný činiteľ","kuv_zahranicny":"KÚV zahraničný",
 "pocet_podnetov":"počet kvalifikovaných podnetov","spolocny_vlastnik_s":"spoločný vlastník s",
}

def links(dod, ico):
    q = urllib.parse.quote(dod or "")
    orsr = f"https://www.orsr.sk/hladaj_subjekt.asp?OBMENO={q}&PF=0&SID=0&S=on&R=on"
    fin  = f"https://finstat.sk/hladaj?q={q}"
    rpvs = f"https://rpvs.gov.sk/rpvs/Partner" + (f" (IČO {ico})" if ico else "")
    out = f"[ORSR]({orsr}) · [FinStat]({fin}) · RPVS"
    if ico: out += f" (IČO {ico})"
    return out

def main():
    src = sys.argv[1] if len(sys.argv)>1 else "findings/risk_scored.json"
    out = sys.argv[2] if len(sys.argv)>2 else "findings/report.md"
    topn = int(sys.argv[3]) if len(sys.argv)>3 else 40
    d = json.load(open(src, encoding="utf-8"))
    items = d.get("items", [])
    s = d.get("summary", {})
    L = []
    L.append("# SK monitor — investigatívny prehľad (SÚKROMNÉ)\n")
    L.append("> Pracovné podozrenia na preverenie. NIE sú to potvrdené tvrdenia. Pred akýmkoľvek")
    L.append("> verejným zverejnením je nutné ľudské overenie z primárnych zdrojov.\n")
    L.append(f"Vygenerované: {datetime.datetime.utcnow().isoformat()}Z  ·  "
             f"položiek: {s.get('polozky','?')}  ·  označených: {s.get('oznacenych','?')}  ·  "
             f"RPVS overených: {s.get('rpvs_overenych','?')}\n")
    L.append("## Rozdelenie podľa príznaku\n")
    counts = {}
    for it in items:
        for f in set(it.get("flags",[])): counts[f]=counts.get(f,0)+1
    for f,c in sorted(counts.items(), key=lambda x:-x[1]):
        L.append(f"- {LABEL.get(f,f)} — **{c}**")
    L.append(f"\n## Top {topn} nálezov podľa skóre\n")
    for it in items[:topn]:
        L.append(f"### [{it.get('skore')}] {it.get('dod') or '—'}")
        L.append(f"*{it.get('kategoria','')}* · {it.get('date','')}  ")
        L.append("Príznaky: " + ", ".join(LABEL.get(f,f) for f in it.get("flags",[])) + "  ")
        ev = it.get("dokaz",{})
        if ev:
            parts = []
            for k,v in ev.items():
                parts.append(f"{EV.get(k,k)}: {', '.join(map(str,v)) if isinstance(v,list) else v}")
            L.append("Dôkaz: " + "; ".join(parts) + "  ")
        L.append("Preveriť: " + links(it.get("dod"), it.get("ico")) + "  ")
        if it.get("url"): L.append(f"Zdroj: {it['url']}  ")
        L.append("")
    open(out,"w",encoding="utf-8").write("\n".join(L))
    print(f"Prehľad zapísaný: {out} ({len(items[:topn])} nálezov)")

if __name__ == "__main__":
    main()
