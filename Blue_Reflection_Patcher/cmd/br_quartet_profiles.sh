#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage:
  br_quartet_profiles.sh list

Discovers read-only quartet_restoration profile manifests below:
  .local/build/quartet_restoration/core_profiles/
USAGE
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck source=/dev/null
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"
command -v go >/dev/null 2>&1 || fail "go is required"

[[ $# -eq 1 ]] || { usage >&2; exit 2; }
[[ "$1" == "list" ]] || { usage >&2; exit 2; }

(
  cd "$PATCHER_ROOT"
  go run ./cmd/brpatcher quartet-local-profile-list \
    --project-root "$PROJECT_ROOT" \
    --game-root "$BR1_QUARTET_ROOT"
)
