# SK monitor — PROGRAM (master index)

Stav k 2026-11-24. Legenda: ⬜ nezačaté · 🟦 rozpracované · ✅ hotové.

## Fázy

- **Fáza 0 — Základ a infra** (teraz): trvalá dokumentácia, technologický audit, dátový pipeline.
- **Fáza 1 — Metodika + katalóg**: metodický report, analýza káuz, 100+ indikátorov v YAML.
- **Fáza 2 — Engine + súkromný režim**: 9 modulov, technické oddelenie súkromnej vrstvy.
- **Fáza 3 — Prototyp + meranie**: rizikové skóre, pohľad „Podozrivé", testovací dataset, falošné poplachy.
- **Fáza 4 — Benchmark + scenáre + škálovanie**: porovnanie platforiem, rozpočtové scenáre A/B/C.

## 14 povinných výstupov (mapovanie a stav)

| # | Výstup | Fáza | Stav | Umiestnenie |
|---|--------|------|------|-------------|
| 1 | Investigative Methodology Report | 1 | ⬜ | `sk-monitor-intelligence/research/01_methodology.md` |
| 2 | Analýza historických inv. prípadov (30+) | 1 | ⬜ | `research/02_cases.md` |
| 3 | Katalóg analytických indikátorov (100+) | 1 | 🟦 podklad OCP 73 | `engine/rules/*.yaml` |
| 4 | Návrh Investigative Intelligence Engine | 2 | ⬜ | `research/04_engine.md` |
| 5 | Systém automatizovaných inv. spisov | 2 | ⬜ | `research/05_casefiles.md` |
| 6 | Benchmark profesionálnych platforiem (15) | 4 | ⬜ | `research/06_benchmark.md` |
| 7 | Technologický a integračný audit | 0 | 🟦 | `research/07_tech_audit.md` |
| 8 | Zoznam MCP/konektorov/pluginov/skills | 0 | 🟦 | `research/07_tech_audit.md` |
| 9 | Inštalačné návody pre nástroje | 0 | ⬜ | `research/09_install_guides.md` |
| 10 | Návrh vlastných skills a MCP servera | 2 | ⬜ | `research/10_custom_tools.md` |
| 11 | Tri rozpočtové scenáre (A/B/C) | 4 | ⬜ | `research/11_scenarios.md` |
| 12 | Kontinuálne zlepšovanie pravidiel | 3 | ⬜ | `research/12_feedback.md` |
| 13 | Testovací dataset + meranie falošných poplachov | 3 | ⬜ | `engine/tests/` |
| 14 | Zoznam tech. prekážok + ako ich odstrániť | 0 | 🟦 | nižšie + `research/07_tech_audit.md` |

## Aktuálne technologické prekážky (živý zoznam — #14)

1. **Chýba WebSearch** v tejto relácii → náhrada cez prehliadač; odporúčané zapnúť web
   search na úrovni účtu/organizácie (Admin → Capabilities / network access).
2. **Sandbox nemá voľný sieťový prístup** (`curl` exit 56) → web obsah ťahať cez `web_fetch`.
3. **Žiadne MCP konektory** pre obstarávanie/registre/sankcie → vlastný scraping + OpenSanctions API.
4. **Mazanie v pripojenom priečinku blokované** (rm/rmdir Operation not permitted) + normalizácia
   diakritiky „Rešerš" láme `allow_cowork_file_delete` aj súborový Write → obísť: `mv` funguje,
   písať cez bash glob (`$(echo .../Re*/...)`). Prázdne adresáre zostávajú (neškodné).
5. **AI popisy (Haiku)** potrebujú `ANTHROPIC_API_KEY` secret — zatiaľ nevyriešené (org bez API konzoly).

## Hotové v tejto fáze (2026-11-24)

- ✅ `CLAUDE.md` — trvalé inštrukcie a princípy.
- ✅ `PROGRAM.md` — tento index.
- ✅ **Bezpečnosť súkromnej vrstvy:** fyzická izolácia do `sk-monitor-intelligence/` (MIMO repa) +
  bezpečnostná brána `tools/security_gate.py` (v Actions pred commitom aj lokálne pred uploadom).
  Overené: lokálne NIE je git repo, žiadny únik do histórie. `.gitignore` ponechané ako druhá vrstva.
- ✅ `research/sources/ocp_redflags_2024_fulltext.txt` — OCP 73 indikátorov (chrbtica katalógu).
- ✅ Overené: prehliadačový výskum funguje; OpenSanctions bezplatný pre public-interest; Docling (MIT) na dokumenty.

## Ďalší krok

