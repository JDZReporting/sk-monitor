# DEV_ENVIRONMENT.md — vývojové prostredie, súkromný repo, audit schopností

Stav k 2026-11-24. Cieľ: odstrániť manuálne nahrávanie cez GitHub UI a dať asistentovi
bezpečný priamy prístup k vývoju/testovaniu/nasadzovaniu.

## A. Profesionálne vývojové prostredie

**Problém dnes:** nasadzuje sa ručným nahrávaním súborov cez GitHub web UI. To je pomalé,
ignoruje `.gitignore`, nemá vetvy, PR, code review ani CI. Riziko nekonzistentného stavu.

**Overené prostredie asistenta (2026-11-24):** sandbox s `git` (v2.34), Python/Node; prehliadač
na prácu s GitHubom; `web_fetch`. Sieť v sandboxe je allowlistovaná a sandbox NEMÁ tvoje GitHub
prihlásenie → `git push` priamo z neho nie je spoľahlivý a token nechcem držať v otvorenom texte.

**Odporúčaný model (3 úrovne — čím vyššia, tým väčšia autonómia):**

1. **Lokálny Git (hneď, bez nových oprávnení).** Z priečinka `sk-monitor` spravíme plnohodnotný
   git repo a prepojíme na GitHub. Výhoda: verzie, história, rollback, koniec „Add files via
   upload". Nasadzovanie stále spúšťaš ty (jeden príkaz / tlačidlo), ale čisto cez git.
2. **GitHub MCP server (ODPORÚČAM ako primárne).** Oficiálny `github/github-mcp-server`
   pripojený v Claude Desktop ako vlastný (custom) konektor — v registri konektorov NIE JE,
   treba pridať ručne. Potom dostanem natívne nástroje na commit/branch/PR/čítanie Actions logov
   **bez manuálneho uploadu a bez toho, aby som držal token** (autentifikácia cez GitHub login).
3. **Claude Code + `gh` CLI na tvojom PC (doplnok pre ťažší vývoj).** Terminálový workflow
   priamo nad repozitárom; vhodné, keď chceš dlhšie kódovacie relácie s vetvami/PR/CI.

**Navrhovaný branch/PR/CI model:**
- `main` = produkcia (Pages), chránená vetva (vyžaduje PR + zelené kontroly).
- `dev` = integračná vetva; feature vetvy → PR do `dev`.
- **CI na každý PR** (nový workflow `ci.yml`): `security_gate.py` (allowlist brána), `pytest`
  (testy indikátorov), `ruff`/`flake8` (lint), `pip-audit` (zraniteľnosti závislostí).
- **Staging:** náhľad z vetvy `dev` (samostatné Pages / preview) pred `main`.
- **Rollback:** `git revert` + tagy na stabilných bodoch.
- **Automatické code review:** zapnúť GitHub required reviews + prípadne CodeQL (zdarma pre
  verejné repo) na bezpečnostné skenovanie.

## B. Súkromný repozitár — architektúra

Cieľ (podľa Juraja):
- **`sk-monitor`** — verejná platforma (kód, verejný dashboard, verejné dáta, vyzreté metodiky).
- **`sk-monitor-intelligence`** — SÚKROMNÝ repo: rizikové skóre a hypotézy o konkrétnych
  subjektoch, investigatívne spisy, surové citlivé podklady.

**Tok dát (jednosmerný, bezpečný):**
```
verejné dáta (sk-monitor: data/store.json)  ──►  súkromný engine (sk-monitor-intelligence)
                                                   │ produkuje skóre/hypotézy/spisy
                                                   ▼
                                         súkromné výstupy (len v private repo, NIE Pages)
```
- Public → Private: engine číta verejné dáta read-only.
- Private → Public: NIKDY automaticky. Len cez **ľudské schválenie** (promovanie overeného
  faktu bez citlivých hypotéz), pričom aj vtedy prejde `security_gate.py`.

**Zdieľaná metodika:** katalóg indikátorov (definície) je verejný (v `sk-monitor/engine/rules`);
do private repa sa pripojí ako **git submodule** alebo kópia — jedna pravda pre pravidlá.

**Autentifikácia:**
- Private repo = len ty + autorizovaní (GitHub collaborators/team).
- Pre automatizáciu: **fine-grained Personal Access Token** alebo **GitHub App** s prístupom
  len na `sk-monitor-intelligence` (najmenšie potrebné oprávnenie). Token ako GitHub Actions
  secret, nikdy v kóde (bráni `security_gate.py`).

