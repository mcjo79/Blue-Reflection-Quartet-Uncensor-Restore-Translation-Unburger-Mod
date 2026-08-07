#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
OUTPUT_DIR="$PROJECT_ROOT/.local/release"
QUARTET_DIR=""
REFRESH=0
KEEP_STAGE=0

usage() {
  cat <<'TXT'
Usage: ./BUILD_RELEASE.sh [options]

Options:
  --refresh                 Refresh the canonical local Translation build first.
  --quartet-dir PATH        Quartet installation used by --refresh.
  --output-dir PATH         Destination for .unburger artifacts.
  --keep-stage              Keep the verified staging directory after packaging.
  -h, --help                Show this help.
TXT
}

while (($#)); do
  case "$1" in
    --refresh) REFRESH=1; shift ;;
    --quartet-dir) QUARTET_DIR="${2:-}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --keep-stage) KEEP_STAGE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v go >/dev/null 2>&1 || { echo "ERROR: go is required" >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { echo "ERROR: tar is required" >&2; exit 1; }
command -v zstd >/dev/null 2>&1 || { echo "ERROR: zstd is required" >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "ERROR: sha256sum is required" >&2; exit 1; }

if ((REFRESH)); then
  [[ -n "$QUARTET_DIR" ]] || { echo "ERROR: --refresh requires --quartet-dir PATH" >&2; exit 1; }
  [[ -d "$QUARTET_DIR" ]] || { echo "ERROR: Quartet directory does not exist: $QUARTET_DIR" >&2; exit 1; }
  "$PROJECT_ROOT/workstreams/core/07_prepare_local_translation_payloads.sh" \
    --game-dir "$QUARTET_DIR" \
    --modules blue_reflection_translation \
    --preview-only \
    --json "$PROJECT_ROOT/.local/reports/core/BR_RELEASE_TRANSLATION_REFRESH.json"
fi

CORE_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/core/VERSION")"
TRANSLATION_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
RESTORATION_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_restoration/VERSION")"
DLC_VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")"
[[ -n "$CORE_VERSION" && -n "$TRANSLATION_VERSION" && -n "$RESTORATION_VERSION" && -n "$DLC_VERSION" ]] || {
  echo "ERROR: one or more workstream VERSION files are empty" >&2
  exit 1
}

mkdir -p "$OUTPUT_DIR" "$PROJECT_ROOT/.local/release/work"
WORK_DIR="$(mktemp -d "$PROJECT_ROOT/.local/release/work/unburger-release-XXXXXX")"
STAGE="$WORK_DIR/stage"
cleanup() {
  if ((KEEP_STAGE)); then
    echo "Release staging retained: $STAGE"
  else
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT

echo "==> Go regression"
(
  cd "$PATCHER_ROOT"
  go test ./...
  go vet ./...
)

echo "==> Stage verified module content"
(
  cd "$PATCHER_ROOT"
  go run ./cmd/unburger-release --project-root "$PROJECT_ROOT" --stage-root "$STAGE"
)

mkdir -p "$STAGE/bin/linux-amd64" "$STAGE/bin/windows-amd64" "$STAGE/meta"

echo "==> Build patcher binaries"
(
  cd "$PATCHER_ROOT"
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o "$STAGE/bin/linux-amd64/brpatcher" ./cmd/brpatcher
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o "$STAGE/bin/windows-amd64/brpatcher.exe" ./cmd/brpatcher
)

install -Dm644 "$PROJECT_ROOT/workstreams/core/VERSION" "$STAGE/workstreams/core/VERSION"
install -Dm644 "$PROJECT_ROOT/workstreams/quartet_restoration/VERSION" "$STAGE/workstreams/quartet_restoration/VERSION"
install -Dm644 "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION" "$STAGE/workstreams/quartet_legacy_dlc/VERSION"
install -Dm644 "$PROJECT_ROOT/workstreams/core/docs/BR1_LEGACY_CONTENT_0.0.69.md" "$STAGE/workstreams/core/docs/BR1_LEGACY_CONTENT_0.0.69.md"
install -Dm644 "$PROJECT_ROOT/workstreams/core/contracts/br1_legacy_content/BR1_LEGACY_CONTENT_REBUILD_V1.json" "$STAGE/workstreams/core/contracts/br1_legacy_content/BR1_LEGACY_CONTENT_REBUILD_V1.json"
install -Dm644 "$PROJECT_ROOT/titles/blue_reflection/modules/quartet_legacy_dlc/module.json" "$STAGE/titles/blue_reflection/modules/quartet_legacy_dlc/module.json"

cat > "$STAGE/meta/MODULE_VERSIONS.tsv" <<TXT
core	$CORE_VERSION
translation	$TRANSLATION_VERSION
quartet_restoration	$RESTORATION_VERSION
quartet_legacy_dlc	$DLC_VERSION
TXT

cat > "$STAGE/meta/CONTENT_POLICY.json" <<'JSON'
{
  "type": "unburger_content_policy",
  "format_version": 1,
  "quartet_composition_order": [
    "quartet_legacy_dlc",
    "quartet_restoration",
    "blue_reflection_translation"
  ],
  "translation_last": true,
  "large_source_game_archives_included": false,
  "legacy_content_materialized_locally": true,
  "restoration_materialized_locally": true
}
JSON

# Fail closed on archive-like game payloads that must be reconstructed locally.
if find "$STAGE" -type f \( -iname '*.PAK' -o -iname '*.PAK_' -o -iname '*.elixir' -o -iname '*.elixir.gz' \) -print -quit | grep -q .; then
  echo "ERROR: release staging contains a large game archive/container payload" >&2
  exit 1
fi

# The title marker and translated event members are permitted as bounded authored/modified payloads;
# full source-game archives are never packaged.
find "$STAGE" -type f -printf '%P\n' | LC_ALL=C sort > "$STAGE/meta/FILE_LIST.txt"
(
  cd "$STAGE"
  find . -type f ! -path './SHA256SUMS' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

ARCHIVE_BASENAME="UNBURGER_${CORE_VERSION}"
ARCHIVE="$OUTPUT_DIR/${ARCHIVE_BASENAME}.unburger"
SIDECAR="$ARCHIVE.sha256"
rm -f "$ARCHIVE" "$SIDECAR"

echo "==> Package $ARCHIVE_BASENAME.unburger"
tar -C "$STAGE" --sort=name --owner=0 --group=0 --numeric-owner --mtime='UTC 2026-01-01' -cf - . | zstd -T0 -19 -q -o "$ARCHIVE"
zstd -t -q "$ARCHIVE"
tar --use-compress-program=unzstd -tf "$ARCHIVE" >/dev/null
sha256sum "$ARCHIVE" | sed "s#  .*#  ${ARCHIVE_BASENAME}.unburger#" > "$SIDECAR"

printf '\nRelease complete\n  %s\n  %s\n' "$ARCHIVE" "$SIDECAR"
