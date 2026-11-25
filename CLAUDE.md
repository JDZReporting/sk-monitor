# CLAUDE.md — trvalé inštrukcie projektu SK monitor

> Tento súbor číta AI asistent na začiatku každej práce na projekte. Udržiava kontext
> naprieč konverzáciami. Keď sa zmení zásadné rozhodnutie, zapíš ho sem.
> Posledná aktualizácia: 2026-11-24.

## 1. Čo je SK monitor a kam smeruje

SK monitor je samo-aktualizujúci sa nástroj, ktorý z **oficiálnych** slovenských zdrojov
monitoruje pohyb verejnej moci a verejných peňazí (parlament, MPK, vláda, ÚVO, CRZ,
kontrolné úrady) a zobrazuje ich na statickom webe zadarmo (GitHub Actions + GitHub Pages).

**Cieľ (ambícia):** vybudovať technologicky špičkovú slovenskú **investigatívnu a analytickú
platformu** — „digitálnu investigatívnu redakciu", ktorá nepretržite analyzuje verejné dáta,
hľadá súvislosti, generuje testovateľné hypotézy a pripravuje podklady pre novinárske
preverenie. AI **nenahrádza** novinára pri rozhodovaní o vine ani pri publikovaní závažných
tvrdení — automatizuje manuálnu prácu pred tým.

## 2. Nemenné princípy (dodržiavať vždy)

1. **Len oficiálne primárne zdroje.** Žiadne médiá ani agregátory ako zdroj zistení.
   Investigatívne články smú slúžiť len na vývoj metodiky, nie ako dôkaz.
2. **Hybridný model publikovania:**
   - **Verejná vrstva** = len oficiálne fakty, preukázané vzťahy, objektívne štatistické
     anomálie, transparentné ukazovatele, finančné analýzy.
   - **Súkromná vrstva** = pokročilé rizikové skóre, pracovné hypotézy, nepotvrdené
     súvislosti, investigatívne spisy, návrhy preverovania.
   - **Súkromná vrstva musí byť technicky oddelená** od verejného webu aj verejného repa
     (nie iba skrytá vo frontende).
3. **Závažné tvrdenie o konkrétnej osobe/firme = ľudské overenie pred verejným publikovaním.**
4. **Ku každému zisteniu dôkaz + odkaz na primárny zdroj** (ideálne strana/pasáž dokumentu).
5. **Rozlišovať hypotézu od faktu.** Ku každej hypotéze uviesť alternatívne (legitímne)
   vysvetlenia a to, čo by ju vyvrátilo.
6. **Merať falošné poplachy.** Pravidlá sa testujú na historických dátach; nové pravidlá
   nesmú samy meniť verejné výstupy bez kontroly.

## 3. Hranice autonómie (dohoda s Jurajom, 2026-11-24)

- **Pracuj samostatne** pri vratných a nízkorizikových krokoch (kód, výskum, prototypy,
  dokumentácia, lokálne súbory). Netreba sa pýtať na každý detail.
- **Konzultuj vopred:** platené služby, zmeny produkčnej architektúry, nové oprávnenia,
  sprístupnenie dát tretím stranám, nezvratné operácie, publikovanie citlivých výstupov.
- **Aktívne upozorňuj,** keď treba niečo nainštalovať/pripojiť/nakonfigurovať — s presným postupom.
- **Výskum musí viesť k funkčným prototypom a merateľným výsledkom**, nie len k dokumentácii.

## 4. Technické prostredie a obmedzenia (zistené 2026-11-24)

- **Nasadenie:** GitHub Actions (cron `0 */3 * * *`) -> `collect.py` -> commit `data/` + `docs/`
  -> GitHub Pages. Repo: `JDZReporting/sk-monitor` (verejné).
- **`docs/` je VEREJNÝ Pages priečinok.** Interné podklady doň NEPATRIA.
- **BEZPEČNOSŤ (dôležité): `.gitignore` NIE JE bezpečnostná hranica** — manuálny upload
  cez GitHub web UI ho ignoruje. Ochrana je FYZICKÁ izolácia: súkromná vrstva je v
  samostatnom priečinku `sk-monitor-intelligence/` MIMO `sk-monitor/` (nikdy sa nenahrá) +
  bezpečnostná brána `tools/security_gate.py`, ktorá beží v GitHub Actions pred commitom
  a lokálne cez `tools/pre_upload_check.sh` pred manuálnym uploadom. Pozri §9.
