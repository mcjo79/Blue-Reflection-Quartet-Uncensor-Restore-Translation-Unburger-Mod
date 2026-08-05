#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck source=/dev/null
source "$PATHS_FILE"
[[ -n "${BR1_ORIGINAL_ROOT:-}" ]] || fail "BR1_ORIGINAL_ROOT is empty"
[[ -d "$BR1_ORIGINAL_ROOT" ]] || fail "Original game root not found: $BR1_ORIGINAL_ROOT"

exec python3 -u "$SCRIPT_DIR/collect_br1_source_archive_provenance_evidence.py" \
  --project-root "$PROJECT_ROOT" \
  --game-root "$BR1_ORIGINAL_ROOT" \
  "$@"
