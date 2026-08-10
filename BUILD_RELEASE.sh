#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
OUTPUT_DIR="$PROJECT_ROOT/.local/release"
KEEP_STAGE=0
REFRESH=0
ASSETS=0
ASSETS_SOURCE=""
SECOND_LIGHT_ASSETS_SOURCE=""
QUARTET_ASSETS_TARGET=""
ASSET_ANCHORS="$PROJECT_ROOT/workstreams/core/contracts/release/BR1_LEGACY_SOURCE_MEMBER_ANCHORS_V1.json"
ASSET_SOURCE_STATE="$PROJECT_ROOT/.local/release/BR1_ASSETS_SOURCE_PATH"
SECOND_LIGHT_ASSET_SOURCE_STATE="$PROJECT_ROOT/.local/release/SECOND_LIGHT_ASSETS_SOURCE_PATH"
QUARTET_ASSET_TARGET_STATE="$PROJECT_ROOT/.local/release/QUARTET_ASSETS_TARGET_PATH"
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
  --assets, -assets         Also build the combined DLC source-assets bundle.
  --assets-source PATH      BLUE REFLECTION (2017) source game folder.
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
    --assets-source) ASSETS_SOURCE="${2:-}"; shift 2 ;;
    --assets-second-light-source) SECOND_LIGHT_ASSETS_SOURCE="${2:-}"; shift 2 ;;
    --assets-quartet-target) QUARTET_ASSETS_TARGET="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$ASSETS_SOURCE$SECOND_LIGHT_ASSETS_SOURCE$QUARTET_ASSETS_TARGET" && "$ASSETS" != 1 ]]; then
  echo "ERROR: assets source/target options require --assets" >&2
  exit 2
fi

if ((ASSETS)) && [[ -z "$ASSETS_SOURCE" && -f "$ASSET_SOURCE_STATE" ]]; then
  ASSETS_SOURCE="$(head -n1 "$ASSET_SOURCE_STATE" | tr -d '\r\n')"
  if [[ -n "$ASSETS_SOURCE" ]]; then
    echo "==> Reuse previous BLUE REFLECTION source hint"
  fi
fi
if ((ASSETS)) && [[ -z "$SECOND_LIGHT_ASSETS_SOURCE" && -f "$SECOND_LIGHT_ASSET_SOURCE_STATE" ]]; then
  SECOND_LIGHT_ASSETS_SOURCE="$(head -n1 "$SECOND_LIGHT_ASSET_SOURCE_STATE" | tr -d '\r\n')"
  [[ -z "$SECOND_LIGHT_ASSETS_SOURCE" ]] || echo "==> Reuse previous Second Light source hint"
fi
if ((ASSETS)) && [[ -z "$QUARTET_ASSETS_TARGET" && -f "$QUARTET_ASSET_TARGET_STATE" ]]; then
  QUARTET_ASSETS_TARGET="$(head -n1 "$QUARTET_ASSET_TARGET_STATE" | tr -d '\r\n')"
  [[ -z "$QUARTET_ASSETS_TARGET" ]] || echo "==> Reuse previous Quartet minimization target"
fi

for cmd in go sha256sum jq zip unzip tar zstd python3 ffmpeg ffprobe; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 1; }
done