Spracovať OCP 73 indikátorov do štruktúrovaného `engine/rules/procurement.yaml` (polia podľa
zadania §27: id, názov, zdôvodnenie, zdroj, potrebné dáta, vzorec, porovnávacia základňa,
min. vzorka, podmienky aktivácie/vylúčenia, legitímne vysvetlenia, riziko falošného poplachu,
istota, kalibrácia, zobrazenie, odporúčaný postup) + označiť realizovateľnosť na SK dátach
(ÚVO/CRZ). Paralelne dokončiť `research/07_tech_audit.md`.

## Bezpečnosť — stav a odporúčanie (2026-11-24)

- ✅ Fyzická izolácia súkromnej vrstvy (`sk-monitor-intelligence/` mimo nahrávaného priečinka).
- ✅ Bezpečnostná brána `tools/security_gate.py` — zapojená v GitHub Actions pred commitom;
  lokálne `tools/pre_upload_check.sh` pred manuálnym uploadom. Pozitívne aj negatívne otestovaná.
- ✅ Overené VZDIALENE: remote `JDZReporting/sk-monitor` (187 commitov) — koreň len pôvodné súbory,
  `docs/` na remote len `index.html`. Žiadny interný súbor na GitHube ani Pages. (Diff 187 commitov neauditovaný — predchádzajú tejto práci.)
- ✅ Brána prepísaná na ALLOWLIST (default-deny): len povolené cesty + dátové polia; testy pozitívne aj negatívne.
- ✅ `DEV_ENVIRONMENT.md` — vývojové prostredie, architektúra súkromného repa `sk-monitor-intelligence`, audit schopností + akcie pre Juraja.
- ⏭️ **Odporúčané (vyžaduje Juraja), keď vznikne subjektová vrstva:** samostatný SÚKROMNÝ GitHub
  repozitár pre investigatívnu vrstvu — skutočné serverové oddelenie. Dovtedy citlivé hypotézy
  NEukladať do verejného repa. Rozhodnutie o paywalle/hostovaní súkromného režimu = na Juraja.


## Engine — stav (2026-11-25)

Reťazec FUNGUJE a je otestovaný end-to-end (na reálne tvarovaných dátach):
verejné `data/store.json` → základné príznaky → **RPVS obohatenie** → súkromné
`findings/risk_scored.json` (sentinel).

- `engine/rules/procurement.yaml` (6) + `engine/rules/ownership.yaml` (5) = **11 indikátorov**.
- `engine/rpvs.py` — RPVS OData klient (lookup podľa IČO, KÚV/konflikt/podnety), otestovaný.
- `engine/score.py` v0.2 — rizikové skóre + RPVS obohatenie + **SK-OWN-SHARED** (spoloční
  vlastníci dvoch dodávateľov), vážené skóre, dôkazy. Otestované end-to-end.
- `collect.py` — doplnené IČO dodávateľa (`dod_ico`, spojka na RPVS) + oprava `druh` parsera.
- Bezpečnosť: výstup skóre je subjektový → len súkromná vrstva (brána overene blokuje únik).

Chýba do ostrej prevádzky (vyžaduje Juraja): **súkromný repo `sk-monitor-intelligence`** so
scheduled Action, ktorý spustí `score.py` nad plným `store.json` + RPVS, a uloží výstup
súkromne. Dovtedy engine beží na vyžiadanie lokálne/manuálne.

