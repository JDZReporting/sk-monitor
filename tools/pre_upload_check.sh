#!/usr/bin/env bash
# Spusti PRED akýmkoľvek manuálnym nahratím sk-monitor na GitHub (web UI ignoruje .gitignore!).
# Zastaví ťa, ak by si nahrával interné dáta alebo tajomstvá.
set -e
cd "$(dirname "$0")/.."
echo "== Kontrola súkromného priečinka =="
if [ -d ../sk-monitor-private ]; then echo "OK: sk-monitor-private je MIMO sk-monitor (nenahrávať ho)."; fi
echo "== Bezpečnostná brána =="
python3 tools/security_gate.py
echo "Hotovo. Ak je výsledok OK, je bezpečné nahrať OBSAH sk-monitor/ (NIE sk-monitor-private/)."
