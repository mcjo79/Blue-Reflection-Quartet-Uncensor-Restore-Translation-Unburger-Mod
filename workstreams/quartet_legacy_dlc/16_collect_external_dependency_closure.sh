#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_legacy_dlc/br_dlc_external_closure_tool.py"
[[ -f "$TOOL" ]] || { printf 'ERROR: missing external closure tool: %s\n' "$TOOL" >&2; exit 1; }
exec python3 "$TOOL" audit --project-root "$PROJECT_ROOT"
