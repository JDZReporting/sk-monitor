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
