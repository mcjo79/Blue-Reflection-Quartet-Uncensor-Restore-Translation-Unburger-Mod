#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
OUTPUT_DIR="$PROJECT_ROOT/.local/release"
KEEP_STAGE=0
REFRESH=0
ASSETS=0
ASSETS_REBUILD=0
ASSETS_BUNDLE=""
ASSETS_SOURCE=""
CANONICAL_SOURCE=""
SECOND_LIGHT_ASSETS_SOURCE=""
QUARTET_ASSETS_TARGET=""
ASSET_BASENAME="UNBURGER_DLC_ASSETS_v3"
ASSET_ANCHORS="$PROJECT_ROOT/workstreams/core/contracts/release/BR1_LEGACY_SOURCE_MEMBER_ANCHORS_V1.json"
ASSET_SOURCE_HASH_CONTRACT="$PROJECT_ROOT/workstreams/core/contracts/release/DLC_SOURCE_ARCHIVE_HASHES_V1.json"
LOCAL_PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
ASSET_SOURCE_STATE="$PROJECT_ROOT/.local/release/BR1_ASSETS_SOURCE_PATH"
CANONICAL_SOURCE_STATE="$PROJECT_ROOT/.local/release/BR1_CANONICAL_RUNTIME_SOURCE_PATH"
SECOND_LIGHT_ASSET_SOURCE_STATE="$PROJECT_ROOT/.local/release/SECOND_LIGHT_ASSETS_SOURCE_PATH"
QUARTET_ASSET_TARGET_STATE="$PROJECT_ROOT/.local/release/QUARTET_ASSETS_TARGET_PATH"
ASSET_BUNDLE_STATE="$PROJECT_ROOT/.local/release/UNBURGER_ASSETS_BUNDLE_PATH"
ASSET_KEY_FILE="$PROJECT_ROOT/.local/secrets/unburger-assets.key"
GENERATED_ASSET_KEY_GO="$PATCHER_ROOT/internal/assetkey/embedded_key_generated.local.go"
MOVIE_ROOT="$PROJECT_ROOT/.local/Video/restored_webm"

usage() {
  cat <<'TXT'
Usage: ./BUILD_RELEASE.sh [options]

Build the complete distributable UNBURGER release ZIP from the current
project state. Translation records are regenerated from the canonical databases;
no prebuilt game PAK is used as public release content.

Options:
  --refresh                 Run the full project validation pass before packaging.
  --output-dir PATH         Destination for release artifacts.
  --keep-stage              Keep verified staging directories.
  --assets, -assets         Also emit the optional combined BR1 + Second Light DLC source-assets
                            bundle. Translation/UNCENSOR never depend on this file.
  --assets-bundle PATH      Existing verified .unburger-assets bundle to reuse.
  --assets-rebuild          Force rebuilding .unburger-assets from source games even when
                            a compatible existing bundle is available.
  --canonical-source PATH   BLUE REFLECTION (2017) source used at release-build time only to
                            embed the canonical wet-school UNCENSOR payload in .unburger.
  --assets-source PATH      BLUE REFLECTION (2017) source game folder (optional DLC bundle rebuild only).
  --assets-second-light-source PATH
                            Standalone BLUE REFLECTION: Second Light source folder.
  --assets-quartet-target PATH
                            Clean/compatible Quartet folder used only to minimize
                            the Second Light source subset. Source paths are remembered
                            after a successful assets build.
  -h, --help                Show this help.
TXT
}

while (($#)); do
  case "$1" in
    --refresh) REFRESH=1; shift ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --keep-stage) KEEP_STAGE=1; shift ;;
    --assets|-assets) ASSETS=1; shift ;;
    --assets-bundle) ASSETS_BUNDLE="${2:-}"; shift 2 ;;
    --assets-rebuild) ASSETS_REBUILD=1; shift ;;
    --canonical-source) CANONICAL_SOURCE="${2:-}"; shift 2 ;;
    --assets-source) ASSETS_SOURCE="${2:-}"; shift 2 ;;
    --assets-second-light-source) SECOND_LIGHT_ASSETS_SOURCE="${2:-}"; shift 2 ;;
    --assets-quartet-target) QUARTET_ASSETS_TARGET="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$ASSETS_BUNDLE$ASSETS_SOURCE$SECOND_LIGHT_ASSETS_SOURCE$QUARTET_ASSETS_TARGET" || "$ASSETS_REBUILD" == 1 ]]; then
  if [[ "$ASSETS" != 1 ]]; then
    echo "ERROR: assets bundle/rebuild/source options require --assets" >&2
    exit 2
  fi
fi
for cmd in go sha256sum jq zip unzip tar zstd python3 ffprobe; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 1; }
done

version_ge() {
  local lhs="$1" rhs="$2"
  [[ "$(printf '%s\n%s\n' "$rhs" "$lhs" | sort -V | tail -n1)" == "$lhs" ]]
}


normalize_root_path() {
  python3 - "$1" <<'PY_REALPATH'
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY_REALPATH
}

first_missing_required_file() {
  local root="$1"; shift
  local rel
  [[ -d "$root" ]] || { printf '%s\n' "$root"; return 0; }
  for rel in "$@"; do
    if [[ ! -f "$root/$rel" ]]; then
      printf '%s\n' "$root/$rel"
      return 0
    fi
  done
  return 1
}

resolve_rebuild_root() {
  local role="$1" explicit="$2" state_file="$3" config_hint="$4" required_name="$5"
  shift 5
  local -n required="$required_name"
  local candidate missing source_kind
  if [[ -n "$explicit" ]]; then
    candidate="$(normalize_root_path "$explicit")"
    if missing="$(first_missing_required_file "$candidate" "${required[@]}")"; then
      echo "ERROR: explicit $role is invalid; missing: $missing" >&2
      return 1
    fi
    printf '%s\n' "$candidate"
    return 0
  fi

  if [[ -f "$state_file" ]]; then
    candidate="$(head -n1 "$state_file" | tr -d '\r\n')"
    if [[ -n "$candidate" ]]; then
      candidate="$(normalize_root_path "$candidate")"
      if missing="$(first_missing_required_file "$candidate" "${required[@]}")"; then
        echo "==> Ignore stale remembered $role" >&2
        echo "    remembered: $candidate" >&2
        echo "    missing:    $missing" >&2
      else
        echo "==> Reuse previous $role" >&2
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  fi

  if [[ -n "$config_hint" ]]; then
    candidate="$(normalize_root_path "$config_hint")"
    if missing="$(first_missing_required_file "$candidate" "${required[@]}")"; then
      echo "==> Ignore invalid $role from .local/paths.sh" >&2
      echo "    configured: $candidate" >&2
      echo "    missing:    $missing" >&2
    else
      echo "==> Use $role from .local/paths.sh" >&2
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  for candidate in "$@"; do
    [[ -n "$candidate" ]] || continue
    candidate="$(normalize_root_path "$candidate")"
    if ! missing="$(first_missing_required_file "$candidate" "${required[@]}")"; then
      echo "==> Auto-detected $role" >&2
      echo "    $candidate" >&2
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "ERROR: unable to resolve a valid $role" >&2
  return 1
}

