#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Użycie:
  bash 97_run_bkn_dry_generation8_exact_availability_closure_evidence.sh \
    --original-dir PATH --game-dir PATH

Read-only exact availability closure for generation-8 dry BKN.
No candidate build, ACTIVE write, transaction, installation or runtime test.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd -P)}"
ORIGINAL_ROOT="${BR_ORIGINAL_GAME_ROOT:-}"
GAME_ROOT="${BR_QUARTET_GAME_ROOT:-}"

while (($#)); do
  case "$1" in
    --original-dir) [[ $# -ge 2 ]] || { echo 'ERROR: --original-dir wymaga wartości' >&2; exit 2; }; ORIGINAL_ROOT="$2"; shift 2 ;;
    --game-dir) [[ $# -ge 2 ]] || { echo 'ERROR: --game-dir wymaga wartości' >&2; exit 2; }; GAME_ROOT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: nieznany argument: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$ORIGINAL_ROOT" ]] || { echo 'ERROR: podaj --original-dir lub BR_ORIGINAL_GAME_ROOT' >&2; exit 2; }
[[ -n "$GAME_ROOT" ]] || { echo 'ERROR: podaj --game-dir lub BR_QUARTET_GAME_ROOT' >&2; exit 2; }
PROJECT_ROOT="$(realpath -e -- "$PROJECT_ROOT")"
ORIGINAL_ROOT="$(realpath -e -- "$ORIGINAL_ROOT")"
GAME_ROOT="$(realpath -e -- "$GAME_ROOT")"
[[ "$(tr -d '\r\n' < "$SCRIPT_DIR/VERSION")" == "0.0.57" ]] || { echo 'ERROR: quartet_legacy_dlc 0.0.57 is required' >&2; exit 1; }

python3 -m unittest -q \
  "$SCRIPT_DIR/tests/test_br_dlc_bkn_dry_exact_availability_closure_tool.py"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORTS="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
NAME="BR_QUARTET_DLC_BKN_DRY_GENERATION8_EXACT_AVAILABILITY_CLOSURE_${STAMP}"
OUT="$REPORTS/$NAME"
ARCHIVE="$REPORTS/$NAME.tar.zst"
SIDECAR="$ARCHIVE.sha256"
mkdir -p -- "$REPORTS"
[[ ! -e "$OUT" && ! -e "$ARCHIVE" ]] || { echo "ERROR: output already exists: $NAME" >&2; exit 1; }

python3 "$SCRIPT_DIR/br_dlc_bkn_dry_exact_availability_closure_tool.py" \
  --project-root "$PROJECT_ROOT" \
  --original-dir "$ORIGINAL_ROOT" \
  --game-dir "$GAME_ROOT" \
  --output-dir "$OUT"

cat > "$OUT/BUNDLE_INFO.txt" <<EOF
Type: generation-8 exact availability closure
Created UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Workstream: quartet_legacy_dlc 0.0.57
Generation: 8
Repository modified: no
Game modified: no
ACTIVE.json modified: no
Candidate build: no
Prepare called: no
Commit called: no
Runtime validation: no
PC08 build: no
EOF

(
  cd "$OUT"
  find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

tar --zstd -cf "$ARCHIVE" -C "$REPORTS" "$NAME"
(
  cd "$REPORTS"
  sha256sum "$NAME.tar.zst" > "$NAME.tar.zst.sha256"
)

echo
printf 'Exact availability closure evidence:\n  %s\n  %s\n' "$ARCHIVE" "$SIDECAR"
cat "$SIDECAR"
