#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_restoration_tool.py" collect-event-records --project-root "$PROJECT_ROOT" "$@"
