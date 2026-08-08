#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
OUTPUT_DIR="$PROJECT_ROOT/.local/release"
KEEP_STAGE=0
REFRESH=0
ASSETS=0
ASSETS_SOURCE=""

usage() {
  cat <<'TXT'
Usage: ./BUILD_RELEASE.sh [options]

Build the complete distributable UNBURGER release ZIP from the current approved
project state. Translation records are regenerated from the canonical databases;
no prebuilt game PAK is used as public release content.

Options:
  --refresh                 Run the full project validation pass before packaging.
  --output-dir PATH         Destination for release artifacts.
  --keep-stage              Keep verified staging directories.
  --assets, -assets         Also build the developer BR1 DLC source-assets bundle.
  --assets-source PATH      BLUE REFLECTION (2017) game folder for --assets.
                            If omitted, Steam autodetection is used.
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
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$ASSETS_SOURCE" && "$ASSETS" != 1 ]]; then
  echo "ERROR: --assets-source requires --assets" >&2
  exit 2
fi

for cmd in go sha256sum jq zip unzip; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 1; }
done

version_ge() {
  local lhs="$1" rhs="$2"
  [[ "$(printf '%s\n%s\n' "$rhs" "$lhs" | sort -V | tail -n1)" == "$lhs" ]]
}

CORE_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/core/VERSION")"
TRANSLATION_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
DLC_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")"
[[ -n "$CORE_VERSION" && -n "$TRANSLATION_VERSION" && -n "$DLC_VERSION" ]] || {
  echo "ERROR: required VERSION file is empty" >&2; exit 1;
}
if [[ "${UNBURGER_ALLOW_PRE_RELEASE_TRANSLATION:-0}" != 1 ]] && ! version_ge "$TRANSLATION_VERSION" "0.0.203"; then
  echo "ERROR: Translation $TRANSLATION_VERSION is not release-closed; need 0.0.203 or newer" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR" "$PROJECT_ROOT/.local/release/work"