validate_source_hash_contract() {
  [[ -f "$ASSET_SOURCE_HASH_CONTRACT" ]] || {
    echo "ERROR: canonical DLC source archive hash contract is missing:" >&2
    echo "  $ASSET_SOURCE_HASH_CONTRACT" >&2
    echo "Run CAPTURE_DLC_SOURCE_ARCHIVE_HASHES.sh on the approved clean BR1 and Second Light sources, then promote the reviewed candidate into the project contract." >&2
    return 1
  }
  local anchor_fingerprint
  anchor_fingerprint="$(jq -r '.source_fingerprint // "" | ascii_downcase' "$ASSET_ANCHORS")"
  jq -e --arg anchor "$anchor_fingerprint" '
    .type == "unburger_dlc_source_archive_hashes" and
    .format_version == 1 and
    .policy == "whole-file hashes gate .unburger-assets source rebuild only; Quartet minimization target is not hash-locked" and
    ((.provenance.blue_reflection_2017_member_anchor_fingerprint | ascii_downcase) == $anchor) and
    (.provenance.blue_reflection_2017_pack00_02_official_sha1 == "f4f10dd846bbb056b81e18050ad3edc680d0bc8b") and
    (.provenance.second_light_verified_logical_members == 2942) and
    (.provenance.second_light_member_fingerprint | test("^[0-9a-fA-F]{64}$")) and
    ([.games[].id] | sort) == ["blue_reflection_2017","blue_reflection_second_light"] and
    ((.games[] | select(.id=="blue_reflection_2017") | .files | length) == 7) and
    ((.games[] | select(.id=="blue_reflection_second_light") | .files | length) == 6) and
    all(.games[].files[];
      (.path | type)=="string" and (.size | type)=="number" and .size>0 and
      (.sha256 | type)=="string" and (.sha256 | test("^[0-9a-fA-F]{64}$")))
  ' "$ASSET_SOURCE_HASH_CONTRACT" >/dev/null || {
    echo "ERROR: canonical DLC source archive hash contract is invalid: $ASSET_SOURCE_HASH_CONTRACT" >&2
    return 1
  }
}

verify_source_archive_hashes() {
  local game_id="$1" root="$2"
  local row rel expected_size expected_sha path actual_size actual_sha
  echo "==> Verify canonical source archive hashes: $game_id"
  while IFS= read -r row; do
    rel="$(jq -r '.path' <<<"$row")"
    expected_size="$(jq -r '.size' <<<"$row")"
    expected_sha="$(jq -r '.sha256 | ascii_downcase' <<<"$row")"
    path="$root/$rel"
    [[ -f "$path" ]] || { echo "ERROR: canonical source file missing: $path" >&2; return 1; }
    actual_size="$(stat -c '%s' -- "$path")"
    [[ "$actual_size" == "$expected_size" ]] || {
      echo "ERROR: source archive size drift: $path" >&2
      echo "  expected: $expected_size" >&2
      echo "  actual:   $actual_size" >&2
      return 1
    }
    actual_sha="$(sha256sum -- "$path" | awk '{print tolower($1)}')"
    [[ "$actual_sha" == "$expected_sha" ]] || {
      echo "ERROR: source archive SHA-256 drift: $path" >&2
      echo "  expected: $expected_sha" >&2
      echo "  actual:   $actual_sha" >&2
      return 1
    }
    echo "    PASS $rel"
  done < <(jq -c --arg id "$game_id" '.games[] | select(.id==$id) | .files[]' "$ASSET_SOURCE_HASH_CONTRACT")
}

CORE_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/core/VERSION")"
TRANSLATION_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
RESTORATION_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_restoration/VERSION")"
DLC_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")"
[[ -n "$CORE_VERSION" && -n "$TRANSLATION_VERSION" && -n "$RESTORATION_VERSION" && -n "$DLC_VERSION" ]] || {
  echo "ERROR: required VERSION file is empty" >&2; exit 1;
}
if [[ "${UNBURGER_ALLOW_PRE_RELEASE_TRANSLATION:-0}" != 1 ]] && ! version_ge "$TRANSLATION_VERSION" "0.0.203"; then
  echo "ERROR: Translation $TRANSLATION_VERSION is not release-closed; need 0.0.203 or newer" >&2
  exit 1
fi

if ((ASSETS)); then
  if [[ ! -f "$ASSET_ANCHORS" ]]; then
    echo "ERROR: verified BLUE REFLECTION source-member checks are missing from this project build." >&2
    echo "Repair/update the project before emitting source assets." >&2
    exit 1
  fi
  jq -e '.type == "unburger_br1_dlc_clean_source_anchors" and .format_version == 1 and .capability == "br1_legacy_clean_source_anchors_v1" and (.source_members | length) == 1682' "$ASSET_ANCHORS" >/dev/null || {
    echo "ERROR: verified BLUE REFLECTION source-member checks are invalid" >&2
    exit 1
  }
fi

