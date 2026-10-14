#!/usr/bin/env bash
# General launcher. No argument: interactive shell. With arguments: run that command and exit.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
exec "$PY" br_launcher.py "$@"
