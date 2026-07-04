# Nastavenie (jednorazovo, ~20–30 min) — beží v cloude zadarmo, nezávisle od tvojho PC

Cieľ: každé ráno sa v GitHube automaticky spustí zber (Parlament + Vláda + ÚVO), výsledok sa uloží do repozitára a zobrazí na **online paneli** (GitHub Pages). Bez AI nákladov, bez zapnutého počítača.

## 1. Vytvor repozitár
1. Na github.com → **New repository** → názov napr. `sk-monitor` → **Private** → Create.
2. Nahraj doň obsah tohto priečinka (`collect.py`, `config.json`, `requirements.txt`, priečinok `.github/`, tento `SETUP.md`). Buď cez „Add file → Upload files", alebo cez git:
   ```bash
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<ty>/sk-monitor.git
   git push -u origin main
   ```

## 2. Zapni GitHub Actions
- V repozitári → záložka **Actions** → ak sa spýta, potvrď povolenie workflowov.
- Workflow „SK monitor daily" beží denne (cron 04:00 UTC = 06:00 v lete). Prvý raz ho spusti ručne: **Actions → SK monitor daily → Run workflow**.

## 3. Zapni online panel (GitHub Pages)
- Repozitár → **Settings → Pages** → *Source*: **Deploy from a branch** → Branch: **main**, priečinok **/docs** → Save.
- O chvíľu bude panel na adrese `https://<ty>.github.io/sk-monitor/` (odkaz uvidíš v Settings → Pages).

Hotovo. Panel sa každé ráno sám obnoví; história dní je v priečinku `data/`.

## 4. AI popisy „čo sa mení" (voliteľné, lacné)
Aby mal každý nový zákon 1–2 vetový popis obsahu (z dôvodovej správy cez model Haiku):
1. Získaj API kľúč na **console.anthropic.com** (účet + platba; beh stojí rádovo centy — sumarizujú sa len nové položky).
2. V repozitári: **Settings → Secrets and variables → Actions → New repository secret**.
3. Name: `ANTHROPIC_API_KEY`, Secret: vlož svoj kľúč → Add secret.
4. Ak kľúč nepridáš, všetko ostatné funguje ďalej — len bez AI popisov (zadarmo).

## Ako to používať
- **Denne:** otvoríš si URL panela — vidíš nové zákony (koalícia/opozícia), vládne materiály a sledované zákazky. Filter hore.
- **On-demand (keď chceš rozbor):** otvor Claude a povedz napr. „rozober ČPT 1356 z dôvodovej správy" alebo „preveri firmu X — vlastníci (RPVS) + médiá". AI platíš len vtedy.

## Úpravy
- Watchlist tém, strán a sledovaných inštitúcií je v `config.json` — uprav a commitni.
- Čas behu zmeníš v `.github/workflows/daily.yml` (pole `cron`, v UTC).

## Poznámka k spoľahlivosti
Skript číta verejné stránky (nrsr.sk, rokovania.gov.sk, uvo.gov.sk). Ak niektorý web zmení štruktúru a zber vráti 0 položiek, treba doladiť selektory v `collect.py` (funkcie `collect_nrsr/collect_vlada/collect_uvo`). Po prvom ostrom behu to spolu rýchlo overíme. ÚVO má aj oficiálne API/JSON — dá sa naň prejsť pre maximálnu stabilitu.
