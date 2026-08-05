#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"

if [[ ! -f "$PATHS_FILE" ]]; then
  printf 'ERROR: missing local path configuration: %s\n' "$PATHS_FILE" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$PATHS_FILE"
if [[ -z "${BR1_ORIGINAL_ROOT:-}" || ! -d "$BR1_ORIGINAL_ROOT" ]]; then
  printf 'ERROR: BR1_ORIGINAL_ROOT is missing or invalid: %s\n' "${BR1_ORIGINAL_ROOT:-<empty>}" >&2
  exit 1
fi
exec python3 -u "$SCRIPT_DIR/collect_br1_official_source_retirement_closure_evidence.py" \
  --project-root "$PROJECT_ROOT" \
  --game-root "$BR1_ORIGINAL_ROOT" \
  "$@"
