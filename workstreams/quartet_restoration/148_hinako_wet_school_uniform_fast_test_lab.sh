#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
PYTHON_TOOL="$SCRIPT_DIR/148_hinako_wet_school_uniform_fast_test_lab.py"
AUTH_TOKEN="--user-authorized-wet-school-test"

fail() { printf '[wet-school-fast-test] ERROR: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage:
  148_hinako_wet_school_uniform_fast_test_lab.sh preflight
  148_hinako_wet_school_uniform_fast_test_lab.sh activate --user-authorized-wet-school-test
  148_hinako_wet_school_uniform_fast_test_lab.sh status
  148_hinako_wet_school_uniform_fast_test_lab.sh rollback

The activation targets only Data/PACK10_02.PAK and requires the exact stage-147
baseline and profile. PACK10_01, PACK10_03 and PACK11 are read-only guards.
EOF
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck disable=SC1090
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"
[[ -f "$PYTHON_TOOL" ]] || fail "Missing stage-148 transaction tool: $PYTHON_TOOL"
[[ $# -ge 1 ]] || { usage >&2; exit 2; }
action="$1"

case "$action" in
  preflight)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    python3 "$PYTHON_TOOL" preflight --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT"
    printf '[wet-school-fast-test] Read-only preflight passed. No game file was modified.\n'
    ;;
  activate)
    [[ $# -eq 2 && "$2" == "$AUTH_TOKEN" ]] || fail "Activation requires explicit token: $AUTH_TOKEN"
    python3 "$PYTHON_TOOL" activate --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT"
    report="$(python3 "$PYTHON_TOOL" collect-activation --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    printf '\n[wet-school-fast-test] ACTIVE: only the stage-147 PACK10_02 Fast Test profile is installed.\n'
    printf '[wet-school-fast-test] PACK10_01, PACK10_03 and PACK11 passed byte guards.\n'
    printf '[wet-school-fast-test] Activation evidence: %s\n' "$report"
    printf '[wet-school-fast-test] Activation evidence SHA-256: '
    sha256sum "$report" | awk '{print $1}'
    cat <<'EOF'

TEST NOW:
  1. Launch Quartet and load the existing save that immediately shows Hinako's wet school uniform.
  2. Observe whether the game loads without a crash.
  3. If stable, compare the wet / see-through appearance with the normal Quartet baseline.
  4. Exit the game completely.
  5. Run the stage-148 rollback before any other PACK10_02 experiment.

A stable game alone does NOT validate the visual effect.
GlowLight remains deferred and untouched.
EOF
    ;;
  status)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    python3 "$PYTHON_TOOL" status --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT"
    ;;
  rollback)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    python3 "$PYTHON_TOOL" rollback --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT"
    report="$(python3 "$PYTHON_TOOL" collect-rollback --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    printf '\n[wet-school-fast-test] Exact stage-147 PACK10_02 baseline restored.\n'
    printf '[wet-school-fast-test] PACK10_01, PACK10_03 and PACK11 remained byte-identical.\n'
    printf '[wet-school-fast-test] Rollback evidence: %s\n' "$report"
    printf '[wet-school-fast-test] Rollback evidence SHA-256: '
    sha256sum "$report" | awk '{print $1}'
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
