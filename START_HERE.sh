#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
VERSION_FILE="$PROJECT_ROOT/config/project_version"
INVENTORY="$PROJECT_ROOT/.local/reports/BR_series_all_games_pak_listings.tar.zst"
TEXT_PACKAGE="$PROJECT_ROOT/.local/reports/BR_text_sources_all_pc_targets.tar.zst"
TRANSLATION_REPORT="$PROJECT_ROOT/.local/reports/BR_translation_base_report.tar.zst"
BASE_VALIDATION="$PROJECT_ROOT/.local/reports/BR_project_base_validation.tar.zst"
PATCHER_VALIDATION="$PROJECT_ROOT/.local/reports/BR_pc_patcher_architecture_validation.tar.zst"
WORKSTREAM_VALIDATION="$PROJECT_ROOT/.local/reports/core/BR_PARALLEL_WORKSTREAM_VALIDATION.json"

printf 'Blue Reflection series translation project\n'
printf 'Project root: %s\n' "$PROJECT_ROOT"
printf 'Project version: %s\n\n' "$(cat "$VERSION_FILE" 2>/dev/null || printf 'unknown')"

if [[ ! -f "$PATHS_FILE" ]]; then
  printf 'Local path configuration is missing:\n  %s\n\n' "$PATHS_FILE"
  printf 'Run the installer or copy config/paths.example.sh there.\n'
  exit 1
fi

# shellcheck source=/dev/null
source "$PATHS_FILE"

check_required_path() {
  local label="$1"
  local value="$2"
  if [[ -n "$value" && -d "$value" ]]; then
    printf '[OK]      %-34s %s\n' "$label" "$value"
  elif [[ -n "$value" ]]; then
    printf '[MISSING] %-34s %s\n' "$label" "$value"
  else
    printf '[MISSING] %-34s not configured\n' "$label"
  fi
}

check_required_path "BLUE REFLECTION original" "${BR1_ORIGINAL_ROOT:-}"
check_required_path "BLUE REFLECTION Quartet" "${BR1_QUARTET_ROOT:-}"
check_required_path "BLUE REFLECTION: Second Light" "${BR_SECOND_LIGHT_ROOT:-}"

printf '\nWorkflow status:\n'
[[ -f "$INVENTORY" ]] && \
  printf '[DONE]    01 inventory of all PC installations\n' || \
  printf '[NEXT]    01 inventory of all PC installations\n'

if [[ -f "$TEXT_PACKAGE" ]]; then
  printf '[DONE]    02 extracted PC text sources\n'
elif [[ -f "$INVENTORY" ]]; then
  printf '[NEXT]    02 extract PC text sources\n'
else
  printf '[WAIT]    02 extract PC text sources\n'
fi

if [[ -f "$TRANSLATION_REPORT" ]]; then
  printf '[DONE]    03 created canonical translation databases\n'
elif [[ -f "$TEXT_PACKAGE" ]]; then
  printf '[NEXT]    03 validate and create translation databases\n'
else
  printf '[WAIT]    03 validate and create translation databases\n'
fi

if [[ -f "$BASE_VALIDATION" ]]; then
  printf '[DONE]    04 validated translation bases and module architecture\n'
elif [[ -f "$TRANSLATION_REPORT" ]]; then
  printf '[NEXT]    04 validate translation bases and module architecture\n'
else
  printf '[WAIT]    04 validate translation bases and module architecture\n'
fi

if [[ -f "$PATCHER_VALIDATION" ]]; then
  printf '[DONE]    05 validated unified PC patcher/distribution architecture\n'
elif [[ -f "$BASE_VALIDATION" ]]; then
  printf '[NEXT]    05 validate unified PC patcher/distribution architecture\n'
else
  printf '[WAIT]    05 validate unified PC patcher/distribution architecture\n'
fi

if [[ -f "$WORKSTREAM_VALIDATION" ]]; then
  printf '[DONE]    06 validated parallel workstream ownership and versions\n'
  printf '[PAUSE]   Translation and restoration may now continue independently.\n'
elif [[ -f "$PATCHER_VALIDATION" ]]; then
  printf '[NEXT]    06 validate parallel workstream architecture\n'
else
  printf '[WAIT]    06 validate parallel workstream architecture\n'
fi

printf '\nDistribution model:\n'
printf '[READY]   One logical bundle for Original, Quartet and Second Light\n'
printf '[READY]   Linux/Windows detection and deterministic module planning\n'
printf '[READY]   Translation/restoration/DLC independent selection\n'
printf '[READY]   Content-aware rebuild preserves unrelated PAK modifications\n'
printf '[GATED]   Game-writing apply engine until stable import/repack tests\n'
printf '[PLANNED] Switch LayeredFS adapters share canonical records\n'

printf '\nParallel workstreams:\n'
printf '[ACTIVE]  Translation tooling: %s\n' "$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation_tooling/VERSION")"
printf '          %q\n' "$PROJECT_ROOT/workstreams/translation_tooling/START_HERE.sh"
printf '[ACTIVE]  Translation content: %s\n' "$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
printf '          %q\n' "$PROJECT_ROOT/workstreams/translation/START_HERE.sh"
printf '[READY]   Quartet restoration: %s\n' "$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_restoration/VERSION")"
printf '          %q\n' "$PROJECT_ROOT/workstreams/quartet_restoration/START_HERE.sh"
printf '[DEFER]   Legacy DLC: %s\n' "$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")"
printf '[POLICY]  Workstream update packages have independent versions and path ownership.\n'

printf '\nNext safe action:\n'
if [[ -f "$WORKSTREAM_VALIDATION" ]]; then
  printf '  %q\n' "$PROJECT_ROOT/workstreams/translation/START_HERE.sh"
elif [[ -f "$PATCHER_VALIDATION" ]]; then
  printf '  %q\n' "$PROJECT_ROOT/06_validate_parallel_workstreams.sh"
elif [[ -f "$BASE_VALIDATION" ]]; then
  printf '  %q\n' "$PROJECT_ROOT/05_validate_patcher_architecture.sh"
elif [[ -f "$TRANSLATION_REPORT" ]]; then
  printf '  %q\n' "$PROJECT_ROOT/04_validate_project_base.sh"
elif [[ -f "$TEXT_PACKAGE" ]]; then
  printf '  %q\n' "$PROJECT_ROOT/03_create_translation_base.sh"
elif [[ -f "$INVENTORY" ]]; then
  printf '  %q\n' "$PROJECT_ROOT/02_extract_text_sources.sh"
else
  printf '  %q\n' "$PROJECT_ROOT/01_inventory_archives.sh"
fi