**Autonómna cloudová prevádzka (bez zapnutého PC):**
- GitHub Actions v private repo (cron) spúšťa engine nad verejnými dátami a ukladá súkromné
  výstupy do private repa. Beží na GitHub serveroch — tvoj počítač nemusí byť zapnutý.
- Prístup k súkromnému režimu (na čítanie výstupov): odporúčam **nie** verejný Pages, ale buď
  (a) prístup priamo cez GitHub (private repo), alebo (b) neskôr malá autentifikovaná appka
  (napr. Cloudflare Access / Access-gated stránka). Detail v rozpočtových scenároch (#11).

**Kroky na vytvorenie (KOORDINOVAŤ — nové oprávnenia/repo = tvoj súhlas):** nižšie v „Akcie".

## C. Audit schopností asistenta (čo mám / čo mi chýba) — stav 2026-11-24

**Mám k dispozícii:**
- Sandbox `bash` (Python, Node, git, pandas-schopné prostredie) — jadro vývoja a testov.
- Prehliadač (`claude-in-chrome`) — web research aj práca s GitHubom (overovanie, čítanie).
- `web_fetch` — načítanie konkrétnych URL vrátane extrakcie textu z PDF.
- Súborové nástroje, docs konektor, artefakty, **scheduled tasks**, task-list,
  **subagenti** (paralelný výskum), `present_files`.

**Chýba / obmedzené:**
- **WebSearch** — v tejto relácii nie je; náhrada cez prehliadač (pomalšie). Zapnúť na účte.
- **Priamy git/GitHub prístup** — nemám; preto zatiaľ manuálny upload. Rieši bod A (GitHub MCP/gh).
- **MCP konektory** pre obstarávanie/registre/sankcie/GitHub — v registri nie sú žiadne.
- **Zápis súborovými nástrojmi** do pripojeného priečinka láme diakritika v „Rešerš" →
  obchádzam cez `bash` (funguje). Mazanie obmedzené (`mv` funguje).

**Najväčšie unlocky podľa dopadu:**
1. **GitHub MCP / `gh`** → priame, verziované nasadzovanie; koniec manuálneho uploadu. (najvyšší)
2. **WebSearch** → výrazne rýchlejší výskum (30 káuz, benchmark 15 platforiem).
3. **Lokálne modely / štatistika** namiesto plateného LLM → analytika bez prevádzkových nákladov.

**Delegovanie:** viem spúšťať špecializovaných subagentov a paralelizovať (napr. extrakcia
indikátorov, benchmark platforiem, čítanie dlhých zdrojov) — budem to využívať.

**Claude Code:** vhodný pre ťažší repo-vývoj; navrhujem nasadiť po zapnutí GitHub prístupu (bod A3).

## AKCIE PRE JURAJA (zoradené podľa dopadu)

1. **[odomkne priame nasadenie — najvyššia priorita] GitHub MCP server.**
   V Claude Desktop → nastavenia konektorov pridaj vlastný MCP server
   `github/github-mcp-server` (oficiálny GitHub). Po prihlásení cez GitHub budem vedieť
   commitovať, robiť vetvy a PR bez manuálneho uploadu. (Ak preferuješ, alternatíva je
   Claude Code + `gh auth login` na tvojom PC.)
2. **[bezpečnosť subjektovej vrstvy] Vytvoriť súkromný repo `sk-monitor-intelligence`.**
   Súkromný (private) na GitHube, pridať teba ako vlastníka. Vytvorenie a oprávnenia
   koordinuj so mnou — pripravím štruktúru a Actions. Nie je blokujúce, kým engine neprodukuje
   subjektové dáta (dovtedy stačí lokálny `sk-monitor-intelligence/` priečinok).
3. **[rýchlosť výskumu] Zapnúť WebSearch** na úrovni účtu/organizácie (Admin → Capabilities /
   network access), potom obnoviť vlákno.
4. **[voliteľné, nie blokujúce] `ANTHROPIC_API_KEY`** ako GitHub secret — odomkne AI popisy;
   základná analytika však bude fungovať aj bez neho (viď #10 bezplatné alternatívy).

Po bode 1 prejdem z manuálneho uploadu na git workflow s vetvami, PR a CI (vrátane
`security_gate.py`, testov, lint a `pip-audit`).