version_ge() {
  local lhs="$1" rhs="$2"
  [[ "$(printf '%s\n%s\n' "$rhs" "$lhs" | sort -V | tail -n1)" == "$lhs" ]]
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
    echo "Repair/update the project before building source assets." >&2
    exit 1
  fi
  jq -e '.type == "unburger_br1_dlc_clean_source_anchors" and .format_version == 1 and .capability == "br1_legacy_clean_source_anchors_v1" and (.source_members | length) == 1682' "$ASSET_ANCHORS" >/dev/null || {
    echo "ERROR: verified BLUE REFLECTION source-member checks are invalid" >&2
    exit 1
  }
  if [[ -z "$SECOND_LIGHT_ASSETS_SOURCE" || -z "$QUARTET_ASSETS_TARGET" ]]; then
    echo "ERROR: combined --assets build needs Second Light source and Quartet minimization target." >&2
    echo "Pass --assets-second-light-source PATH --assets-quartet-target PATH once; successful paths are remembered." >&2
    exit 1
  fi
  echo "==> Verify clean BLUE REFLECTION and Second Light source data"
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

echo "==> Verify canonical Quartet movie restoration assets"
MOVIES=(CNG_PC00_00.webm CNG_PC01_00.webm CNG_PC02_00.webm)
MOVIE_CANON_ROOT="$WORK_DIR/movie-restoration-canonical"
mkdir -p "$MOVIE_CANON_ROOT"
for movie in "${MOVIES[@]}"; do
  path="$MOVIE_ROOT/$movie"
  canon="$MOVIE_CANON_ROOT/$movie"
  [[ -f "$path" ]] || { echo "ERROR: missing movie restoration asset: $path" >&2; exit 1; }

  probe="$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,color_range,color_space,color_transfer,color_primaries,nb_read_frames -of json "$path")"
  if ! jq -e '.streams|length==1 and .[0].codec_name=="vp9" and .[0].profile=="Profile 0" and .[0].width==1920 and .[0].height==1080 and .[0].pix_fmt=="yuv420p" and .[0].r_frame_rate=="30000/1001" and .[0].avg_frame_rate=="30000/1001" and .[0].time_base=="1/1000" and .[0].color_range=="tv" and .[0].color_space=="bt709" and ((.[0].color_transfer // "bt709")=="bt709") and ((.[0].color_primaries // "bt709")=="bt709") and .[0].nb_read_frames=="916"' <<<"$probe" >/dev/null; then
    echo "ERROR: $movie does not match the canonical Quartet restoration video profile" >&2
    jq -r '.streams[0] | "  codec=\(.codec_name) profile=\(.profile) size=\(.width)x\(.height) pix_fmt=\(.pix_fmt) fps=\(.r_frame_rate)/\(.avg_frame_rate) time_base=\(.time_base) range=\(.color_range) matrix=\(.color_space) transfer=\(.color_transfer // "unspecified") primaries=\(.color_primaries // "unspecified") frames=\(.nb_read_frames)"' <<<"$probe" >&2
    exit 1
  fi

  aprobe="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,channel_layout -of json "$path")"
  jq -e '.streams|length==1 and .[0].codec_name=="opus" and .[0].sample_rate=="48000" and .[0].channels==2 and .[0].channel_layout=="stereo"' <<<"$aprobe" >/dev/null || {
    echo "ERROR: $movie does not contain canonical Quartet Opus 48k stereo audio" >&2
    echo "$aprobe" >&2
    exit 1
  }

  # FFmpeg/libvpx can produce an otherwise canonical VP9 stream while omitting
  # Matroska transfer/primaries tags even when -color_trc/-color_primaries were
  # supplied at encode time. Normalize only those container metadata fields by
  # stream-copying the already encoded VP9/Opus streams; never re-encode here.
  if jq -e '.streams[0].color_transfer=="bt709" and .streams[0].color_primaries=="bt709"' <<<"$probe" >/dev/null; then
    install -Dm644 "$path" "$canon"
  else
    echo "    $movie: normalize BT.709 transfer/primaries metadata (stream copy; no re-encode)"
    ffmpeg -hide_banner -loglevel warning -y \
      -i "$path" -map 0:v:0 -map 0:a:0 -c:v copy -c:a copy \
      -color_range tv -colorspace bt709 -color_trc bt709 -color_primaries bt709 \
      -map_metadata -1 "$canon"
  fi

  cprobe="$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,color_range,color_space,color_transfer,color_primaries,nb_read_frames -of json "$canon")"
  jq -e '.streams|length==1 and .[0].codec_name=="vp9" and .[0].profile=="Profile 0" and .[0].width==1920 and .[0].height==1080 and .[0].pix_fmt=="yuv420p" and .[0].r_frame_rate=="30000/1001" and .[0].avg_frame_rate=="30000/1001" and .[0].time_base=="1/1000" and .[0].color_range=="tv" and .[0].color_space=="bt709" and .[0].color_transfer=="bt709" and .[0].color_primaries=="bt709" and .[0].nb_read_frames=="916"' <<<"$cprobe" >/dev/null || {
    echo "ERROR: $movie failed canonical metadata normalization" >&2
    echo "$cprobe" >&2
    exit 1
  }
done

echo "==> Build canonical Translation record payload"
(
  cd "$PATCHER_ROOT"
  go run ./cmd/unburger-release --project-root "$PROJECT_ROOT" --stage-root "$BUNDLE_STAGE"
)

mkdir -p "$BUNDLE_STAGE/meta" "$BUNDLE_STAGE/content/modules" "$BUNDLE_STAGE/docs" "$BUNDLE_STAGE/contracts" "$RELEASE_STAGE/bin/linux-amd64" "$RELEASE_STAGE/bin/windows-amd64" "$BUNDLE_STAGE/content/restoration/movies"

for movie in "${MOVIES[@]}"; do
  install -Dm644 "$MOVIE_CANON_ROOT/$movie" "$BUNDLE_STAGE/content/restoration/movies/$movie"
done
{
  echo '{'
  echo '  "type": "unburger_quartet_movie_restoration",'
  echo '  "format_version": 1,'
  echo '  "target_relative_dir": "Data/B1/x64/Movie",'
  echo '  "files": ['
  for i in "${!MOVIES[@]}"; do
    movie="${MOVIES[$i]}"
    hash="$(sha256sum "$MOVIE_CANON_ROOT/$movie" | awk '{print $1}')"
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
  "capability": "quartet_bathroom_water_restoration_v1",
  "status": "runtime_validated",
  "materialization": "from_current_compatible_installation",
  "contains_game_payload": false
}
JSON
install -Dm644 "$PROJECT_ROOT/titles/blue_reflection/modules/quartet_legacy_dlc/module.json" "$BUNDLE_STAGE/content/modules/quartet_legacy_dlc.json"
install -Dm644 "$PROJECT_ROOT/workstreams/core/docs/UNBURGER_RELEASE_AND_SOURCE_ASSETS.md" "$BUNDLE_STAGE/docs/UNBURGER_RELEASE_AND_SOURCE_ASSETS.md"
install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_RUNTIME_BUNDLE_V3.json" "$BUNDLE_STAGE/contracts/UNBURGER_RUNTIME_BUNDLE_V3.json"
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
  "format_version": 3,
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
  "quartet_movie_restoration_embedded": true,
  "developer_source_assets_capability": "br1_legacy_source_assets_v2",
  "developer_source_assets_supplemental_capability": "second_light_dlc_source_subset_v1",
  "developer_source_assets_container": "opaque-encrypted-v3",
  "developer_source_assets_clean_anchor_capability": "br1_legacy_clean_source_anchors_v1"
}
JSON

