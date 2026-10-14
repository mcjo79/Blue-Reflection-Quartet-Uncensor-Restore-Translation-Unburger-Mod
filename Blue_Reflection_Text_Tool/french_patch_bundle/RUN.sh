#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
command -v python3 >/dev/null 2>&1 || PY=python

if [[ $# -eq 0 ]]; then
  # Interactive mode: choose the game and the translation to install.
  exec "$PY" br_french_installer.py
fi

# Advanced / direct mode: pass every argument to the 2017 patch tool.
exec "$PY" br_french_patch.py "$@"
