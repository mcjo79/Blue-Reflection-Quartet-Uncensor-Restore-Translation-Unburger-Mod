#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/Blue_Reflection_Text_Tool/br_restoration_tool.py" build-event-prototypes --project-root "$ROOT" "$@"
