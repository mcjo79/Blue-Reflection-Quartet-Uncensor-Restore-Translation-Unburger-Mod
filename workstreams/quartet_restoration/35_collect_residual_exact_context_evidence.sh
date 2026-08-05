#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/collect_residual_exact_context_evidence.py"

if [[ ! -f "$TOOL" ]]; then
  printf 'ERROR: Missing residual exact-context tool: %s\n' "$TOOL" >&2
  exit 1
fi

exec python3 "$TOOL" --project-root "$PROJECT_ROOT" "$@"
