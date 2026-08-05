#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/runtime_pak_trace.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_RUNTIME_PAK_TRACE_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_runtime_pak_trace_report.tar.zst"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: 10_trace_runtime_pak_usage.sh TARGET
Targets:
  blue_reflection_original
  blue_reflection_quartet
  second_light_original
EOF
}

[[ $# -eq 1 ]] || { usage >&2; exit 2; }
TARGET="$1"

for command in python3 inotifywait tar zstd; do
  command -v "$command" >/dev/null 2>&1 || {
    if [[ "$command" == "inotifywait" ]]; then
      fail "inotifywait is required. Install it with: sudo pacman -S inotify-tools"
    fi
    fail "$command is required"
  }
done

[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -x "$TOOL" ]] || fail "Missing executable tracer: $TOOL"
# shellcheck source=/dev/null
source "$PATHS_FILE"

case "$TARGET" in
  blue_reflection_original)
    GAME_ROOT="${BR1_ORIGINAL_ROOT:-}"
    ;;
  blue_reflection_quartet)
    GAME_ROOT="${BR1_QUARTET_ROOT:-}"
    ;;
  second_light_original)
    GAME_ROOT="${BR_SECOND_LIGHT_ROOT:-}"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

[[ -n "$GAME_ROOT" && -d "$GAME_ROOT" ]] || \
  fail "Invalid configured game root: $GAME_ROOT"

"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" \
  "$PROJECT_ROOT" translation_tooling -- \
  python3 "$TOOL" \
    --project-root "$PROJECT_ROOT" \
    --game-root "$GAME_ROOT" \
    --target "$TARGET"

[[ -f "$REPORT_JSON" ]] || fail "Runtime trace report was not created"

TRANSACTION_ID="$(
  python3 - "$REPORT_JSON" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["transaction_id"])
PY
)"
TRACE_DIR=".local/reports/translation/runtime_trace/$TRANSACTION_ID"
[[ -d "$PROJECT_ROOT/$TRACE_DIR" ]] || fail "Trace directory is missing"

rm -f -- "$REPORT_PACKAGE"
tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" \
  .local/reports/translation/BR_RUNTIME_PAK_TRACE_REPORT.json \
  "$TRACE_DIR"

printf '\nUpload this report before restoring the diagnostic build:\n'
printf '  %s\n' "$REPORT_PACKAGE"