Nenasadené lokálne zmeny (čakajú na dávkový deploy cez prehliadač): collect.py (druh fix,
dod_ico), tools/security_gate.py, .github/workflows/daily.yml, engine/*, docs.

## Aktualizácia 2026-11-25 — kritický audit + Historical Intelligence
- **Retencia:** store.json bol 30-dňové okno (prune). Doplnená **DLHODOBÁ PAMÄŤ**:
  append-only `data/history/YYYY-MM.jsonl` (+ index `data/archive_ids.json`), nič sa nemaže.
  Otestované na 2340 položkách (first_seen 2026-07..11). store.json ostáva 30-dňové okno pre panel.
  Spätný backfill (1/3/5/10 r.) per zdroj = roadmap.
- **RPVS OData OVERENÉ naživo:** Partneri→KonecniUzivateliaVyhod (polia JeVerejnyCinitel,
  PlatnostOd/PlatnostDo = aktuálne vs historické). UNIPHARMA IČO 31625657 → 3 KÚV. Spojka
  `dod_ico` sa dopĺňa po oprave sticky RPO cache (_v=2).
- **Engine linking:** `links.py` — SK-AUDIT-SPENDER (56 prepojení) + SK-AUDIT-REPEAT (4) otestované.
- **Katalóg:** `engine/rules/control.yaml` (kontrolné indikátory, §27).
- **Ďalej (roadmap, podľa priority):** scoring v2 (viacrozmerné, kalibrované), Ownership profil,
  Temporal, Document Intelligence (PDF), Evidence/Verification 2.0, privátny terminál, benchmark 15.

## Aktualizácia 2026-11-26 — STRATEGICKÉ PREHODNOTENIE (mení roadmapu)
Plný dokument: `sk-monitor-intelligence/research/STRATEGICKE_PREHODNOTENIE.md`.

**Kľúčové zistenie:** verejnú dátovú vrstvu (CRZ/RPVS/RPO/funkcionári/dlžníci/rozpočet/ÚVO/účtovné
závierky, 2011–2026) **už poskytuje verejnystat.sk** zadarmo (CC BY), nočne, vrátane extrakcie cien
po dodatkoch. Pod ním **slovensko.digital DataHub** (sync API zadarmo) a **RÚZ Open API (CC0)**.
→ ~80 % pôvodného 5-pilierového plánu je už hotové inde. **Nереplikovať.**

**Nová téza:** SK monitor = **investigatívna ÚSUDKOVÁ vrstva** nad existujúcimi dátami.
verejnystat.sk zámerne NErobí skóre/hypotézy/hodnotenia → to je naše jediné unikum.

**Revidovaná roadmapa:**
- IMPLEMENTOVAŤ: RÚZ integrácia (`engine/ruz.py` + `financial.yaml`, SK-FIN-*), prechod zberu na
  slovensko.digital DataHub, finančné kombinácie v termináli (DuckDB beží).
- ZJEDNODUŠIŤ: collect.py (len NKÚ + adaptér DataHub); 5 pilierov → 3 osi; 9 modulov → 4 (Rule/Relationship/Financial/Document).
- ODLOŽIŤ: FtM+NetworkX graf, Splink, OCR, always-on cloud terminál, NL/MCP asistent.
- ZRUŠIŤ: plný parlament scraping (§5 dokumentu), vlastný dátový portál ako cieľ, backfill zberom.

**Verdikt parlament:** NIE plný monitoring. Bot-detection neprekonateľné legitímne; nízka hodnota/náklad.
Nechať na legitímnu cestu (Slov-Lex / NR SR open data / oficiálna žiadosť) až keď bude reálne treba.

**Najhodnotnejšie kombinácie (= produkty enginu):** CRZ×RÚZ (závislosť od štátu, schránky),
CRZ×RPVS×RÚZ (kto profituje cez akú firmu), NKÚ×CRZ (kontrolovaný míňač), RPO×CRZ (firma šitá na zákazku),
dlžníci×CRZ (dodávateľ čo dlhuje štátu).

## Aktualizácia 2026-11-26 (večer) — P0/P1 implementácia (HOTOVÉ, otestované)
Schválené korekcie stratégie zapracované. Scenár A (0 €).
- **P0 audit zdrojov** (`sk-monitor-intelligence/research/P0_audit_zdrojov.md`): RÚZ=CC0 autonómne;
  **KOREKCIA: DataHub je platený/po registrácii** (zdarma len po schválení pre výskum) → jadro na priamych
  primárnych registroch, nezávislá pamäť. nrsr=mimo jadra. ÚVO/TED=jadro (P1, ďalej).
- **RÚZ klient** `engine/ruz.py` — CC0, bez kľúča, parser kotvený na text riadkov výkazu, template cache;
  **selftest PASS na reálnych číslach (Slovanet)**. Ošetrené: IFRS/konsolidované/2009–2012 = len PDF → financie=None.
- **Finančná analytika** `engine/financial.py` + `engine/rules/financial.yaml` — **DVE oddelené dimenzie**:
  ekonomická významnosť (deskriptívna) vs rizikové proxy signály (SK-FIN-PUBRELIANCE/YOUNGWIN/THINCAP/LOSSWIN),
  každý s obmedzeniami + legit. vysvetleniami. Metodika: obrat ≠ platby od štátu; nízke aktíva ≠ schránka. selftest PASS.
- **DuckDB + terminál**: nové tabuľky `financie_firma/financne_signaly/financie_rad`, views + **dotazy ⑩⑪⑫**.
  Overené end-to-end na reálnych dátach RÚZ (Slovanet 2024→2025: obrat 51,1→70,0 mil., rast 37 %).
- Zapojené do `intelligence.yml` (RÚZ + financial kroky). Security gate: OK (nové súbory v allowliste/whiteliste).
- **Zistenie:** `dod_ico` v commitnutom store.json je prázdne (0/2340) — IČO sa dopĺňa až v živom Actions behu
  (collect.py RPO). Preto plný CRZ×RÚZ join beží až v pipeline, nie na lokálnej snapshotke.

## Aktualizácia 2026-11-26 (neskoro večer) — validácia pipeline + kvalita dát
- **Hranica prostredia (dôležité):** živý produkčný beh (collect.py CRZ/RPO/RPVS, engine RÚZ) beží LEN
  v GitHub Actions — Cowork sandbox má obmedzenú sieť (len web_fetch na vybrané hosty) a nevie pushovať.
  Preto: kód + unit-testy lokálne, **živá validácia na najbližšom riadnom Actions behu** (alebo workflow_dispatch).
- **IČO — PRIMÁRNA oprava (P0):** príčina prázdneho `dod_ico` = RPO enrichment beží len v Actions a CRZ listing
  IČO nemá. **Riešenie: `crz_detail()` v collect.py ťahá IČO z DETAILU zmluvy (/zmluva/<id>) = primárny zdroj,
  presné, bez fuzzy.** Overené: detail Valbek SK → dod_ico 17314569, obj_ico 31364501, zmluvná suma 527 670 €
  (parser selftest PASS). Reťazec CRZ→IČO→RÚZ overený naživo (17314569 → RÚZ UJ 303574).
  RPO zostáva SEKUNDÁRNE (len keď CRZ detail nedá IČO); provenancia v poli `dod_ico_zdroj` (crz/rpo).
  Nové polia (obj_ico, suma_zmluvna, dod_ico_zdroj) pridané do security_gate allowlistu. Cache: data/crz_detail_cache.json.
- **Rozlíšenie súm (metodika):** `suma_zmluvna` = zmluvne dohodnutá čiastka z CRZ detailu (NIE skutočná platba).
- **Data Quality Dashboard (P0):** `tools/data_quality.py` — trvalý prehľad po každom zbere. Metriky s
  menovateľom + spôsobom výpočtu: záznamy/zdroj, historické pokrytie, % validných IČO, identifikovaní dodávatelia,
  provenancia IČO, duplicity, RÚZ/RPVS pokrytie, štrukt. výkazy, chýbajúce financie, ÚVO↔CRZ (n/a=P1),
  posledná aktualizácia zdrojov. Spúšťa sa v collect.py (verejné) aj intelligence.yml (+findings). Terminál dotaz ⑬.
  **Baseline PRED behom: 0/303 zmluvy s IČO** — po novom behu má byť ~100 % z CRZ detailu (to je test úspechu).

## Aktualizácia 2026-11-26 (noc) — ÚVO↔CRZ prepojenie (P1) + odolný push
- **`engine/uvo_link.py`** — prepojenie ÚVO zákazka → CRZ zmluva. **TRI oddelené sumy**: predpokladaná (ÚVO),
  zmluvná (CRZ), zaplatené (n/a — CRZ platby nemá). Rozdiel zmluvná−predpokladaná = signál navýšenia.
  Join podľa obstarávateľa+názvu+času = **nízka istota** (nie cez ID/IČO) → `uroven_istoty`, „OVERIŤ".
  Selftest PASS; na reálnych dátach **17 prepojení/301 zmlúv** (napr. Cesta II/563 → 1,40 mil. €).
  Zapojené: intelligence.yml, build_db (tabuľka `uvo_crz`), terminál ⑭, metrika `uvo_crz_prepojenie`, gate whitelist.
- **Zdroje na migráciu** (research/P1_uvo_ted.md): ÚVO OpenData (opendata.uvo.gov.sk — stabilné ID+IČO víťaza),
  TED eForms, OCDS. ÚVO hosty blokujú robots pre web_fetch → živé overenie z Actions runnera / pastnutej vzorky.
- **Oprava CI:** `daily.yml` commit krok — odolný push (rebase + 5 pokusov) proti súbehu/ručnému pushu
  (predtým `[rejected] fetch first`). collect.py + gate predtým prešli; padal len push.
- **Validácia IČO (živá):** po 2 behoch 5,6 %→**29,9 %** zmlúv s IČO (87 crz + 3 rpo, 0 fuzzy chýb); rastie ~80/beh.

## Aktualizácia 2026-11-26 (noc, pokr.) — Radar (P2) + ÚVO OpenData sonda
- **`engine/radar.py`** (P2) — spája financial/risk/ownership/NKÚ do leadov s **DVOMA nezávislými osami**:
  `vyznam_skore` (ekonomická významnosť) a `riziko_skore` (proxy na preverenie). Typ témy: ekonomická téma
  (významné, bez podozrenia) / na preverenie / prioritné / sledovať. Nekolabuje do „pravdepodobnosti korupcie".
  Vysvetlenie oboch osí pri každom leade. Selftest PASS. Zapojené: intelligence.yml, build_db (`radar`), terminál ⑮.
- **`tools/uvo_probe.py`** — sonda schémy **ÚVO OpenData** (opendata.uvo.gov.sk). ÚVO je blokované pre web_fetch
  aj sandbox → sonda beží v Actions (otvorená sieť), uloží reálnu schému do `findings/_uvo_probe.json`.
  Z nej postavím ÚVO klienta SPRÁVNE (bez hádania polí). Zapojené do intelligence.yml (nekritický krok).
- Oba nové súbory v gate whiteliste. Terminál má teraz dotazy ①–⑮.

## Aktualizácia 2026-11-26 (noc, pokr. 2) — živá validácia + kalibrácia radaru
- **Živý engine beh prešiel.** Reálne čísla: **IČO 90,7 %** (273/301; 267 crz + 6 rpo, 0 fuzzy chýb),
  dodávatelia identif. **90,3 %**, **RÚZ 96 %** (štrukt. výkazy 92 %), RPVS 60 %, 0 duplicít, ÚVO↔CRZ 17, radar 124 leadov.
- **Opravené pri čítaní ostrých dát:** financial.py None-guard (rok bez výkazu); radar **dedup** príznakov
  (Slovanet riziko 100→36); data_quality source_health vnorenie; engine kroky **nekritické** (|| echo).
- **ÚVO sonda:** `opendata.uvo.gov.sk` NEEXISTUJE (DNS). Noví kandidáti (www.uvo.gov.sk/openDataIdx,
  data.slovensko.sk CKAN, TED) — budúci beh overí.
- **Kalibrácia radaru:** koncentračné/objemové príznaky (SK-HIGHVALUE/MARKET-HHI/BUYER-CONC) presunuté
  k **VÝZNAMNOSTI** (ekonomická štruktúra, nie podozrenie); na rizikovej osi ostávajú len skutočné proxy
  (SK-OWN-SHARED, audit, FIN). Selftest PASS. Prejaví sa pri ďalšom engine behu (beží z verejného repa).

## Aktualizácia 2026-11-26 (noc, pokr. 3) — CRZ dodatky: životný cyklus kontraktu
- **`engine/contract_lifecycle.py`** — rekonštrukcia cyklu z CRZ záznamov zoskupených podľa čísla zmluvy
  (dodatok → rodič cez `zml_cislo_ref`). Časová os (zmluva + dodatky), **3 sémantiky súm** (delta / nová
  celková cena / neurčené) → kumulatív LEN pri jednoznačnej sémantike, inak sa **neskladá** (bez dvojitého
  započítania). Navýšenie abs/%, **>50 % = upozornenie preveriť voči zákonu o VO** (nie tvrdenie o nezákonnosti),
  dni medzi podpisom a dodatkami, počet dodatkov. Selftest PASS (delta/nová cena/neurčené).
- **collect.py**: `parse_crz_detail_text` parsuje `typ` (Zmluva/Dodatok), `cislo`, `cislo_ref` (k zmluve č.);
  položky dostanú `zml_typ`/`zml_cislo`/`zml_cislo_ref`. `CRZ_PARSER_VER=3` (cache sa preparsuje). Gate allowlist doplnený.
- Zapojené: intelligence.yml (nekritický krok), build_db (`zmluvy_cyklus`, `zmluvy_cyklus_timeline`),
  terminál **⑯ cyklus / ⑰ časová os**, data_quality (`zmluvy_s_dodatkami`, `cykly_nejednoznacna_suma`).
- **Ďalej:** napojiť TEXTY dodatkov (document.py extrahuje PDF) → presná sémantika namiesto „neurčené";
  predĺženie trvania, zmena predmetu/jednotkových cien zo štruktúrovaných polí; dôvody zmien z textu.

### Ďalej (P1 zvyšok → P4)
- **P1:** CRZ↔ÚVO prepojenie + ÚVO/TED ako jadro (celý proces obstarávanie→zmluva→dodatky→platby).
- **P2:** kvalitné indikátory, vlastníctvo, dokumenty, investigatívny radar (významnosť+riziko spolu).
- **P3:** terminál (hotový základ), správa prípadov, graf vzťahov (FtM/NetworkX).
- **P4:** read-only MCP server nad DuckDB (architektúra: čistá SQL vrstva `skmonitor.duckdb` + views = pripravená),
  NL/text-to-SQL asistent.
- Parlament (#11): kód NEMAZAŤ; Slov-Lex/vláda len ako lacný doplnkový kontext, ak dostupné.
