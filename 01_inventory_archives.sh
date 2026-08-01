#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
COLLECTOR="$PROJECT_ROOT/Blue_Reflection_Text_Tool/collect_pak_listings.sh"
REPORT_DIR="$PROJECT_ROOT/.local/reports"
REPORT_FILE="$REPORT_DIR/BR_series_all_games_pak_listings.tar.zst"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$PATHS_FILE" ]] || die "Missing local path configuration: $PATHS_FILE"
[[ -x "$COLLECTOR" ]] || die "Collector is missing or not executable: $COLLECTOR"

# shellcheck source=/dev/null
source "$PATHS_FILE"

require_game_root() {
  local variable_name="$1"
  local label="$2"
  local value="${!variable_name:-}"

  [[ -n "$value" ]] || die "$variable_name is empty ($label)"
  [[ -d "$value" ]] || die "$label directory not found: $value"
}

require_game_root BR1_ORIGINAL_ROOT "BLUE REFLECTION original"
require_game_root BR1_QUARTET_ROOT "BLUE REFLECTION Quartet"
require_game_root BR_SECOND_LIGHT_ROOT "BLUE REFLECTION: Second Light"

find_gust_pak() {
  local candidate

  if [[ -n "${GUST_PAK:-}" && -x "$GUST_PAK" ]]; then
    realpath -- "$GUST_PAK"
    return 0
  fi

  for candidate in \
    "$PROJECT_ROOT/.local/vendor/gust_tools/gust_pak" \
    "$HOME/Downloads/gust_tools/gust_pak"
  do
    if [[ -x "$candidate" ]]; then
      realpath -- "$candidate"
      return 0
    fi
  done

  if command -v gust_pak >/dev/null 2>&1; then
    command -v gust_pak
    return 0
  fi

  return 1
}

GUST_PAK_BIN="$(find_gust_pak || true)"
if [[ -z "$GUST_PAK_BIN" ]]; then
  cat >&2 <<EOF
ERROR: gust_pak was not found.

Build it inside the ignored local vendor directory:

  git clone --depth 1 https://github.com/VitaSmith/gust_tools.git \
    "$PROJECT_ROOT/.local/vendor/gust_tools"

  make -C "$PROJECT_ROOT/.local/vendor/gust_tools" gust_pak

Then run this wrapper again.
EOF
  exit 1
fi

mkdir -p -- "$REPORT_DIR"

"$COLLECTOR" \
  "$GUST_PAK_BIN" \
  "$REPORT_FILE" \
  blue_reflection_original "$BR1_ORIGINAL_ROOT" \
  blue_reflection_quartet "$BR1_QUARTET_ROOT" \
  second_light_original "$BR_SECOND_LIGHT_ROOT"

printf '\nInventory completed without extracting or modifying game assets.\n'
printf 'Upload this report for archive mapping:\n  %s\n' "$REPORT_FILE"
printf '\nDo not start text extraction yet; the next wrapper will be generated after this report is analyzed.\n'
