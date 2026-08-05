#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/translation_game_test.py"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/translation"
REPORT_JSON="$REPORT_ROOT/BR_TRANSLATION_GAME_TEST_REPORT.json"
REPORT_PACKAGE="$REPORT_ROOT/BR_translation_game_test_report.tar.zst"
fail(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
usage(){ cat <<'EOF'
Usage: 09_test_translation_in_game.sh install|status|restore TARGET
Targets: blue_reflection_original | blue_reflection_quartet | second_light_original
EOF
}
[[ $# -eq 2 ]] || { usage >&2; exit 2; }
ACTION="$1"; TARGET="$2"
case "$ACTION" in install|status|restore);; *) usage >&2; exit 2;; esac
for c in python3 tar zstd; do command -v "$c" >/dev/null || fail "$c is required"; done
[[ -f "$PATHS_FILE" ]] || fail "Missing $PATHS_FILE"
[[ -x "$TOOL" ]] || fail "Missing executable tool: $TOOL"
source "$PATHS_FILE"
case "$TARGET" in
 blue_reflection_original) GAME_ROOT="${BR1_ORIGINAL_ROOT:-}";;
 blue_reflection_quartet) GAME_ROOT="${BR1_QUARTET_ROOT:-}";;
 second_light_original) GAME_ROOT="${BR_SECOND_LIGHT_ROOT:-}";;
 *) usage >&2; exit 2;;
esac
[[ -n "$GAME_ROOT" && -d "$GAME_ROOT" ]] || fail "Invalid configured game root: $GAME_ROOT"
mkdir -p "$REPORT_ROOT"
"$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_lock.sh" "$PROJECT_ROOT" translation_tooling -- python3 "$TOOL" "$ACTION" --project-root "$PROJECT_ROOT" --target "$TARGET" --game-root "$GAME_ROOT"
if [[ -f "$REPORT_JSON" ]]; then
 rm -f "$REPORT_PACKAGE"; ITEMS=(.local/reports/translation/BR_TRANSLATION_GAME_TEST_REPORT.json); STATE=".local/state/translation_game_test/$TARGET.json"; [[ -f "$PROJECT_ROOT/$STATE" ]] && ITEMS+=("$STATE"); tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" "${ITEMS[@]}"; printf '\nReport:\n  %s\n' "$REPORT_PACKAGE"
fi
if [[ "$ACTION" == install ]]; then
 cat <<EOF

Manual smoke test:
  1. Launch only $TARGET.
  2. Check the title screen and menus.
  3. Confirm whether the lower title label reads exactly:
       UNBURGER / UNCENSOR
     For Original and Quartet, the marker is read from the patched unused
     region of the existing a17_common.g1t resource.
  4. Load/start a scene and advance dialogue.
  5. Exit the game completely.
  6. Restore with:
     $PROJECT_ROOT/workstreams/translation_tooling/09_test_translation_in_game.sh restore $TARGET
EOF
fi
