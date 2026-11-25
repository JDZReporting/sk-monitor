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
- **Potvrdená príčina (diagnostika z runnera 25.11.2026):** nrsr.sk vráti HTTP **200** so stránkou
  `title = "Bot Detection"` (challenge, 0× odkaz na zákon). Teda nejde o IP-blok ani parser-bug, ale
  o **systém detekcie botov**. Prekonať ho = obchádzanie detekcie botov → **nerobíme**. Dôsledok:
  ani VPS (datacentrová IP) spoľahlivo nepomôže.
- **Zaznamenané v health-checku:** `parlament.reason = "bot_detection"`, `expected_gap = true`;
  pole `unexpected_down` ho nezahŕňa, takže platforma nehlási falošné „nezdravie", ale medzera je viditeľná.

### Preskúmané alternatívy (stav k 25.11.2026)
| # | Alternatíva | Pokrytie | Náklad/Autonómia | Stav | Záver |
|---|---|---|---|---|---|
| A | Priamy scrape nrsr.sk z Actions | úplné | zadarmo/plná | **bot-detection** | zamietnuté (obchádzanie) |
| B | VPS / non-datacentrum | úplné | €/mes., réžia | datacentrová IP → tá istá detekcia; **neoverené** | neodporúčané |
| C | Dátová spolupráca s parlamentsr.sk (base44) | úplné (vrátane hlasovaní) | zadarmo, závisí od súhlasu | SSR stránky čitateľné; **nescrapujeme bez dohody** | možné po dohode |
| D | Slov-Lex — sledovanie legislatívnych procesov | čiastočné (návrhy+stav, bez hlasovaní) | zadarmo/plná | funguje z Actions | **použiteľné teraz (čiastočne)** |
| E | rokovania.gov.sk (vládne návrhy) | čiastočné (vládna časť) | zadarmo/plná | funguje (zdroj `vlada`) | **už máme** |
| F | Oficiálna žiadosť Kancelárii NR SR | úplné | zadarmo, závisí od úradu | pripravený návrh `NRSR_ziadost_o_data.md` | rezerva (user odložil) |
| G | KohoVolit `scraper-sk_nrsr` | úplné kedysi | — | cieľ (parldata) mŕtvy; scraper narazí na tú istú detekciu | dead-end |

- **Čo vieme získať hneď (autonómne, legitímne):** predparlamentná legislatíva (`mpk`/Slov-Lex),
  vládne návrhy (`vlada`/rokovania). Rozšíriteľné o Slov-Lex sledovanie procesu (D) pre stav návrhov.
- **Čo zatiaľ nevieme autonómne:** hlasovania jednotlivých poslancov, pozmeňujúce návrhy, výbory,
  programy schôdzí — vyžadujú C (dohoda) alebo F (žiadosť).
- **Odolnosť:** počas výpadku sa posledné platné parlamentné položky **nemažú** (prune sa pre
  degradovaný zdroj preskakuje) a stav je označený v health-checku.
- **Roadmap:** parlamentné hlasovania/výbory = blokované detekciou botov na nrsr.sk; odomkne ich len
  dohoda s držiteľom dát (C) alebo oficiálny prístup (F). Priebežne skúmať D (Slov-Lex proces).

## Monitoring funkčnosti
- `data/health.json` sa generuje každým behom; hodnotí zdravie podľa **úspešnosti zberu** (počet
  položiek vrátených zberom tento beh), nie podľa počtu v `store.json`.
- `data/source_health.json` drží poslednú úspešnú aktualizáciu každého zdroja (prežíva medzi behmi).
- Pri výpadku zdroja (0 položiek) sa zdroj označí `down`/`stale`, zachovajú sa posledné dáta a
  zaznamená sa HTTP status / príčina.