mkdir -p "$OUTPUT_DIR" "$PROJECT_ROOT/.local/release/work"
WORK_DIR="$(mktemp -d "$PROJECT_ROOT/.local/release/work/unburger-release-XXXXXX")"
BUNDLE_STAGE="$WORK_DIR/bundle"
RELEASE_STAGE="$WORK_DIR/release"
cleanup() {
  rm -f "$GENERATED_ASSET_KEY_GO"
  if ((KEEP_STAGE)); then
    echo "Release staging retained: $WORK_DIR"
  else
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

if ((REFRESH)); then
  echo "==> Project validation"
  "$PROJECT_ROOT/04_validate_project_base.sh"
fi

echo "==> Go regression"
(
  cd "$PATCHER_ROOT"
  go test ./...
  go vet ./...
)

echo "==> Prepare local assets encryption key"
mkdir -p "$(dirname "$ASSET_KEY_FILE")"
if [[ ! -f "$ASSET_KEY_FILE" ]]; then
  umask 077
  head -c 32 /dev/urandom > "$ASSET_KEY_FILE"
  chmod 0600 "$ASSET_KEY_FILE"
  echo "Created local key: $ASSET_KEY_FILE"
fi
if [[ "$(wc -c < "$ASSET_KEY_FILE")" != 32 ]]; then
  echo "ERROR: $ASSET_KEY_FILE must contain exactly 32 bytes" >&2
  exit 1
fi
python3 "$PATCHER_ROOT/internal/assetkey/generate_embed.py" "$ASSET_KEY_FILE" "$GENERATED_ASSET_KEY_GO"

echo "==> Verify ready canonical Quartet movie restoration assets"
MOVIES=(CNG_PC00_00.webm CNG_PC01_00.webm CNG_PC02_00.webm)
for movie in "${MOVIES[@]}"; do
  path="$MOVIE_ROOT/$movie"
  [[ -f "$path" ]] || { echo "ERROR: missing movie restoration asset: $path" >&2; exit 1; }

  probe="$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,color_range,color_space,color_transfer,color_primaries,nb_read_frames -of json "$path")"
  if ! jq -e '.streams|length==1 and .[0].codec_name=="vp9" and .[0].profile=="Profile 0" and .[0].width==1920 and .[0].height==1080 and .[0].pix_fmt=="yuv420p" and .[0].r_frame_rate=="30000/1001" and .[0].avg_frame_rate=="30000/1001" and .[0].time_base=="1/1000" and .[0].color_range=="tv" and .[0].color_space=="bt709" and .[0].color_transfer=="bt709" and .[0].color_primaries=="bt709" and .[0].nb_read_frames=="916"' <<<"$probe" >/dev/null; then
    echo "ERROR: $movie is not a ready canonical Quartet restoration movie" >&2
    jq -r '.streams[0] | "  codec=\(.codec_name) profile=\(.profile) size=\(.width)x\(.height) pix_fmt=\(.pix_fmt) fps=\(.r_frame_rate)/\(.avg_frame_rate) time_base=\(.time_base) range=\(.color_range) matrix=\(.color_space) transfer=\(.color_transfer // "unspecified") primaries=\(.color_primaries // "unspecified") frames=\(.nb_read_frames)"' <<<"$probe" >&2
    echo "Canonical movie inputs are never rewritten by BUILD_RELEASE.sh." >&2
    echo "Run ./NORMALIZE_MOVIE_RESTORATION_ASSETS.sh once to normalize compatible existing files in place," >&2
    echo "or use ./PREPARE_MOVIE_RESTORATION.sh for a fresh workspace." >&2
    exit 1
  fi

  aprobe="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,channel_layout -of json "$path")"
  jq -e '.streams|length==1 and .[0].codec_name=="opus" and .[0].sample_rate=="48000" and .[0].channels==2 and .[0].channel_layout=="stereo"' <<<"$aprobe" >/dev/null || {
    echo "ERROR: $movie does not contain canonical Quartet Opus 48k stereo audio" >&2
    echo "$aprobe" >&2
    exit 1
  }
done

echo "==> Resolve canonical UNCENSOR build source"
CONFIG_CANONICAL_SOURCE=""
if [[ -f "$LOCAL_PATHS_FILE" ]]; then
  set +u
  # shellcheck disable=SC1090
  source "$LOCAL_PATHS_FILE"
  set -u
  CONFIG_CANONICAL_SOURCE="${BR1_ORIGINAL_ROOT:-}"
fi
CANONICAL_REQUIRED=("BLUE_REFLECTION.exe" "DATA/PACK00_02.PAK" "DATA/PACK00_03.PAK" "DATA/PACK01.PAK")
CANONICAL_SOURCE="$(resolve_rebuild_root \
  "canonical BLUE REFLECTION UNCENSOR build source" "$CANONICAL_SOURCE" "$CANONICAL_SOURCE_STATE" "$CONFIG_CANONICAL_SOURCE" CANONICAL_REQUIRED \
  "$HOME/.steam/debian-installation/steamapps/common/BLUE REFLECTION" \
  "$HOME/.steam/steam/steamapps/common/BLUE REFLECTION" \
  "$HOME/.local/share/Steam/steamapps/common/BLUE REFLECTION")" || exit 1
CANONICAL_PACK="$CANONICAL_SOURCE/DATA/PACK00_02.PAK"
if [[ ! -f "$CANONICAL_PACK" ]]; then CANONICAL_PACK="$CANONICAL_SOURCE/Data/PACK00_02.PAK"; fi
CANONICAL_EXPECTED_SIZE="$(jq -r '.games[] | select(.id=="blue_reflection_2017") | .files[] | select(.path=="DATA/PACK00_02.PAK") | .size' "$ASSET_SOURCE_HASH_CONTRACT")"
CANONICAL_EXPECTED_SHA="$(jq -r '.games[] | select(.id=="blue_reflection_2017") | .files[] | select(.path=="DATA/PACK00_02.PAK") | .sha256 | ascii_downcase' "$ASSET_SOURCE_HASH_CONTRACT")"
[[ "$CANONICAL_EXPECTED_SIZE" =~ ^[0-9]+$ && "$CANONICAL_EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: canonical PACK00_02 contract missing" >&2; exit 1; }
[[ "$(stat -c '%s' -- "$CANONICAL_PACK")" == "$CANONICAL_EXPECTED_SIZE" ]] || { echo "ERROR: canonical BR1 PACK00_02 size drift" >&2; exit 1; }
[[ "$(sha256sum -- "$CANONICAL_PACK" | awk '{print tolower($1)}')" == "$CANONICAL_EXPECTED_SHA" ]] || { echo "ERROR: canonical BR1 PACK00_02 SHA-256 drift" >&2; exit 1; }
mkdir -p "$(dirname "$CANONICAL_SOURCE_STATE")"
printf '%s\n' "$CANONICAL_SOURCE" > "$CANONICAL_SOURCE_STATE"
echo "    canonical donor source verified (build-time only)"

echo "==> Build canonical Translation record payload"
(
  cd "$PATCHER_ROOT"
  go run ./cmd/unburger-release --project-root "$PROJECT_ROOT" --stage-root "$BUNDLE_STAGE" --br1-canonical-source "$CANONICAL_SOURCE"
)

mkdir -p "$BUNDLE_STAGE/meta" "$BUNDLE_STAGE/content/modules" "$BUNDLE_STAGE/docs" "$BUNDLE_STAGE/contracts" "$RELEASE_STAGE/bin/linux-amd64" "$RELEASE_STAGE/bin/windows-amd64" "$BUNDLE_STAGE/content/restoration/movies"

for movie in "${MOVIES[@]}"; do
  install -Dm644 "$MOVIE_ROOT/$movie" "$BUNDLE_STAGE/content/restoration/movies/$movie"
done
{
  echo '{'
  echo '  "type": "unburger_quartet_movie_restoration",'
  echo '  "format_version": 1,'
  echo '  "target_relative_dir": "Data/B1/x64/Movie",'
  echo '  "files": ['
  for i in "${!MOVIES[@]}"; do
    movie="${MOVIES[$i]}"
    hash="$(sha256sum "$MOVIE_ROOT/$movie" | awk '{print $1}')"
    comma=","; [[ "$i" == "$((${#MOVIES[@]}-1))" ]] && comma=""
    printf '    {"name":"%s","sha256":"%s"}%s\n' "$movie" "$hash" "$comma"
  done
  echo '  ]'
  echo '}'
} > "$BUNDLE_STAGE/content/restoration/movies/MANIFEST.json"

echo "==> Build patcher binaries"
(
  cd "$PATCHER_ROOT"
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=$CORE_VERSION" -o "$RELEASE_STAGE/bin/linux-amd64/brpatcher" ./cmd/brpatcher
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=$CORE_VERSION" -o "$RELEASE_STAGE/bin/windows-amd64/brpatcher.exe" ./cmd/brpatcher
)
chmod 0755 "$RELEASE_STAGE/bin/linux-amd64/brpatcher"

cat > "$BUNDLE_STAGE/content/modules/quartet_restoration.json" <<'JSON'
{
  "type": "unburger_builtin_module",
  "format_version": 1,
  "module_id": "quartet_restoration",
  "capability": "quartet_restoration_v2",
  "components": ["quartet_wet_school_restoration_v1", "quartet_bathroom_water_restoration_v1"],
  "status": "runtime_validated",
  "materialization": "wet-school from embedded canonical encrypted runtime payload; bathroom-water from compatible target",
  "contains_canonical_game_payload": true
}
JSON
install -Dm644 "$PROJECT_ROOT/titles/blue_reflection/modules/quartet_legacy_dlc/module.json" "$BUNDLE_STAGE/content/modules/quartet_legacy_dlc.json"
install -Dm644 "$PROJECT_ROOT/workstreams/core/docs/UNBURGER_RELEASE_AND_SOURCE_ASSETS.md" "$BUNDLE_STAGE/docs/UNBURGER_RELEASE_AND_SOURCE_ASSETS.md"
install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_RUNTIME_BUNDLE_V4.json" "$BUNDLE_STAGE/contracts/UNBURGER_RUNTIME_BUNDLE_V4.json"
install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_RUNTIME_BUNDLE_V3.json" "$BUNDLE_STAGE/contracts/UNBURGER_RUNTIME_BUNDLE_V3_LEGACY.json"
install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_RUNTIME_BUNDLE_V2.json" "$BUNDLE_STAGE/contracts/UNBURGER_RUNTIME_BUNDLE_V2_LEGACY.json"
if [[ -f "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_DLC_SOURCE_ASSETS_V3.json" ]]; then
  install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_DLC_SOURCE_ASSETS_V3.json" "$BUNDLE_STAGE/contracts/UNBURGER_DLC_SOURCE_ASSETS_V3.json"
fi
if [[ -f "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_BR1_SOURCE_ASSETS_V3.json" ]]; then
  install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_BR1_SOURCE_ASSETS_V3.json" "$BUNDLE_STAGE/contracts/UNBURGER_BR1_SOURCE_ASSETS_V3.json"
fi
if [[ -f "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_BR1_SOURCE_ASSETS_V2.json" ]]; then
  install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_BR1_SOURCE_ASSETS_V2.json" "$BUNDLE_STAGE/contracts/UNBURGER_BR1_SOURCE_ASSETS_V2_LEGACY.json"
fi
if [[ -f "$ASSET_ANCHORS" ]]; then
  install -Dm644 "$ASSET_ANCHORS" "$BUNDLE_STAGE/contracts/BR1_LEGACY_SOURCE_MEMBER_ANCHORS_V1.json"
fi
if [[ -f "$ASSET_SOURCE_HASH_CONTRACT" ]]; then
  install -Dm644 "$ASSET_SOURCE_HASH_CONTRACT" "$BUNDLE_STAGE/contracts/DLC_SOURCE_ARCHIVE_HASHES_V1.json"
fi

if [[ "${UNBURGER_ALLOW_PRE_RELEASE_TRANSLATION:-0}" != 1 ]]; then
  for target in blue_reflection_original blue_reflection_quartet blue_reflection_ray_quartet blue_reflection_sun_quartet second_light_original second_light_quartet; do
    jq -e --arg target "$target" '.translation_targets | index($target) != null' "$BUNDLE_STAGE/RELEASE_MANIFEST.json" >/dev/null || {
      echo "ERROR: release-closed Translation bundle is missing target $target" >&2
      exit 1
    }
  done
fi

cat > "$BUNDLE_STAGE/meta/MODULE_VERSIONS.tsv" <<TXT
core	$CORE_VERSION
translation	$TRANSLATION_VERSION
quartet_restoration	$RESTORATION_VERSION
quartet_legacy_dlc	$DLC_VERSION
TXT

cat > "$BUNDLE_STAGE/meta/CONTENT_POLICY.json" <<'JSON'
{
  "type": "unburger_content_policy",
  "format_version": 4,
  "quartet_composition_order": [
    "blue_reflection_dlc_if_selected",
    "second_light_dlc_if_selected",
    "quartet_restoration",
    "quartet_movie_restoration",
    "blue_reflection_translation"
  ],
  "translation_last": true,
  "translation_payload": "canonical_record_bundle",
  "whole_archive_version_lock": false,
  "compatible_installation_materialization": true,
  "large_source_game_archives_included": false,
  "legacy_content_materialized_locally": true,
  "restoration_materialized_locally": true,
  "canonical_wet_school_payload_embedded": true,
  "quartet_movie_restoration_embedded": true,
  "runtime_bundle_container": "opaque-encrypted-v4",
  "developer_source_assets_capability": "br1_legacy_source_assets_v2",
  "developer_source_assets_supplemental_capabilities": [
    "second_light_dlc_source_subset_v1"
  ],
  "developer_source_assets_container": "opaque-encrypted-v3",
  "developer_source_assets_clean_anchor_capability": "br1_legacy_clean_source_anchors_v1"
}
JSON

# Public release content may contain authored translations/configuration and binaries,
# but never materialized game archives or extracted game containers.
while IFS= read -r game_asset; do
  rel="${game_asset#"$BUNDLE_STAGE/"}"
  if [[ "$rel" != "content/restoration/wet-school/source/DATA/PACK00_02.PAK" ]]; then
    echo "ERROR: release staging contains an unauthorized materialized game archive/asset: $rel" >&2
    exit 1
  fi
done < <(find "$BUNDLE_STAGE" -type f \( -iname '*.PAK' -o -iname '*.PAK_' -o -iname '*.elixir' -o -iname '*.elixir.gz' -o -iname '*.g1m' -o -iname '*.g1t' \) -print)
[[ -f "$BUNDLE_STAGE/content/restoration/wet-school/source/DATA/PACK00_02.PAK" ]] || { echo "ERROR: canonical wet-school payload is missing from runtime staging" >&2; exit 1; }
if (cd "$BUNDLE_STAGE" && find . -type f | grep -Eq '/\.local/|BR_TRANSLATION_(LOOSE_BUILD|PAK_REPACK|STANDALONE_MEMBER)_REPORT'); then
  echo "ERROR: release staging contains developer Translation build artifacts" >&2
  exit 1
fi

find "$BUNDLE_STAGE" -type f -printf '%P\n' | LC_ALL=C sort > "$BUNDLE_STAGE/meta/FILE_LIST.txt"
(
  cd "$BUNDLE_STAGE"
  find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

ARCHIVE_BASENAME="UNBURGER_${CORE_VERSION}"
UNBURGER="$OUTPUT_DIR/${ARCHIVE_BASENAME}.unburger"
UNBURGER_SIDECAR="$UNBURGER.sha256"
rm -f "$UNBURGER" "$UNBURGER_SIDECAR"

PLAIN_RUNTIME="$WORK_DIR/${ARCHIVE_BASENAME}.tar.zst"
echo "==> Package ${ARCHIVE_BASENAME}.unburger (format v4: AES-256-GCM chunked over tar + Zstandard)"
(
  cd "$BUNDLE_STAGE"
  find . -exec touch -h -t 202601010000.00 {} +
  find . -type f -printf '%P\0' | LC_ALL=C sort -z | \
    tar --null --no-recursion --format=ustar --owner=0 --group=0 --numeric-owner --mtime='2026-01-01 00:00:00 UTC' -T - -cf - | \
    zstd -q -19 -T0 -o "$PLAIN_RUNTIME"
)
zstd -q -t "$PLAIN_RUNTIME"
(
  cd "$PATCHER_ROOT"
  go run ./cmd/unburger-runtime --encrypt "$PLAIN_RUNTIME" --output "$UNBURGER"
  go run ./cmd/unburger-runtime --verify "$UNBURGER" >/dev/null
)
rm -f "$PLAIN_RUNTIME"
sha256sum "$UNBURGER" | sed "s#  .*#  ${ARCHIVE_BASENAME}.unburger#" > "$UNBURGER_SIDECAR"

# The public ZIP contains only user-facing launchers/binaries and the canonical runtime payload.
# The patcher materializes the verified .unburger payload itself on first run.
cp -a "$UNBURGER" "$RELEASE_STAGE/${ARCHIVE_BASENAME}.unburger"
cp -a "$UNBURGER_SIDECAR" "$RELEASE_STAGE/${ARCHIVE_BASENAME}.unburger.sha256"

cat > "$RELEASE_STAGE/RUN.sh" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/bin/linux-amd64/brpatcher" start --project-root "$ROOT" "$@"
SH
chmod 0755 "$RELEASE_STAGE/RUN.sh"
cat > "$RELEASE_STAGE/RUN.cmd" <<'CMD'
@echo off
setlocal
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "ERRLOG=%ROOT%\UNBURGER_LAST_ERROR.log"
del /q "%ERRLOG%" >nul 2>nul
"%ROOT%\bin\windows-amd64\brpatcher.exe" start --project-root "%ROOT%" %* 2>"%ERRLOG%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo UNBURGER patcher failed with exit code %RC%.
  if exist "%ERRLOG%" type "%ERRLOG%"
  echo.
  echo Error log: "%ERRLOG%"
  echo The game files are not considered successfully installed unless the patcher reports success.
  pause
) else (
  if exist "%ERRLOG%" del /q "%ERRLOG%" >nul 2>nul
)
exit /b %RC%
CMD

cat > "$RELEASE_STAGE/SAVE_ACCESS.sh" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/bin/linux-amd64/brpatcher" save-access "$@"
SH
chmod 0755 "$RELEASE_STAGE/SAVE_ACCESS.sh"
cat > "$RELEASE_STAGE/SAVE_ACCESS.cmd" <<'CMD'
@echo off
setlocal
for %%I in ("%~dp0.") do set "ROOT=%%~fI"
set "ERRLOG=%ROOT%\UNBURGER_SAVE_ACCESS_LAST_ERROR.log"
del /q "%ERRLOG%" >nul 2>nul
"%ROOT%\bin\windows-amd64\brpatcher.exe" save-access %* 2>"%ERRLOG%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo Save Access failed with exit code %RC%.
  if exist "%ERRLOG%" type "%ERRLOG%"
  echo.
  echo Error log: "%ERRLOG%"
  pause
) else (
  if exist "%ERRLOG%" del /q "%ERRLOG%" >nul 2>nul
)
exit /b %RC%
CMD

cat > "$RELEASE_STAGE/README.md" <<'MD'
# Blue Reflection Unburger Mod

Run `RUN.sh` on Linux or `RUN.cmd` on Windows. The patcher first checks the current/release directory, then a previously managed installation, then the default Steam libraries (including extra libraries listed in `steamapps/libraryfolders.vdf`). If more than one supported game is found, the guided UI asks which installation to use. Identification remains based on structural game files, not on a Steam AppID.

For BLUE REFLECTION Quartet, Translation, UNCENSOR and DLC are normal module choices and are enabled by default. Translation and UNCENSOR are self-contained: the always-shipped encrypted `.unburger` runtime payload carries the canonical wet-school restoration set for PC00-PC14 plus the three verified CNG_PC00_00/CNG_PC01_00/CNG_PC02_00 restored movies. Users never need BLUE REFLECTION (2017), Second Light, or `.unburger-assets` for Translation/UNCENSOR. Inside DLC, BLUE REFLECTION and BLUE REFLECTION: Second Light source families are both enabled by default and the cursor starts on Continue. The optional `.unburger-assets` bundle exists only to provide reduced source data for those DLC families; if it is absent, the DLC source flow can use the corresponding standalone source installations. Quartet's startup menu can also create a reusable encrypted `UNBURGER_DLC_ASSETS_v3.unburger-assets` locally from installed BLUE REFLECTION and Second Light copies. That builder is read-only to all games, fully verifies the new bundle before replacing an existing one, and writes the bundle beside the patcher by default. After a successful build, future DLC installs can use the bundle without keeping the source games installed.

BLUE REFLECTION legacy DLC can also use the optional Save Access step for existing Quartet saves. Native Second Light DLC restoration does not require an automatic save patch; its unresolved entitlement gates are restored through game-data story routing. On native Windows Save Access detects the normal Local AppData folder, while Linux supports Steam/Proton and loose Wine/Heroic prefixes. Every changed save is backed up before writing.

Run `SAVE_ACCESS.sh` on Linux or `SAVE_ACCESS.cmd` on Windows whenever you create a new playthrough/save and want the restored costume and Tropical Island access flags applied to it.

The patcher prepares verified game-file changes transactionally and keeps rollback data for managed installations. Canonical restoration assets are carried only inside the encrypted `.unburger` runtime container; the public ZIP never exposes loose game PAKs, models or texture containers.
MD

if find "$RELEASE_STAGE" -type f \( -iname '*.PAK' -o -iname '*.PAK_' -o -iname '*.elixir' -o -iname '*.elixir.gz' -o -iname '*.g1m' -o -iname '*.g1t' -o -iname '*.unburger-assets' \) -print -quit | grep -q .; then
  echo "ERROR: public release ZIP staging contains source-game/developer asset payload" >&2
  exit 1
fi
(
  cd "$RELEASE_STAGE"
  find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
  find . -exec touch -h -t 202601010000.00 {} +
)

RELEASE_BASENAME="Blue-Reflection-Unburger-Mod_${CORE_VERSION}"
RELEASE_ZIP="$OUTPUT_DIR/${RELEASE_BASENAME}.zip"
RELEASE_SIDECAR="$RELEASE_ZIP.sha256"
rm -f "$RELEASE_ZIP" "$RELEASE_SIDECAR"
echo "==> Package ${RELEASE_BASENAME}.zip"
(
  cd "$RELEASE_STAGE"
  find . -type f -printf '%P\n' | LC_ALL=C sort | zip -9 -X -q "$RELEASE_ZIP" -@
)
unzip -tqq "$RELEASE_ZIP"
sha256sum "$RELEASE_ZIP" | sed "s#  .*#  ${RELEASE_BASENAME}.zip#" > "$RELEASE_SIDECAR"

if ((ASSETS)); then
  ASSET_BUNDLE_OUT="$OUTPUT_DIR/${ASSET_BASENAME}.unburger-assets"
  ASSET_SIDECAR_OUT="$ASSET_BUNDLE_OUT.sha256"
  ASSET_EXPECTED_BR1_COUNT=1682
  ASSET_EXPECTED_SL_COUNT="$(jq -r '.source_assets.second_light_frozen_logical_members // 0' "$PROJECT_ROOT/config/canonical_state.json")"
  ASSET_ANCHOR_FINGERPRINT="$(jq -r '.source_fingerprint // ""' "$ASSET_ANCHORS")"
  if [[ "$ASSET_EXPECTED_SL_COUNT" != 2942 || ! "$ASSET_ANCHOR_FINGERPRINT" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "ERROR: canonical source-assets contract is incomplete or inconsistent" >&2
    exit 1
  fi

  verify_assets_bundle() {
    local bundle="$1" label="$2" allow_sidecar_repair="${3:-0}"
    local manifest_out="$WORK_DIR/asset-manifest-$(printf '%s' "$label" | tr -cs '[:alnum:]_.-' '_').json"
    local sidecar="${bundle}.sha256" expected="" actual="" bootstrap_sidecar=0 need_full_verify=0
    [[ -f "$bundle" ]] || return 1

    actual="$(sha256sum "$bundle" | awk '{print tolower($1)}')"
    [[ "$actual" =~ ^[0-9a-f]{64}$ ]] || {
      echo "    reject $label: could not compute a valid SHA-256 for $bundle" >&2
      return 1
    }

    if [[ -f "$sidecar" ]]; then
      expected="$(awk 'NF {print $1; exit}' "$sidecar")"
      if [[ ! "$expected" =~ ^[0-9a-fA-F]{64}$ ]]; then
        if [[ "$allow_sidecar_repair" == 1 ]]; then
          echo "    invalid SHA-256 sidecar; perform one-time full bundle verification before repair" >&2
          need_full_verify=1
          bootstrap_sidecar=1
        else
          echo "    reject $label: invalid SHA-256 sidecar" >&2
          return 1
        fi
      elif [[ "${actual,,}" != "${expected,,}" ]]; then
        if [[ "$allow_sidecar_repair" == 1 ]]; then
          echo "    SHA-256 sidecar does not match bundle; perform one-time full bundle verification before repair" >&2
          need_full_verify=1
          bootstrap_sidecar=1
        else
          echo "    reject $label: SHA-256 does not match sidecar" >&2
          return 1
        fi
      fi
    else
      echo "    no SHA-256 sidecar; perform one-time full bundle verification before migration" >&2
      need_full_verify=1
      bootstrap_sidecar=1
    fi

    if (( need_full_verify )); then
      if ! (
        cd "$PATCHER_ROOT"
        go run ./cmd/unburger-assets --verify --anchors "$ASSET_ANCHORS" --output "$bundle"
      ) >"$manifest_out"; then
        echo "    reject $label: bundle failed full object/member verification" >&2
        return 1
      fi
    else
      if ! (
        cd "$PATCHER_ROOT"
        go run ./cmd/unburger-assets --inspect --output "$bundle"
      ) >"$manifest_out"; then
        echo "    reject $label: encrypted manifest cannot be inspected with the current asset key" >&2
        return 1
      fi
    fi

    if ! jq -e \
      --arg anchor "${ASSET_ANCHOR_FINGERPRINT,,}" \
      --argjson br1 "$ASSET_EXPECTED_BR1_COUNT" \
      --argjson sl "$ASSET_EXPECTED_SL_COUNT" '''
        .type == "unburger_br1_dlc_source_assets" and
        .format_version == 2 and
        .capability == "br1_legacy_source_assets_v2" and
        .reconstruction_capability == "br1_legacy_content_rebuild_v1" and
        .clean_anchor_capability == "br1_legacy_clean_source_anchors_v1" and
        ((.clean_anchor_fingerprint | ascii_downcase) == $anchor) and
        ((.source_fingerprint | ascii_downcase) == $anchor) and
        ((.source_members | length) == $br1) and
        ((.image_files | length) > 0) and
        (((.supplemental_sources // []) | length) == 1) and
        (any(.supplemental_sources[];
          .capability == "second_light_dlc_source_subset_v1" and
          .root == "SECOND_LIGHT" and
          ((.source_members | length) == $sl) and
          ((.source_fingerprint | test("^[0-9a-fA-F]{64}$")))))
      ''' "$manifest_out" >/dev/null; then
      echo "    reject $label: manifest does not match current 1682+2942 DLC source contract" >&2
      return 1
    fi

    if (( bootstrap_sidecar )); then
      local sidecar_tmp="${sidecar}.tmp.$$"
      if printf '%s  %s\n' "$actual" "$(basename "$bundle")" >"$sidecar_tmp" 2>/dev/null && mv -f -- "$sidecar_tmp" "$sidecar" 2>/dev/null; then
        echo "    migrated verified bundle: wrote SHA-256 sidecar $sidecar" >&2
      else
        rm -f -- "$sidecar_tmp" 2>/dev/null || true
        echo "    verified bundle; source location is not writable, output sidecar will still be emitted" >&2
      fi
    fi

    # stdout is an API: callers capture it as the bundle digest. Keep diagnostics on stderr.
    printf '%s\n' "$actual"
  }

  reuse_candidate=""
  reuse_sha=""
  if (( ! ASSETS_REBUILD )); then
    declare -a ASSET_CANDIDATES=()
    if [[ -n "$ASSETS_BUNDLE" ]]; then
      ASSET_CANDIDATES+=("$ASSETS_BUNDLE")
    else
      ASSET_CANDIDATES+=("$ASSET_BUNDLE_OUT")
      if [[ -f "$ASSET_BUNDLE_STATE" ]]; then
        remembered_bundle="$(head -n1 "$ASSET_BUNDLE_STATE" | tr -d '\r\n')"
        [[ -z "$remembered_bundle" ]] || ASSET_CANDIDATES+=("$remembered_bundle")
      fi
      ASSET_CANDIDATES+=("$PROJECT_ROOT/.local/release/${ASSET_BASENAME}.unburger-assets")
    fi

    declare -A seen_asset_candidates=()
    for candidate in "${ASSET_CANDIDATES[@]}"; do
      [[ -n "$candidate" ]] || continue
      candidate="$(python3 - "$candidate" <<'PY_REALPATH'
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY_REALPATH
)"
      [[ -z "${seen_asset_candidates[$candidate]:-}" ]] || continue
      seen_asset_candidates[$candidate]=1
      [[ -f "$candidate" ]] || continue
      echo "==> Verify existing combined DLC source-assets bundle"
      echo "    candidate: $candidate"
      repair_existing=1
      [[ -z "$ASSETS_BUNDLE" ]] || repair_existing=0
      if reuse_sha="$(verify_assets_bundle "$candidate" existing "$repair_existing")"; then
        [[ "$reuse_sha" =~ ^[0-9a-f]{64}$ ]] || {
          echo "ERROR: verified assets bundle returned an invalid digest" >&2
          exit 1
        }
        reuse_candidate="$candidate"
        break
      fi
      if [[ -n "$ASSETS_BUNDLE" ]]; then
        echo "ERROR: explicitly supplied --assets-bundle is not reusable" >&2
        exit 1
      fi
    done
  fi

  if [[ -n "$reuse_candidate" ]]; then
    echo "==> Reuse verified combined DLC source-assets bundle"
    mkdir -p "$OUTPUT_DIR" "$(dirname "$ASSET_BUNDLE_STATE")"
    if [[ ! "$reuse_candidate" -ef "$ASSET_BUNDLE_OUT" ]]; then
      tmp_copy="$OUTPUT_DIR/.${ASSET_BASENAME}.reuse.$$.tmp"
      rm -f "$tmp_copy"
      if cp --reflink=auto -- "$reuse_candidate" "$tmp_copy" 2>/dev/null; then
        :
      else
        cp -- "$reuse_candidate" "$tmp_copy"
      fi
      copied_sha="$(sha256sum "$tmp_copy" | awk '{print $1}')"
      [[ "${copied_sha,,}" == "${reuse_sha,,}" ]] || { echo "ERROR: copied assets bundle hash changed" >&2; rm -f "$tmp_copy"; exit 1; }
      mv -f -- "$tmp_copy" "$ASSET_BUNDLE_OUT"
    fi
    [[ "$reuse_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: refusing to emit invalid assets SHA-256 sidecar" >&2; exit 1; }
    printf '%s  %s\n' "$reuse_sha" "${ASSET_BASENAME}.unburger-assets" > "$ASSET_SIDECAR_OUT"
    printf '%s\n' "$reuse_candidate" > "$ASSET_BUNDLE_STATE"
    echo "    source rebuild skipped"
  else
    echo "==> No reusable combined DLC source-assets bundle found; rebuild is required"
    if ((ASSETS_REBUILD)); then
      echo "    rebuild explicitly requested by --assets-rebuild"
    fi

    CONFIG_BR1_SOURCE=""
    CONFIG_SECOND_LIGHT_SOURCE=""
    CONFIG_QUARTET_TARGET=""
    if [[ -f "$LOCAL_PATHS_FILE" ]]; then
      # Machine-local shell configuration is intentionally excluded from Git.
      # It is a hint only; every path is structurally validated below.
      set +u
      # shellcheck disable=SC1090
      source "$LOCAL_PATHS_FILE"
      set -u
      CONFIG_BR1_SOURCE="${BR1_ORIGINAL_ROOT:-}"
      CONFIG_SECOND_LIGHT_SOURCE="${BR_SECOND_LIGHT_ROOT:-}"
      CONFIG_QUARTET_TARGET="${BR1_QUARTET_ROOT:-}"
    fi

    BR1_REQUIRED=(
      "BLUE_REFLECTION.exe"
      "DATA/PACK00_02.PAK" "DATA/PACK00_03.PAK" "DATA/PACK01.PAK"
      "DATA/PACK02_1.PAK" "DATA/PACK02_2.PAK" "DATA/PACK02_3.PAK"
    )
    SECOND_LIGHT_REQUIRED=(
      "Data/PACK00_02.PAK" "Data/PACK00_03.PAK" "Data/PACK01.PAK" "Data/PACK02.PAK"
      "Data/x64/Sound/Le0000_BGM.ktsl2asbin" "Data/x64/Sound/Le0000_BGM.ktsl2stbin"
    )
    QUARTET_REQUIRED=("Data/PACK00_02.PAK" "Data/PACK02_03.PAK")

    ASSETS_SOURCE="$(resolve_rebuild_root \
      "BLUE REFLECTION source" "$ASSETS_SOURCE" "$ASSET_SOURCE_STATE" "$CONFIG_BR1_SOURCE" BR1_REQUIRED \
      "$HOME/.steam/debian-installation/steamapps/common/BLUE REFLECTION" \
      "$HOME/.steam/steam/steamapps/common/BLUE REFLECTION" \
      "$HOME/.local/share/Steam/steamapps/common/BLUE REFLECTION")" || exit 1
    SECOND_LIGHT_ASSETS_SOURCE="$(resolve_rebuild_root \
      "Second Light source" "$SECOND_LIGHT_ASSETS_SOURCE" "$SECOND_LIGHT_ASSET_SOURCE_STATE" "$CONFIG_SECOND_LIGHT_SOURCE" SECOND_LIGHT_REQUIRED \
      "$HOME/.steam/debian-installation/steamapps/common/BLUE REFLECTION Second Light" \
      "$HOME/.steam/steam/steamapps/common/BLUE REFLECTION Second Light" \
      "$HOME/.local/share/Steam/steamapps/common/BLUE REFLECTION Second Light")" || exit 1
    QUARTET_ASSETS_TARGET="$(resolve_rebuild_root \
      "Quartet minimization target" "$QUARTET_ASSETS_TARGET" "$QUARTET_ASSET_TARGET_STATE" "$CONFIG_QUARTET_TARGET" QUARTET_REQUIRED \
      "$HOME/.steam/debian-installation/steamapps/common/BLUE REFLECTION Quartet" \
      "$HOME/.steam/steam/steamapps/common/BLUE REFLECTION Quartet" \
      "$HOME/.local/share/Steam/steamapps/common/BLUE REFLECTION Quartet")" || exit 1

    echo "==> Resolved source roots for rebuild"
    echo "    BLUE REFLECTION: $ASSETS_SOURCE"
    echo "    Second Light:    $SECOND_LIGHT_ASSETS_SOURCE"
    echo "    Quartet target:  $QUARTET_ASSETS_TARGET"

    validate_source_hash_contract || exit 1
    verify_source_archive_hashes "blue_reflection_2017" "$ASSETS_SOURCE" || exit 1
    verify_source_archive_hashes "blue_reflection_second_light" "$SECOND_LIGHT_ASSETS_SOURCE" || exit 1
    echo "    Quartet target is structure/capability-gated only; no whole-file hash lock is applied."

    echo "==> Build optional combined BLUE REFLECTION + Second Light DLC source-assets bundle"
    ASSET_BUILD_TMP="$WORK_DIR/${ASSET_BASENAME}.unburger-assets"
    ASSET_BUILD_TMP_SIDECAR="$ASSET_BUILD_TMP.sha256"
    ASSET_ARGS=(--output "$ASSET_BUILD_TMP" --anchors "$ASSET_ANCHORS" --second-light-source-root "$SECOND_LIGHT_ASSETS_SOURCE" --quartet-root "$QUARTET_ASSETS_TARGET")
    if [[ -n "$ASSETS_SOURCE" ]]; then
      ASSET_ARGS+=(--source-root "$ASSETS_SOURCE")
    fi
    ASSET_BUILD_LOG="$WORK_DIR/asset-build.log"
    (
      cd "$PATCHER_ROOT"
      go run ./cmd/unburger-assets "${ASSET_ARGS[@]}"
    ) | tee "$ASSET_BUILD_LOG"
    tmp_sha="$(sha256sum "$ASSET_BUILD_TMP" | awk '{print $1}')"
    printf '%s  %s\n' "$tmp_sha" "$(basename "$ASSET_BUILD_TMP")" > "$ASSET_BUILD_TMP_SIDECAR"
    verify_assets_bundle "$ASSET_BUILD_TMP" rebuilt 0 >/dev/null || {
      echo "ERROR: newly rebuilt combined source-assets bundle failed final verification" >&2
      exit 1
    }

    RESOLVED_SOURCE="$(awk -F= '$1 == "SOURCE_ROOT" {sub(/^SOURCE_ROOT=/, ""); print; exit}' "$ASSET_BUILD_LOG")"
    if [[ -n "$RESOLVED_SOURCE" ]]; then
      mkdir -p "$(dirname "$ASSET_SOURCE_STATE")"
      printf '%s\n' "$RESOLVED_SOURCE" > "$ASSET_SOURCE_STATE"
    fi
    RESOLVED_SECOND_LIGHT="$(awk -F= '$1 == "SECOND_LIGHT_SOURCE_ROOT" {sub(/^SECOND_LIGHT_SOURCE_ROOT=/, ""); print; exit}' "$ASSET_BUILD_LOG")"
    RESOLVED_QUARTET="$(awk -F= '$1 == "QUARTET_ROOT" {sub(/^QUARTET_ROOT=/, ""); print; exit}' "$ASSET_BUILD_LOG")"
    [[ -z "$RESOLVED_SECOND_LIGHT" ]] || printf '%s\n' "$RESOLVED_SECOND_LIGHT" > "$SECOND_LIGHT_ASSET_SOURCE_STATE"
    [[ -z "$RESOLVED_QUARTET" ]] || printf '%s\n' "$RESOLVED_QUARTET" > "$QUARTET_ASSET_TARGET_STATE"

    mkdir -p "$OUTPUT_DIR" "$(dirname "$ASSET_BUNDLE_STATE")"
    mv -f -- "$ASSET_BUILD_TMP" "$ASSET_BUNDLE_OUT"
    printf '%s  %s\n' "$tmp_sha" "${ASSET_BASENAME}.unburger-assets" > "$ASSET_SIDECAR_OUT"
    printf '%s\n' "$ASSET_BUNDLE_OUT" > "$ASSET_BUNDLE_STATE"
  fi

  final_asset_sha="$(verify_assets_bundle "$ASSET_BUNDLE_OUT" final 0)" || {
    echo "ERROR: final emitted combined source-assets bundle failed verification" >&2
    exit 1
  }
  [[ "$final_asset_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: final assets verifier returned an invalid digest" >&2; exit 1; }
  printf '%s  %s\n' "$final_asset_sha" "${ASSET_BASENAME}.unburger-assets" > "$ASSET_SIDECAR_OUT"
  printf '\nCombined DLC source bundle complete\n  %s\n  %s\n' "$ASSET_BUNDLE_OUT" "$ASSET_SIDECAR_OUT"
fi
printf '\nRelease complete\n  %s\n  %s\n  %s\n  %s\n' "$RELEASE_ZIP" "$RELEASE_SIDECAR" "$UNBURGER" "$UNBURGER_SIDECAR"