# Public release content may contain authored translations/configuration and binaries,
# but never materialized game archives or extracted game containers.
if find "$BUNDLE_STAGE" -type f \( -iname '*.PAK' -o -iname '*.PAK_' -o -iname '*.elixir' -o -iname '*.elixir.gz' -o -iname '*.g1m' -o -iname '*.g1t' \) -print -quit | grep -q .; then
  echo "ERROR: release staging contains a materialized game archive/asset" >&2
  exit 1
fi
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

echo "==> Package ${ARCHIVE_BASENAME}.unburger (format v3: tar + Zstandard)"
(
  cd "$BUNDLE_STAGE"
  find . -exec touch -h -t 202601010000.00 {} +
  find . -type f -printf '%P\0' | LC_ALL=C sort -z | \
    tar --null --no-recursion --format=ustar --owner=0 --group=0 --numeric-owner --mtime='2026-01-01 00:00:00 UTC' -T - -cf - | \
    zstd -q -19 -T0 -o "$UNBURGER"
)
zstd -q -t "$UNBURGER"
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

For BLUE REFLECTION Quartet, Translation, UNCENSOR and DLC are normal module choices and are enabled by default. Inside DLC, BLUE REFLECTION and BLUE REFLECTION: Second Light source families are both enabled by default and the cursor starts on Continue. UNCENSOR also exposes an optional restored-movie component using the three verified CNG_PC00_00/CNG_PC01_00/CNG_PC02_00 WEBM assets carried inside the public .unburger payload. One compatible `.unburger-assets` bundle can provide reduced source data for both DLC families and is auto-detected only beside the patcher/release `.unburger` payload (or through an explicit developer override). If a required capability is absent, the DLC source flow can use the corresponding standalone source installation.

