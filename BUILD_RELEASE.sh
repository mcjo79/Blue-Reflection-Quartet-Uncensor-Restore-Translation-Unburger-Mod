#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
OUTPUT_DIR="$PROJECT_ROOT/.local/release"
KEEP_STAGE=0
REFRESH=0

usage() {
  cat <<'TXT'
Usage: ./BUILD_RELEASE.sh [options]

Build the complete distributable UNBURGER package from the current approved
project state. Translation records are regenerated from the canonical databases
on every invocation; no prebuilt game PAK is used as release content.

Options:
  --refresh                 Run the full validation pass before packaging.
  --output-dir PATH         Destination for .unburger artifacts.
  --keep-stage              Keep the verified staging directory.
  -h, --help                Show this help.
TXT
}

while (($#)); do
  case "$1" in
    --refresh) REFRESH=1; shift ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --keep-stage) KEEP_STAGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for cmd in go tar zstd sha256sum jq; do
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
STAGE="$WORK_DIR/stage"
cleanup() {
  if ((KEEP_STAGE)); then echo "Release staging retained: $STAGE"; else rm -rf "$WORK_DIR"; fi
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
  go run ./cmd/unburger-release --project-root "$PROJECT_ROOT" --stage-root "$STAGE"
)

mkdir -p "$STAGE/bin/linux-amd64" "$STAGE/bin/windows-amd64" "$STAGE/meta" "$STAGE/content/modules"

echo "==> Build patcher binaries"
(
  cd "$PATCHER_ROOT"
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o "$STAGE/bin/linux-amd64/brpatcher" ./cmd/brpatcher
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o "$STAGE/bin/windows-amd64/brpatcher.exe" ./cmd/brpatcher
)
chmod 0755 "$STAGE/bin/linux-amd64/brpatcher"

cat > "$STAGE/RUN.sh" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/bin/linux-amd64/brpatcher" start "$@"
SH
chmod 0755 "$STAGE/RUN.sh"

cat > "$STAGE/RUN.cmd" <<'CMD'
@echo off
setlocal
set "ROOT=%~dp0"
"%ROOT%bin\windows-amd64\brpatcher.exe" start %*
CMD

cat > "$STAGE/content/modules/quartet_restoration.json" <<'JSON'
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
install -Dm644 "$PROJECT_ROOT/titles/blue_reflection/modules/quartet_legacy_dlc/module.json" "$STAGE/content/modules/quartet_legacy_dlc.json"
mkdir -p "$STAGE/docs" "$STAGE/contracts"
install -Dm644 "$PROJECT_ROOT/workstreams/core/docs/UNBURGER_RUNTIME_MATERIALIZATION_0.0.74.md" "$STAGE/docs/UNBURGER_RUNTIME_MATERIALIZATION.md"
install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/release/UNBURGER_RUNTIME_BUNDLE_V2.json" "$STAGE/contracts/UNBURGER_RUNTIME_BUNDLE_V2.json"

if [[ "${UNBURGER_ALLOW_PRE_RELEASE_TRANSLATION:-0}" != 1 ]]; then
  for target in blue_reflection_original blue_reflection_quartet blue_reflection_ray_quartet blue_reflection_sun_quartet second_light_original second_light_quartet; do
    jq -e --arg target "$target" '.translation_targets | index($target) != null' "$STAGE/RELEASE_MANIFEST.json" >/dev/null || {
      echo "ERROR: release-closed Translation bundle is missing target $target" >&2
      exit 1
    }
  done
fi

cat > "$STAGE/meta/MODULE_VERSIONS.tsv" <<TXT
core	$CORE_VERSION
translation	$TRANSLATION_VERSION
quartet_restoration	quartet_bathroom_water_restoration_v1
quartet_legacy_dlc	$DLC_VERSION
TXT

cat > "$STAGE/meta/CONTENT_POLICY.json" <<'JSON'
{
  "type": "unburger_content_policy",
  "format_version": 2,
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
  "restoration_materialized_locally": true
}
JSON

# Release content may contain authored translations/configuration and binaries,
# but never materialized game archives or extracted game containers.
if find "$STAGE" -type f \( -iname '*.PAK' -o -iname '*.PAK_' -o -iname '*.elixir' -o -iname '*.elixir.gz' -o -iname '*.g1m' -o -iname '*.g1t' \) -print -quit | grep -q .; then
  echo "ERROR: release staging contains a materialized game archive/asset" >&2
  exit 1
fi

# Production release must not contain developer workspaces/repack reports.
if (cd "$STAGE" && find . -type f | grep -Eq '/\.local/|BR_TRANSLATION_(LOOSE_BUILD|PAK_REPACK|STANDALONE_MEMBER)_REPORT'); then
  echo "ERROR: release staging contains developer Translation build artifacts" >&2
  exit 1
fi

find "$STAGE" -type f -printf '%P\n' | LC_ALL=C sort > "$STAGE/meta/FILE_LIST.txt"
(
  cd "$STAGE"
  find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

ARCHIVE_BASENAME="UNBURGER_${CORE_VERSION}"
ARCHIVE="$OUTPUT_DIR/${ARCHIVE_BASENAME}.unburger"
SIDECAR="$ARCHIVE.sha256"
rm -f "$ARCHIVE" "$SIDECAR"

echo "==> Package ${ARCHIVE_BASENAME}.unburger"
tar -C "$STAGE" --sort=name --owner=0 --group=0 --numeric-owner --mtime='UTC 2026-01-01' -cf - . | zstd -T0 -19 -q -o "$ARCHIVE"
zstd -t -q "$ARCHIVE"
tar --use-compress-program=unzstd -tf "$ARCHIVE" >/dev/null
sha256sum "$ARCHIVE" | sed "s#  .*#  ${ARCHIVE_BASENAME}.unburger#" > "$SIDECAR"

printf '\nRelease complete\n  %s\n  %s\n' "$ARCHIVE" "$SIDECAR"
