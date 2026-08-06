#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT=""
GAME_DIR=""
OUTPUT_DIR=""

usage() {
  cat <<'USAGE'
Usage:
  validate_quartet_legacy_dlc_active_manifest.sh \
    --project-root PATH \
    --game-dir PATH \
    [--output-dir PATH]

Read-only validation of the DLC-owned active manifest and canonical
quartet_legacy_dlc payload preview. The command does not prepare or commit a
transaction and does not modify the game or patcher state.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) PROJECT_ROOT="${2:?missing value}"; shift 2 ;;
    --game-dir) GAME_DIR="${2:?missing value}"; shift 2 ;;
    --output-dir) OUTPUT_DIR="${2:?missing value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$PROJECT_ROOT" && -d "$PROJECT_ROOT" ]] || { echo "ERROR: --project-root is required" >&2; exit 1; }
[[ -n "$GAME_DIR" && -d "$GAME_DIR" ]] || { echo "ERROR: --game-dir is required" >&2; exit 1; }
PROJECT_ROOT="$(realpath "$PROJECT_ROOT")"
GAME_DIR="$(realpath "$GAME_DIR")"
MANIFEST_RELATIVE=".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
MANIFEST="$PROJECT_ROOT/$MANIFEST_RELATIVE"
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || {
  echo "ERROR: DLC-owned active manifest is missing or is a symlink: $MANIFEST" >&2
  echo "The quartet_legacy_dlc workstream must publish ACTIVE.json before canonical preview." >&2
  exit 1
}

if [[ -z "$OUTPUT_DIR" ]]; then
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  OUTPUT_DIR="$HOME/Downloads/BR_QUARTET_LEGACY_DLC_MANIFEST_PREVIEW_$STAMP"
fi
mkdir -p "$OUTPUT_DIR" "$PROJECT_ROOT/.local/build/patcher"
PATCHER="$PROJECT_ROOT/.local/build/patcher/blue-reflection-patcher-linux-x86_64"

cat "$PROJECT_ROOT/workstreams/core/VERSION" > "$OUTPUT_DIR/CORE_VERSION.txt"
cat "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION" > "$OUTPUT_DIR/DLC_VERSION.txt" 2>/dev/null || true
sha256sum "$MANIFEST" > "$OUTPUT_DIR/ACTIVE_MANIFEST.sha256"
cp "$MANIFEST" "$OUTPUT_DIR/ACTIVE_MANIFEST.json"

(
  cd "$PROJECT_ROOT/Blue_Reflection_Patcher"
  go test -count=1 ./internal/plan/payloadpreview
  go vet ./...
  go build -trimpath -o "$PATCHER" ./cmd/brpatcher
) > "$OUTPUT_DIR/SOURCE_VALIDATION.txt" 2>&1

"$PATCHER" transaction-status \
  --game-dir "$GAME_DIR" \
  --json "$OUTPUT_DIR/TRANSACTION_STATUS_BEFORE.json" \
  > "$OUTPUT_DIR/TRANSACTION_STATUS_BEFORE.txt"

for rel in Data/PACK10_02.PAK Data/PACK12.PAK; do
  path="$GAME_DIR/$rel"
  [[ -f "$path" && ! -L "$path" ]] || { echo "ERROR: baseline missing or symlink: $path" >&2; exit 1; }
  stat -c '%n\t%s\t%Y\t%i' "$path"
done > "$OUTPUT_DIR/GAME_TARGET_STAT_BEFORE.tsv"

"$PATCHER" payload-preview \
  --game-dir "$GAME_DIR" \
  --modules quartet_legacy_dlc \
  --no-prompt \
  --project-root "$PROJECT_ROOT" \
  --json "$OUTPUT_DIR/PAYLOAD_PREVIEW.json" \
  > "$OUTPUT_DIR/PAYLOAD_PREVIEW.txt"

"$PATCHER" transaction-status \
  --game-dir "$GAME_DIR" \
  --json "$OUTPUT_DIR/TRANSACTION_STATUS_AFTER.json" \
  > "$OUTPUT_DIR/TRANSACTION_STATUS_AFTER.txt"

for rel in Data/PACK10_02.PAK Data/PACK12.PAK; do
  path="$GAME_DIR/$rel"
  stat -c '%n\t%s\t%Y\t%i' "$path"
done > "$OUTPUT_DIR/GAME_TARGET_STAT_AFTER.tsv"

python3 "$PROJECT_ROOT/workstreams/core/tools/validate_quartet_legacy_dlc_preview_result.py" \
  --output-dir "$OUTPUT_DIR"

(
  cd "$OUTPUT_DIR"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)
ARCHIVE="$OUTPUT_DIR.tar.zst"
tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -C "$(dirname "$OUTPUT_DIR")" -cf - "$(basename "$OUTPUT_DIR")" \
  | zstd -T0 -19 -q -o "$ARCHIVE"
(
  cd "$(dirname "$ARCHIVE")"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
  sha256sum -c "$(basename "$ARCHIVE").sha256"
)

echo "Canonical generic Legacy DLC preview evidence:"
echo "$ARCHIVE"
echo "$ARCHIVE.sha256"
