#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
REPORT_JSON="$PROJECT_ROOT/.local/reports/core/BR_QUARTET_FIELD_PROFILE_TRANSACTION_REPORT.json"
REPORT_PACKAGE="$PROJECT_ROOT/.local/reports/core/BR_quartet_field_profile_transaction_report.tar.zst"
STATE_REL=".local/state/core_unified_patcher/quartet_field_profile.json"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage:
  br_quartet_field_profile.sh activate PROFILE_ID
  br_quartet_field_profile.sh status
  br_quartet_field_profile.sh rollback

Profile IDs are discovered from local quartet_restoration manifests targeting
Data/PACK10_03.PAK. Core enforces mutual exclusion with event and shader profile
transactions.
USAGE
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck source=/dev/null
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"
command -v go >/dev/null 2>&1 || fail "go is required"

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
action="$1"
shift
case "$action" in
  activate)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    command_name="quartet-field-profile-activate"
    extra=("$1")
    ;;
  status)
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    command_name="quartet-field-profile-status"
    extra=()
    ;;
  rollback)
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    command_name="quartet-field-profile-rollback"
    extra=()
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

(
  cd "$PATCHER_ROOT"
  go run ./cmd/brpatcher "$command_name" \
    --project-root "$PROJECT_ROOT" \
    --game-root "$BR1_QUARTET_ROOT" \
    "${extra[@]}"
)

if [[ -f "$REPORT_JSON" ]] && command -v tar >/dev/null 2>&1 && command -v zstd >/dev/null 2>&1; then
  mkdir -p "$(dirname -- "$REPORT_PACKAGE")"
  items=(".local/reports/core/BR_QUARTET_FIELD_PROFILE_TRANSACTION_REPORT.json")
  [[ -f "$PROJECT_ROOT/$STATE_REL" ]] && items+=("$STATE_REL")
  rm -f -- "$REPORT_PACKAGE"
  tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" "${items[@]}"
  printf '\nReport package:\n  %s\n' "$REPORT_PACKAGE"
fi
