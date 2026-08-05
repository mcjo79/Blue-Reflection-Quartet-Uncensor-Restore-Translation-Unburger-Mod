#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/collect_unselected_cue_residual_splice_evidence.py"
[[ -f "$TOOL" ]] || { printf 'ERROR: Missing unselected cue-residual splice tool: %s\n' "$TOOL" >&2; exit 1; }
exec python3 "$TOOL" --project-root "$PROJECT_ROOT" "$@"
