#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_restoration_tool.py"

exec python3 "$TOOL" collect-event-identifiers \
  --project-root "$PROJECT_ROOT"