WORK_DIR="$(mktemp -d "$PROJECT_ROOT/.local/release/work/unburger-release-XXXXXX")"
BUNDLE_STAGE="$WORK_DIR/bundle"
RELEASE_STAGE="$WORK_DIR/release"
cleanup() {
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

echo "==> Build canonical Translation record payload"
(
  cd "$PATCHER_ROOT"
  go run ./cmd/unburger-release --project-root "$PROJECT_ROOT" --stage-root "$BUNDLE_STAGE"
)

mkdir -p "$BUNDLE_STAGE/bin/linux-amd64" "$BUNDLE_STAGE/bin/windows-amd64" "$BUNDLE_STAGE/meta" "$BUNDLE_STAGE/content/modules" "$BUNDLE_STAGE/docs" "$BUNDLE_STAGE/contracts"

echo "==> Build patcher binaries"
(
  cd "$PATCHER_ROOT"
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=$CORE_VERSION" -o "$BUNDLE_STAGE/bin/linux-amd64/brpatcher" ./cmd/brpatcher
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=$CORE_VERSION" -o "$BUNDLE_STAGE/bin/windows-amd64/brpatcher.exe" ./cmd/brpatcher
)
chmod 0755 "$BUNDLE_STAGE/bin/linux-amd64/brpatcher"

cat > "$BUNDLE_STAGE/RUN.sh" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/bin/linux-amd64/brpatcher" start --project-root "$ROOT" "$@"
SH
chmod 0755 "$BUNDLE_STAGE/RUN.sh"

cat > "$BUNDLE_STAGE/RUN.cmd" <<'CMD'
@echo off
setlocal
set "ROOT=%~dp0"
"%ROOT%bin\windows-amd64\brpatcher.exe" start --project-root "%ROOT%" %*
CMD

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
install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_RUNTIME_BUNDLE_V2.json" "$BUNDLE_STAGE/contracts/UNBURGER_RUNTIME_BUNDLE_V2.json"
if [[ -f "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_BR1_SOURCE_ASSETS_V1.json" ]]; then
  install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_BR1_SOURCE_ASSETS_V1.json" "$BUNDLE_STAGE/contracts/UNBURGER_BR1_SOURCE_ASSETS_V1.json"
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
quartet_restoration	quartet_bathroom_water_restoration_v1
quartet_legacy_dlc	$DLC_VERSION
TXT

cat > "$BUNDLE_STAGE/meta/CONTENT_POLICY.json" <<'JSON'
{
  "type": "unburger_content_policy",
  "format_version": 3,
  "quartet_composition_order": [
    "quartet_legacy_dlc",
    "quartet_restoration",
    "blue_reflection_translation"
  ],
  "translation_last": true,
  "translation_payload": "canonical_record_bundle",
  "whole_archive_version_lock": false,
  "compatible_installation_materialization": true,
  "large_source_game_archives_included": false,
  "legacy_content_materialized_locally": true,
  "restoration_materialized_locally": true,
  "developer_source_assets_capability": "br1_legacy_source_assets_v1"
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

echo "==> Package ${ARCHIVE_BASENAME}.unburger"
(
  cd "$BUNDLE_STAGE"
  find . -exec touch -h -t 202601010000.00 {} +
  find . -type f -printf '%P\n' | LC_ALL=C sort | zip -9 -X -q "$UNBURGER" -@
)
unzip -tqq "$UNBURGER"
sha256sum "$UNBURGER" | sed "s#  .*#  ${ARCHIVE_BASENAME}.unburger#" > "$UNBURGER_SIDECAR"

# The public ZIP contains only user-facing launchers/binaries and the canonical runtime payload.
# The patcher materializes the verified .unburger payload itself on first run.
mkdir -p "$RELEASE_STAGE/bin/linux-amd64" "$RELEASE_STAGE/bin/windows-amd64"
cp -a "$BUNDLE_STAGE/bin/linux-amd64/brpatcher" "$RELEASE_STAGE/bin/linux-amd64/brpatcher"
cp -a "$BUNDLE_STAGE/bin/windows-amd64/brpatcher.exe" "$RELEASE_STAGE/bin/windows-amd64/brpatcher.exe"
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
set "ROOT=%~dp0"
"%ROOT%bin\windows-amd64\brpatcher.exe" start --project-root "%ROOT%" %*
CMD

cat > "$RELEASE_STAGE/README.md" <<'MD'
# UNBURGER

Run `RUN.sh` on Linux or `RUN.cmd` on Windows. The patcher detects supported BLUE REFLECTION installations and opens the guided module selector.

For BLUE REFLECTION Quartet, Translation, UNCENSOR and DLC are normal module choices. DLC is shown only when Legacy DLC restoration is selected or installed. BR1 Legacy DLC reconstruction normally detects or asks for your own BLUE REFLECTION (2017) installation; you may choose a Steam installation/library or the game folder directly.

The patcher prepares verified changes transactionally and keeps rollback data for managed installations. The public release does not contain rebuilt game PAKs, character models or other source-game payloads.
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

RELEASE_BASENAME="UNBURGER_${CORE_VERSION}_RELEASE"
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
  ASSET_BASENAME="UNBURGER_BR1_DLC_ASSETS_v1"
  ASSET_BUNDLE="$OUTPUT_DIR/${ASSET_BASENAME}.unburger-assets"
  ASSET_SIDECAR="$ASSET_BUNDLE.sha256"
  rm -f "$ASSET_BUNDLE" "$ASSET_SIDECAR"
  echo "==> Build developer BR1 DLC source-assets bundle"
  ASSET_ARGS=(--output "$ASSET_BUNDLE")
  if [[ -n "$ASSETS_SOURCE" ]]; then
    ASSET_ARGS+=(--source-root "$ASSETS_SOURCE")
  fi
  (
    cd "$PATCHER_ROOT"
    go run ./cmd/unburger-assets "${ASSET_ARGS[@]}"
  )
  sha256sum "$ASSET_BUNDLE" | sed "s#  .*#  ${ASSET_BASENAME}.unburger-assets#" > "$ASSET_SIDECAR"
  (
    cd "$PATCHER_ROOT"
    go run ./cmd/unburger-assets --inspect --output "$ASSET_BUNDLE" >/dev/null
  )
  printf '\nDeveloper asset bundle complete\n  %s\n  %s\n' "$ASSET_BUNDLE" "$ASSET_SIDECAR"
fi

printf '\nRelease complete\n  %s\n  %s\n  %s\n  %s\n' "$RELEASE_ZIP" "$RELEASE_SIDECAR" "$UNBURGER" "$UNBURGER_SIDECAR"
