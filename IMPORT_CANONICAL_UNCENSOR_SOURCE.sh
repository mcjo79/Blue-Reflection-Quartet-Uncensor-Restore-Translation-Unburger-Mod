#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
CACHE_ROOT="$PROJECT_ROOT/.local/Uncensor/quartet_wet_school_canonical_source_v1"
LEGACY_CACHE_ROOT="$PROJECT_ROOT/.local/release/quartet_wet_school_canonical_source_v1"
SOURCE_STATE="$PROJECT_ROOT/.local/Uncensor/BR1_CANONICAL_RUNTIME_SOURCE_PATH"
LEGACY_SOURCE_STATE="$PROJECT_ROOT/.local/release/BR1_CANONICAL_RUNTIME_SOURCE_PATH"
LOCAL_PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
HASH_CONTRACT="$PROJECT_ROOT/workstreams/core/contracts/release/DLC_SOURCE_ARCHIVE_HASHES_V1.json"
SOURCE=""

usage() {
  cat <<'TXT'
Usage: ./IMPORT_CANONICAL_UNCENSOR_SOURCE.sh [--source PATH]

One-time developer import of the canonical BLUE REFLECTION (2017) wet-school
source used by Quartet UNCENSOR release builds. The importer verifies the clean
retail PACK00_02.PAK, extracts only the proven PC00-PC14 SCL_W donor family
(30 members), and stores a validated reduced capability under .local/Uncensor/.

After this succeeds, normal BUILD_RELEASE.sh runs do not require the BLUE
REFLECTION (2017) installation to remain present.
TXT
}

while (($#)); do
  case "$1" in
    --source) SOURCE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for cmd in go jq sha256sum python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 1; }
done
[[ -f "$HASH_CONTRACT" ]] || { echo "ERROR: missing source hash contract" >&2; exit 1; }

normalize() {
  python3 - "$1" <<'PY'
import os,sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
}

find_pack() {
  local root="$1"
  for rel in DATA/PACK00_02.PAK Data/PACK00_02.PAK data/PACK00_02.PAK; do
    if [[ -f "$root/$rel" ]]; then printf '%s\n' "$root/$rel"; return 0; fi
  done
  return 1
}

valid_source() {
  local root="$1" pack
  [[ -d "$root" ]] || return 1
  pack="$(find_pack "$root" 2>/dev/null || true)"
  [[ -n "$pack" ]]
}

if [[ -n "$SOURCE" ]]; then
  SOURCE="$(normalize "$SOURCE")"
elif [[ -f "$SOURCE_STATE" ]]; then
  candidate="$(head -n1 "$SOURCE_STATE" | tr -d '\r\n')"
  if [[ -n "$candidate" ]]; then
    candidate="$(normalize "$candidate")"
    valid_source "$candidate" && SOURCE="$candidate"
  fi
elif [[ -f "$LEGACY_SOURCE_STATE" ]]; then
  candidate="$(head -n1 "$LEGACY_SOURCE_STATE" | tr -d '\r\n')"
  if [[ -n "$candidate" ]]; then
    candidate="$(normalize "$candidate")"
    valid_source "$candidate" && SOURCE="$candidate"
  fi
fi

if [[ -z "$SOURCE" && -f "$LOCAL_PATHS_FILE" ]]; then
  set +u
  # shellcheck disable=SC1090
  source "$LOCAL_PATHS_FILE"
  set -u
  if [[ -n "${BR1_ORIGINAL_ROOT:-}" ]]; then
    candidate="$(normalize "$BR1_ORIGINAL_ROOT")"
    valid_source "$candidate" && SOURCE="$candidate"
  fi
fi

if [[ -z "$SOURCE" ]]; then
  for candidate in \
    "$HOME/.steam/debian-installation/steamapps/common/BLUE REFLECTION" \
    "$HOME/.steam/steam/steamapps/common/BLUE REFLECTION" \
    "$HOME/.local/share/Steam/steamapps/common/BLUE REFLECTION"; do
    candidate="$(normalize "$candidate")"
    if valid_source "$candidate"; then SOURCE="$candidate"; break; fi
  done
fi

[[ -n "$SOURCE" ]] || {
  echo "ERROR: BLUE REFLECTION (2017) source was not found for the one-time import." >&2
  echo "Run: ./IMPORT_CANONICAL_UNCENSOR_SOURCE.sh --source /path/to/BLUE_REFLECTION" >&2
  exit 1
}
PACK="$(find_pack "$SOURCE")"

EXPECTED_SIZE="$(jq -r '.games[] | select(.id=="blue_reflection_2017") | .files[] | select(.path=="DATA/PACK00_02.PAK") | .size' "$HASH_CONTRACT")"
EXPECTED_SHA="$(jq -r '.games[] | select(.id=="blue_reflection_2017") | .files[] | select(.path=="DATA/PACK00_02.PAK") | .sha256 | ascii_downcase' "$HASH_CONTRACT")"
[[ "$EXPECTED_SIZE" =~ ^[0-9]+$ && "$EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: canonical PACK00_02 contract missing" >&2; exit 1; }
ACTUAL_SIZE="$(stat -c '%s' -- "$PACK")"
ACTUAL_SHA="$(sha256sum -- "$PACK" | awk '{print tolower($1)}')"
[[ "$ACTUAL_SIZE" == "$EXPECTED_SIZE" ]] || { echo "ERROR: canonical BR1 PACK00_02 size drift" >&2; exit 1; }
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || { echo "ERROR: canonical BR1 PACK00_02 SHA-256 drift" >&2; exit 1; }

echo "==> Import canonical UNCENSOR source into local project cache"
mkdir -p "$(dirname "$CACHE_ROOT")"
if [[ ! -e "$CACHE_ROOT" && -d "$LEGACY_CACHE_ROOT" ]]; then
  echo "==> Migrate legacy canonical UNCENSOR source out of .local/release"
  mv "$LEGACY_CACHE_ROOT" "$CACHE_ROOT"
fi
NEW_CACHE="$(mktemp -d "$(dirname "$CACHE_ROOT")/.quartet-wet-source-import-XXXXXX")"
BACKUP_CACHE=""
cleanup_import() {
  [[ -z "${NEW_CACHE:-}" ]] || rm -rf "$NEW_CACHE"
  if [[ -n "${BACKUP_CACHE:-}" && -d "$BACKUP_CACHE" && ! -d "$CACHE_ROOT" ]]; then
    mv "$BACKUP_CACHE" "$CACHE_ROOT" || true
  fi
}
trap cleanup_import EXIT
(
  cd "$PATCHER_ROOT"
  go run ./cmd/unburger-canonical-source --import --source "$SOURCE" --output "$NEW_CACHE"
  go run ./cmd/unburger-canonical-source --verify --input "$NEW_CACHE"
)
if [[ -e "$CACHE_ROOT" ]]; then
  BACKUP_CACHE="$CACHE_ROOT.previous.$$"
  mv "$CACHE_ROOT" "$BACKUP_CACHE"
fi
mv "$NEW_CACHE" "$CACHE_ROOT"
NEW_CACHE=""
(
  cd "$PATCHER_ROOT"
  go run ./cmd/unburger-canonical-source --verify --input "$CACHE_ROOT"
)
if [[ -n "$BACKUP_CACHE" ]]; then rm -rf "$BACKUP_CACHE"; BACKUP_CACHE=""; fi
printf '%s\n' "$SOURCE" > "$SOURCE_STATE"
trap - EXIT

echo "CANONICAL UNCENSOR LOCAL SOURCE IMPORT: PASS"
echo "cache=.local/Uncensor/quartet_wet_school_canonical_source_v1"
