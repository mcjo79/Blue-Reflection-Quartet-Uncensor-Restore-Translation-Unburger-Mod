#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
PROFILE_ID="fast_test_kps_posteffectglowlight_target_dword_61389ebb65bb"
AUTH_TOKEN="--user-authorized-glowlight-test"
CORE_ROUTE="$PROJECT_ROOT/Blue_Reflection_Patcher/cmd/br_quartet_shader_profile.sh"
PYTHON_TOOL="$SCRIPT_DIR/146_glowlight_fast_test_lab.py"

fail() { printf '[glowlight-fast-test] ERROR: %s\n' "$*" >&2; exit 1; }
usage() {
  cat <<'EOF'
Usage:
  146_glowlight_fast_test_lab.sh preflight
  146_glowlight_fast_test_lab.sh activate --user-authorized-glowlight-test
  146_glowlight_fast_test_lab.sh status
  146_glowlight_fast_test_lab.sh rollback

Activation requires the explicit authorization token. Preflight is read-only.
Only GlowLight is supported; Gamma cannot be selected by this wrapper.
EOF
}

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
# shellcheck disable=SC1090
source "$PATHS_FILE"
[[ -n "${BR1_QUARTET_ROOT:-}" ]] || fail "BR1_QUARTET_ROOT is empty"
[[ -d "$BR1_QUARTET_ROOT" ]] || fail "Quartet game root not found: $BR1_QUARTET_ROOT"
[[ -x "$CORE_ROUTE" ]] || fail "Missing core transaction route: $CORE_ROUTE"
[[ -f "$PYTHON_TOOL" ]] || fail "Missing stage-146 validator: $PYTHON_TOOL"
[[ $# -ge 1 ]] || { usage >&2; exit 2; }
action="$1"

case "$action" in
  preflight)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    python3 "$PYTHON_TOOL" preflight --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT"
    printf '[glowlight-fast-test] Read-only preflight passed. No game file was modified.\n'
    ;;
  activate)
    [[ $# -eq 2 && "$2" == "$AUTH_TOKEN" ]] || fail "GlowLight activation requires explicit token: $AUTH_TOKEN"
    preflight="$(python3 "$PYTHON_TOOL" preflight --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    mode="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["mode"])' <<<"$preflight")"
    python3 "$PYTHON_TOOL" prepare-guard --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT" >/dev/null
    if [[ "$mode" == "activate" ]]; then
      bash "$CORE_ROUTE" activate "$PROFILE_ID"
    elif [[ "$mode" == "already_active" ]]; then
      printf '[glowlight-fast-test] GlowLight is already active; validating the existing transaction.\n'
      bash "$CORE_ROUTE" status
    else
      fail "Unexpected preflight mode: $mode"
    fi
    report="$(python3 "$PYTHON_TOOL" collect-activation --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    printf '\n[glowlight-fast-test] GlowLight profile is ACTIVE.\n'
    printf '[glowlight-fast-test] PACK10_03 guard is active and unchanged.\n'
    printf '[glowlight-fast-test] Evidence: %s\n' "$report"
    printf '[glowlight-fast-test] Evidence SHA-256: '
    sha256sum "$report" | awk '{print $1}'
    cat <<'EOF'

NEXT:
  1. Launch Quartet and start New Game.
  2. Observe stability and any clearly distinguishable GlowLight/posteffect change.
  3. Exit the game completely.
  4. Run the stage-146 rollback command before any other PACK10_01 test.

Do not change PACK10_03 during this test. Stability alone does not validate GlowLight.
EOF
    ;;
  status)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    bash "$CORE_ROUTE" status
    ;;
  rollback)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    bash "$CORE_ROUTE" rollback
    report="$(python3 "$PYTHON_TOOL" collect-rollback --project-root "$PROJECT_ROOT" --quartet-root "$BR1_QUARTET_ROOT")"
    printf '\n[glowlight-fast-test] Exact PACK10_01 baseline restored.\n'
    printf '[glowlight-fast-test] PACK10_03 remained byte-identical to its pre-activation guard.\n'
    printf '[glowlight-fast-test] Evidence: %s\n' "$report"
    printf '[glowlight-fast-test] Evidence SHA-256: '
    sha256sum "$report" | awk '{print $1}'
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
