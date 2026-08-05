#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/build_fe13_remaining_residual_prototype.py"
[[ -f "$TOOL" ]] || { printf 'ERROR: Missing fe13_090 remaining-residual prototype tool: %s\n' "$TOOL" >&2; exit 1; }
exec python3 "$TOOL" --project-root "$PROJECT_ROOT" "$@"