- **Web search (WebSearch) NIE JE v tomto prostredí dostupný.** Náhrada: prehliadačový panel
  (`mcp__claude-in-chrome__*`) — navigácia na vyhľadávač + čítanie stránok — a `web_fetch`
  na konkrétne URL (zvládne aj extrakciu textu z PDF). Ak sa WebSearch zapne na úrovni účtu,
  výskum bude rýchlejší.
- **Sandbox bash:** Python/Node, ale sieť je allowlistovaná — `curl` na ľubovoľnú doménu
  môže zlyhať (exit 56). Spoľahlivá cesta na získanie webového obsahu je `web_fetch`.
- **Mazanie v pripojenom priečinku** je blokované; použiť `allow_cowork_file_delete`
  (pozor na normalizáciu diakritiky v ceste „Rešerš"). Súborový Write tool na túto cestu
  zlyháva — písať cez bash (`REPO=$(echo /sessions/.../mnt/Re*/sk-monitor)`).
- **Konektory (MCP):** v registri NIE sú žiadne pre obstarávanie/firemné registre/sankcie.
  Dátové zdroje si ťaháme sami (scraping + oficiálne API).

## 5. Kľúčové dátové zdroje a API (overené)

- **OpenSanctions** — sankcie + PEP (politicky exponované osoby). API aj bulk dáta.
  CC-BY-NC; **bezplatný API kľúč pre novinársku/neziskovú/akademickú prácu** (public-interest
  exemption). Zvážiť ako zdroj PEP/sankčných prepojení. https://www.opensanctions.org/docs/api/
- **RPO (Register právnických osôb, Štatistický úrad SR)** — vznik, krajina, IČO. CC-BY.
  Už používané v `collect.py` (`rpo_info`).
- **ORSR / FinStat** — odkazy na preverenie súkromnej strany kontraktu.
- **RPVS (Register partnerov verejného sektora)** — MÁ REST API (OData v4/Swagger):
  https://rpvs.gov.sk/opendatav2/swagger (overené 2026-11-25). Koneční užívatelia výhod
  strojovo → odomyká automatické overenie, spoločných vlastníkov, konflikt záujmov.
  (OPRAVA: skorší predpoklad 'RPVS bez API' bol nesprávny.)
- **Eurofondy/ITMS2014+** — eurofondy.gov.sk + data.slovensko.sk (DCAT-AP-SK); prijímatelia + sumy.
  Detail zdrojov: sk-monitor-intelligence/research/sk_data_sources.md
- **OCDS (Open Contracting Data Standard)** — štandard pre dáta o obstarávaní; naň sú mapované
  red-flag indikátory (viď §6).

## 6. Investigatívna metodika — základ

- **Chrbtica katalógu indikátorov:** Open Contracting Partnership, *Red Flags in Public
  Procurement* (2024) — **73 indikátorov s definíciami a vzorcami**, mapované na OCDS, CC-BY 4.0.
  Plný text: `research/sources/ocp_redflags_2024_fulltext.txt`. Indikátory sú kódované
  `R001`–`Rxxx` a zoskupené (nízka transparentnosť, súťaž, podozrenie na manipuláciu...).
- Ďalšie metodické piliere (na spracovanie): OECD (bid rigging, integrity in procurement),
  Transparency International, Digiwhist/Opentender (CRI – Corruption Risk Index), World Bank,
  OLAF, OCCRP/ICIJ (postupy prepájania entít).

## 7. Architektúra (cieľový stav — Investigative Intelligence Engine)

Modulárny deterministický základ (AI voliteľná, nie nutná), 9 modulov: Rule, Anomaly,
Pattern, Relationship, Temporal, Document, Hypothesis, Evidence, Verification. Indikátory ako
verzované konfiguračné komponenty (YAML/JSON v `engine/rules/`), aby sa dali pridávať bez
zmeny architektúry.

## 8. Rozpracované / ďalší krok

Viď `PROGRAM.md` (index 14 výstupov + stav). Pracovný zoznam úloh je v task-liste relácie.

## 8b. Repozitáre (stav 2026-11-25)

- **`JDZReporting/sk-monitor` (verejný)** — kód, verejný dashboard, verejné dáta, metodiky.
  Nasadené 2026-11-25: collect.py (druh fix + dod_ico), .gitignore.
- **`JDZReporting/sk-monitor-intelligence` (GitHub, Private)** — VYTVORENÉ 2026-11-25.
  Schránka pre súkromnú investigatívnu vrstvu (findings/skóre/spisy). Zatiaľ len README.
- Zápis do repov: cez prehliadač (konektor je read-only). Root súbory spoľahlivo cez
  'Upload files'; vnorené (engine/, tools/, .github/workflows/) sú cez web UI krehké.

## 9. Bezpečnosť súkromnej vrstvy (platné od 2024-11-24)

**Model izolácie (overené, nie len .gitignore):**
- `sk-monitor/` = VEREJNÉ (nahráva sa na GitHub). Len kód, verejný dashboard, vyzreté metodiky
  bez údajov o konkrétnych subjektoch.
- `sk-monitor-intelligence/` = SÚKROMNÉ, samostatný priečinok MIMO `sk-monitor/`. Rizikové skóre a
  hypotézy o konkrétnych subjektoch, spisy, surové podklady. **Nikdy sa nenahráva.**
- Každý súkromný súbor nesie sentinel `SKMON-PRIVATE-DO-NOT-PUBLISH`.

**Bezpečnostná brána `tools/security_gate.py` = ALLOWLIST / default-deny** (exit 1 = stop):
- publikuje sa LEN explicitne povolená množina ciest (ALLOWED_PATH_GLOBS) — nový súbor mimo nej bránu zastaví;
- vo verejných `data/*.json` sú povolené LEN explicitné polia (item/firma); nové pole (napr. `rizikove_skore`, `hypoteza`) bránu zastaví;
- druhá vrstva: súkromný sentinel + tajomstvá (Anthropic/AWS/GitHub kľúče, PEM).
Beží v GitHub Actions PRED `git add/commit/push`; lokálne cez `tools/pre_upload_check.sh`.
Otestovaná pozitívne aj negatívne (nepovolený súbor aj zakázané dátové pole zachytené).

**Overené 2026-11-24 (VZDIALENE, nie len lokálne):** na GitHube `JDZReporting/sk-monitor`
(187 commitov, main) koreň obsahuje len pôvodné súbory; `docs/` na remote obsahuje LEN
`index.html`. Žiadny `research/`, `CLAUDE.md`, `PROGRAM.md`, `tools/`, `engine/` ani interný
súbor na remote ani na Pages. Dnešné interné súbory existujú len lokálne.
OVERENÉ: aktuálny stav remote nemá únik. NEOVEROVAL som diff všetkých 187 historických commitov
(sú to pôvodné uploady + dátové commity pred touto prácou). Interné podklady sú v `sk-monitor-intelligence/`.

**Zostáva (odporúčané, vyžaduje Juraja):** zvážiť samostatný **súkromný GitHub repozitár** pre
investigatívnu vrstvu (skutočné serverové oddelenie namiesto len lokálneho priečinka), keď
súkromná vrstva začne produkovať subjektové dáta. Dovtedy sa citlivé hypotézy NEukladajú do
verejného repa ani jeho publikačných priečinkov.

## 2026-11-25 — retencia, história a RPVS (dôležité pre prácu s dátami)
- `data/store.json` = 30-dňové okno (panel). **Dlhodobá pamäť** je v `data/history/*.jsonl`
  (append-only, NIKDY neprunovať). Pri viacročnej/historickej analýze čítať `history/`, nie store.json.
- RPVS OData overené naživo: `Partneri`→`KonecniUzivateliaVyhod` (JeVerejnyCinitel, PlatnostOd/Do).
  `dod_ico` sa dopĺňa z RPO (cache verzia `_v=2`). Pri osobách: **zhoda mena != dôkaz totožnosti**;
  čiastočné údaje zobrazovať ako neistotu, nie potvrdené prepojenie.
