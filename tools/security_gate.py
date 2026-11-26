#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SK monitor — bezpečnostná brána pred nasadením (ALLOWLIST / default-deny).

Filozofia: NIE "zakáž známe zlé", ale "povoľ len explicitne dovolené". Publikovať sa smú
VÝLUČNE súbory na allowliste ciest a dátové polia na allowliste polí. Čokoľvek nové (nový
súbor, nové pole v dátach — napr. budúce rizikové skóre či hypotéza) bránu ZASTAVÍ, kým to
niekto vedome nepridá na allowlist. Blokovanie tajomstiev/sentinelu je druhá vrstva.

Spúšťa sa v GitHub Actions PRED commitom a lokálne cez tools/pre_upload_check.sh.
Návratový kód 0 = čisté, 1 = porušenie (nasadenie sa musí zastaviť).
"""
import os, re, sys, json, fnmatch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 1) ALLOWLIST ciest: len tieto vzory sa smú publikovať ----
ALLOWED_PATH_GLOBS = [
    "CLAUDE.md", "PROGRAM.md", "SETUP.md", "README.md", ".gitignore",
    "requirements.txt", "daily.yml", "config.json", "feeds.json", "collect.py",
    "DEV_ENVIRONMENT.md", "DATA_SOURCES.md",
    "data/history/*.jsonl",
    ".github/workflows/*.yml",
    "tools/*.py", "tools/*.sh",
    "engine/*.py", "engine/**/*.py", "engine/**/*.yaml", "engine/**/*.yml",
    "engine/**/*.json", "engine/**/*.md",
    "docs/index.html", "docs/**/*.html", "docs/**/*.css", "docs/**/*.js",
    "docs/**/*.json", "docs/**/*.svg", "docs/**/*.ico", "docs/**/*.png",
    "data/*.json", "data/**/*.json", "data/*.md",
]
# Adresáre, ktoré preskakujeme pri obsahu (nie sú súčasťou uploadu):
SKIP_DIRS = {".git", ".gittrash", "__pycache__", "node_modules"}

# ---- 2) ALLOWLIST dátových polí vo verejných data/*.json ----
ALLOWED_TOP = {"items", "updated", "firmy"}
ALLOWED_ITEM_FIELDS = {
    # základné (každá položka)
    "id", "source", "title", "date", "category", "blok", "meta", "url",
    # obohatenie / podmienené
    "stav", "suma", "dod", "overit", "popis",
    "first_seen", "last_seen", "dod_vznik", "dod_krajina", "_changed",
    "druh", "cpv", "fondy", "dod_ico",    # ÚVO detail + IČO dodávateľa (verejné)
    "dod_ico_zdroj", "obj_ico", "suma_zmluvna",   # provenancia IČO + IČO objednávateľa + zmluvná suma (CRZ detail, verejné)
    # interné príznaky spracovania — TODO (#8): stripovať pred publikovaním store.json
    "_uvo_done", "_ai_tried", "_overit_checked",
}
ALLOWED_FIRMA_FIELDS = {"vznik", "krajina", "ico", "zdroj", "_v"}  # _v = interný marker verzie cache (neškodný)

# ---- 3) Blocklist (druhá vrstva): tajomstvá + súkromný sentinel ----
PRIVATE_SENTINEL = "SKMON-PRIVATE-DO-NOT-PUBLISH"
SECRET_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API kľúč"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "súkromný kľúč (PEM)"),
    (re.compile(r"ANTHROPIC_API_KEY\s*[:=]\s*['\"]?sk-ant-"), "zapísaný ANTHROPIC_API_KEY"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "GitHub token"),
]
SKIP_EXT = {".pyc"}
SELF = "tools/security_gate.py"
# Súbory, ktoré smú sentinel SPOMÍNAŤ ako dokumentáciu (nie sú súkromný obsah):
SENTINEL_DOC_WHITELIST = {"tools/security_gate.py", "tools/pre_upload_check.sh", "CLAUDE.md", "PROGRAM.md", "engine/score.py", "engine/links.py", "engine/ownership.py", "engine/score2.py", "engine/document.py", "engine/ruz.py", "engine/financial.py", "engine/uvo_link.py"}

violations = []
def rel(p): return os.path.relpath(p, ROOT).replace(os.sep, "/")
def allowed_path(r):
    return any(fnmatch.fnmatch(r, g) for g in ALLOWED_PATH_GLOBS)

# --- Prejdi všetky súbory, ktoré by manuálny upload nahral ---
for base, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for f in files:
        p = os.path.join(base, f); r = rel(p)
        # a) cesta musí byť na allowliste
        if not allowed_path(r):
            violations.append(f"[MIMO ALLOWLISTU] '{r}' nie je medzi povolenými publikovateľnými súbormi")
            continue
        if os.path.splitext(f)[1].lower() in SKIP_EXT:
            continue
        try:
            if os.path.getsize(p) > 20_000_000:
                continue
            text = open(p, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        # b) sentinel + tajomstvá (okrem seba — pozná vzory z definície)
        if r not in SENTINEL_DOC_WHITELIST:
            if PRIVATE_SENTINEL in text:
                violations.append(f"[SÚKROMNÝ SENTINEL] '{r}' patrí do sk-monitor-intelligence/")
            for pat, label in SECRET_PATTERNS:
                if pat.search(text):
                    violations.append(f"[TAJOMSTVO] '{r}' obsahuje {label}")
        # c) field-level allowlist pre verejné dáta
        if os.path.basename(r) == "store.json":
            try:
                obj = json.loads(text)
            except Exception:
                violations.append(f"[DÁTA] '{r}' nie je platný JSON"); continue
            if isinstance(obj, dict):
                extra = set(obj.keys()) - ALLOWED_TOP
                if extra:
                    violations.append(f"[DÁTOVÉ POLE MIMO ALLOWLISTU] '{r}' top-level: {sorted(extra)}")
                for it in (obj.get("items") or []):
                    if isinstance(it, dict):
                        ex = set(it.keys()) - ALLOWED_ITEM_FIELDS
                        if ex:
                            violations.append(f"[DÁTOVÉ POLE MIMO ALLOWLISTU] '{r}' item {it.get('id','?')}: {sorted(ex)}")
                            break
                firmy = obj.get("firmy") or {}
                if isinstance(firmy, dict):
                    for name, val in firmy.items():
                        if isinstance(val, dict):
                            ex = set(val.keys()) - ALLOWED_FIRMA_FIELDS
                            if ex:
                                violations.append(f"[DÁTOVÉ POLE MIMO ALLOWLISTU] '{r}' firmy['{name}']: {sorted(ex)}")
                                break

if violations:
    print("BEZPEČNOSTNÁ BRÁNA (allowlist): NASADENIE ZASTAVENÉ — porušenia:")
    for v in violations[:50]:
        print("  - " + v)
    print(f"\nSpolu: {len(violations)}. Pridaj súbor/pole na allowlist VEDOME, alebo presuň do súkromnej vrstvy.")
    sys.exit(1)
print("Bezpečnostná brána (allowlist): OK — publikuje sa len explicitne povolené súbory a polia.")
sys.exit(0)
