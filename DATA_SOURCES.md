# Dátové zdroje SK monitoru

Register oficiálnych zdrojov. Každý zdroj má uvedený endpoint, formát, licenciu, periodicitu,
rozsah pokrytia a spôsob monitorovania funkčnosti. Zásada: **len oficiálne zdroje, žiadne obchádzanie
bezpečnostných mechanizmov (WAF, CAPTCHA), žiadne médiá ako primárny zdroj.**

Stav zdrojov je strojovo sledovaný v `data/health.json` (stavy: `ok_fresh`, `ok_no_new`, `partial`,
`down`, `stale`) a perzistentne v `data/source_health.json` (posledná úspešná aktualizácia per zdroj).

## Aktívne zdroje

| Zdroj | Endpoint | Formát | Licencia | Periodicita | Pokrytie |
|---|---|---|---|---|---|
| **uvo** – Verejné obstarávanie | uvo.gov.sk/vyhladavanie-zakaziek | HTML | otvorené dáta ÚVO | priebežne | zákazky, obstarávatelia, stav, CPV, sumy |
| **zmluvy** – Centrálny register zmlúv | crz.gov.sk | HTML | zák. 211/2000 | priebežne | zmluvy nad prahom, dodávateľ, objednávateľ, suma |
| **mpk** – Medzirezortné pripomienkovanie | vyhladavanie.slov-lex.sk/rss/legislativnyMaterial | RSS/XML | Slov-Lex otvorené | priebežne | legislatívne materiály v MPK (LP/PI), rezort |
| **vlada** – Rokovania vlády | rokovania.gov.sk/RVL/Material | HTML | otvorené dáta | priebežne | materiály vlády, UV čísla, dátum |
| **kontrolne** – NKÚ výsledky kontrol | nku.gov.sk/datasety → `zoznam_vysledkov_kontrol_*.json` | JSON | otvorené dáta NKÚ | kvartálne | kontrolovaný subjekt, popis, číslo KA, dátum, link na dokument |

### Pozn. ku kontrolným inštitúciám (NKÚ)
- Primárny zdroj je **oficiálny otvorený dataset** NKÚ (nie RSS — RSS kanál `…/journal/rss/33855/1300577`
  je prakticky prázdny, obsahuje len testovaciu položku z 2023).
- NKÚ publikuje aj bohatší dataset **„Kontrolné zistenia"** (CSV/XML/JSON, ~50 MB) a
  **„Zoznam kontrolovateľných subjektov"** — plánované pre investigatívny engine (prepojenie
  zistenie → subjekt → zákazka → zmluva → dodávateľ → suma → nápravné opatrenie).
- Kvartálna periodicita znamená oneskorenie max. ~3 mesiace; health-check to reflektuje stavom `stale`,
  nie `down`.

## Zdroj mimo prevádzky / riešený

### parlament (NR SR) — nrsr.sk
- **Problém:** okolo júla 2026 pribudol na `nrsr.sk` **WAF**, ktorý blokuje automatizované requesty
  (prehliadač dáta vidí, serverový fetch dostane 4xx). Ostatné vládne weby (rokovania, ÚVO, Slov-Lex,
  CRZ) fungujú — blok je špecifický pre nrsr.sk.
- **Rozhodnutie:** WAF **neobchádzame** (odporuje zásade projektu aj pravidlám). Hľadáme legitímne
  strojovo-čitateľné alternatívy.
- **Preskúmané alternatívy:**
  - `api.parldata.eu/sk/nrsr` (KohoVolit.eu) — **mŕtve** (error page).
  - `data.slovensko.sk` (Národný katalóg otvorených dát) — má JSON API (`POST /datasets/search`);
    NR SR ako poskytovateľ zatiaľ nepotvrdený, treba hlbší prieskum facetov/poskytovateľov.
  - Slov-Lex — funguje, pokrýva legislatívny proces a dokumenty (nie hlasovania poslancov ani výbory).
- **Navrhovaná kombinácia (v riešení):** Slov-Lex (návrhy zákonov + proces + dokumenty + stav)
  + rokovania.gov.sk (vládne návrhy) pre obnoviteľné jadro. Hlasovania poslancov, pozmeňujúce návrhy,
  programy schôdzí a výbory nemajú zatiaľ otvorené rozhranie → (a) pokračovať v prieskume
  data.slovensko.sk, (b) požiadať Kanceláriu NR SR o strojovo-čitateľný export/API.
- **Odolnosť:** počas výpadku sa posledné platné parlamentné položky **nemažú** (prune sa pre
  degradovaný zdroj preskakuje) a stav je označený v health-checku.

## Monitoring funkčnosti
- `data/health.json` sa generuje každým behom; hodnotí zdravie podľa **úspešnosti zberu** (počet
  položiek vrátených zberom tento beh), nie podľa počtu v `store.json`.
- `data/source_health.json` drží poslednú úspešnú aktualizáciu každého zdroja (prežíva medzi behmi).
- Pri výpadku zdroja (0 položiek) sa zdroj označí `down`/`stale`, zachovajú sa posledné dáta a
  zaznamená sa HTTP status / príčina.
