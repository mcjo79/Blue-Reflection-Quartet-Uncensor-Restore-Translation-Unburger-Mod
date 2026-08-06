#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
PROFILE_ID="fast_test_kps_posteffectgamma_target_dword_3c4565adce04"
CORE_ROUTE="$PROJECT_ROOT/Blue_Reflection_Patcher/cmd/br_quartet_shader_profile.sh"
PYTHON_TOOL="$SCRIPT_DIR/144_gamma_fast_test_lab.py"

fail() { printf '[gamma-fast-test] ERROR: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage:
  144_gamma_fast_test_lab.sh activate
  144_gamma_fast_test_lab.sh status
  144_gamma_fast_test_lab.sh rollback

Only the Gamma Fast Test Lab profile is supported. GlowLight is deliberately blocked.
EOF
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck disable=SC1090
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"
[[ -x "$CORE_ROUTE" ]] || fail "Missing core transaction route: $CORE_ROUTE"
[[ -f "$PYTHON_TOOL" ]] || fail "Missing stage-144 validator: $PYTHON_TOOL"
[[ $# -eq 1 ]] || { usage >&2; exit 2; }
action="$1"

case "$action" in
  activate)
    preflight="$(python3 "$PYTHON_TOOL" preflight --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    mode="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["mode"])' <<<"$preflight")"
    if [[ "$mode" == "activate" ]]; then
      bash "$CORE_ROUTE" activate "$PROFILE_ID"
    elif [[ "$mode" == "already_active" ]]; then
      printf '[gamma-fast-test] Gamma is already active; validating the existing transaction.\n'
      bash "$CORE_ROUTE" status
    else
      fail "Unexpected preflight mode: $mode"
    fi
    report="$(python3 "$PYTHON_TOOL" collect-activation --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    printf '\n[gamma-fast-test] Gamma profile is ACTIVE.\n'
    printf '[gamma-fast-test] Evidence: %s\n' "$report"
    printf '[gamma-fast-test] Evidence SHA-256: '
    sha256sum "$report" | awk '{print $1}'
    cat <<'EOF'

NEXT:
  1. Launch Quartet.
  2. Start New Game.
  3. Observe boot stability, the first cutscene, the transition after it, and any visible Gamma/posteffect change.
  4. Exit the game completely.
  5. Run: bash workstreams/quartet_restoration/144_gamma_fast_test_lab.sh rollback

Do not activate GlowLight before rollback and review.
EOF
    ;;
  status)
    bash "$CORE_ROUTE" status
    ;;
  rollback)
    bash "$CORE_ROUTE" rollback
    report="$(python3 "$PYTHON_TOOL" collect-rollback --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    printf '\n[gamma-fast-test] Exact PACK10_01 baseline restored.\n'
    printf '[gamma-fast-test] Evidence: %s\n' "$report"
    printf '[gamma-fast-test] Evidence SHA-256: '
    sha256sum "$report" | awk '{print $1}'
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
