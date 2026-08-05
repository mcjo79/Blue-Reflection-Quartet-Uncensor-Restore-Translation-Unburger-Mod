#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/quartet_restoration/build_residual_shared_presentation_prototype.py"

if [[ ! -f "$TOOL" ]]; then
  printf 'ERROR: Missing shared-presentation prototype tool: %s\n' "$TOOL" >&2
  exit 1
fi

exec python3 "$TOOL" --project-root "$PROJECT_ROOT" "$@"