BLUE REFLECTION legacy DLC can also use the optional Save Access step for existing Quartet saves. Native Second Light DLC restoration does not require an automatic save patch; its unresolved entitlement gates are restored through game-data story routing. On native Windows Save Access detects the normal Local AppData folder, while Linux supports Steam/Proton and loose Wine/Heroic prefixes. Every changed save is backed up before writing.

Run `SAVE_ACCESS.sh` on Linux or `SAVE_ACCESS.cmd` on Windows whenever you create a new playthrough/save and want the restored costume and Tropical Island access flags applied to it.

The patcher prepares verified game-file changes transactionally and keeps rollback data for managed installations. The public release does not contain rebuilt game PAKs, character models or other source-game payloads.
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
  ASSET_BASENAME="UNBURGER_DLC_ASSETS_v3"
  ASSET_BUNDLE="$OUTPUT_DIR/${ASSET_BASENAME}.unburger-assets"
  ASSET_SIDECAR="$ASSET_BUNDLE.sha256"
  rm -f "$ASSET_BUNDLE" "$ASSET_SIDECAR"
  echo "==> Build combined BLUE REFLECTION + Second Light DLC source-assets bundle"
  ASSET_ARGS=(--output "$ASSET_BUNDLE" --anchors "$ASSET_ANCHORS" --second-light-source-root "$SECOND_LIGHT_ASSETS_SOURCE" --quartet-root "$QUARTET_ASSETS_TARGET")
  if [[ -n "$ASSETS_SOURCE" ]]; then
    ASSET_ARGS+=(--source-root "$ASSETS_SOURCE")
  fi
  ASSET_BUILD_LOG="$WORK_DIR/asset-build.log"
  (
    cd "$PATCHER_ROOT"
    go run ./cmd/unburger-assets "${ASSET_ARGS[@]}"
  ) | tee "$ASSET_BUILD_LOG"
  RESOLVED_SOURCE="$(awk -F= '$1 == "SOURCE_ROOT" {sub(/^SOURCE_ROOT=/, ""); print; exit}' "$ASSET_BUILD_LOG")"
  if [[ -n "$RESOLVED_SOURCE" ]]; then
    mkdir -p "$(dirname "$ASSET_SOURCE_STATE")"
    printf '%s\n' "$RESOLVED_SOURCE" > "$ASSET_SOURCE_STATE"
  fi
  RESOLVED_SECOND_LIGHT="$(awk -F= '$1 == "SECOND_LIGHT_SOURCE_ROOT" {sub(/^SECOND_LIGHT_SOURCE_ROOT=/, ""); print; exit}' "$ASSET_BUILD_LOG")"
  RESOLVED_QUARTET="$(awk -F= '$1 == "QUARTET_ROOT" {sub(/^QUARTET_ROOT=/, ""); print; exit}' "$ASSET_BUILD_LOG")"
  [[ -z "$RESOLVED_SECOND_LIGHT" ]] || printf '%s\n' "$RESOLVED_SECOND_LIGHT" > "$SECOND_LIGHT_ASSET_SOURCE_STATE"
  [[ -z "$RESOLVED_QUARTET" ]] || printf '%s\n' "$RESOLVED_QUARTET" > "$QUARTET_ASSET_TARGET_STATE"
  sha256sum "$ASSET_BUNDLE" | sed "s#  .*#  ${ASSET_BASENAME}.unburger-assets#" > "$ASSET_SIDECAR"
  (
    cd "$PATCHER_ROOT"
    go run ./cmd/unburger-assets --inspect --output "$ASSET_BUNDLE" >/dev/null
  )
  printf '\nCombined DLC source bundle complete\n  %s\n  %s\n' "$ASSET_BUNDLE" "$ASSET_SIDECAR"
fi

printf '\nRelease complete\n  %s\n  %s\n  %s\n  %s\n' "$RELEASE_ZIP" "$RELEASE_SIDECAR" "$UNBURGER" "$UNBURGER_SIDECAR"
