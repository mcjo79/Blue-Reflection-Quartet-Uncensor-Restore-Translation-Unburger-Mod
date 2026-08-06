#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash workstreams/quartet_legacy_dlc/98_run_bkn_dry_generation8_save_entitlement_surface_evidence.sh \
    --original-dir PATH --game-dir PATH [--state-root PATH ...]

Read-only. State roots may be Wine prefixes, platform configuration roots or patcher-state roots.
No save, registry, game, manifest, candidate, core or Git file is modified.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd -P)}"
ORIGINAL_DIR=""
GAME_DIR=""
STATE_ROOTS=()

while (($#)); do
  case "$1" in
    --original-dir) ORIGINAL_DIR="${2:?}"; shift 2 ;;
    --game-dir) GAME_DIR="${2:?}"; shift 2 ;;
    --state-root) STATE_ROOTS+=("${2:?}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$ORIGINAL_DIR" ]] || { echo "ERROR: --original-dir is required" >&2; exit 2; }
[[ -n "$GAME_DIR" ]] || { echo "ERROR: --game-dir is required" >&2; exit 2; }
[[ "$(tr -d '\r\n' < "$SCRIPT_DIR/VERSION")" == "0.0.58" ]] || { echo "ERROR: quartet_legacy_dlc 0.0.58 is required" >&2; exit 1; }

REPORTS="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="BR_QUARTET_DLC_BKN_DRY_GENERATION8_SAVE_ENTITLEMENT_SURFACE_${STAMP}"
STAGE="$(mktemp -d)"
ROOT="$STAGE/$NAME"
ARCHIVE="$REPORTS/$NAME.tar.zst"
SIDECAR="$ARCHIVE.sha256"
cleanup() { rm -rf -- "$STAGE"; }
trap cleanup EXIT
mkdir -p -- "$REPORTS"

ARGS=(
  --project-root "$PROJECT_ROOT"
  --original-dir "$ORIGINAL_DIR"
  --game-dir "$GAME_DIR"
  --output-dir "$ROOT"
)
for state_root in "${STATE_ROOTS[@]}"; do
  ARGS+=(--state-root "$state_root")
done

python3 "$SCRIPT_DIR/br_dlc_bkn_dry_save_entitlement_surface_tool.py" "${ARGS[@]}"

cat > "$ROOT/BUNDLE_INFO.txt" <<EOF
Type: generation-8 save and entitlement surface evidence
Created UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Workstream: quartet_legacy_dlc 0.0.58
Game modified: no
Saves modified: no
Registry modified: no
Raw save contents exported: no
Raw registry contents exported: no
Prepare called: no
Commit called: no
PC08 build allowed: no
EOF

(
  cd "$ROOT"
  find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

tar --zstd -cf "$ARCHIVE" -C "$STAGE" "$NAME"
(
  cd "$REPORTS"
  sha256sum "$NAME.tar.zst" > "$NAME.tar.zst.sha256"
)

echo "Save/entitlement surface evidence: $ARCHIVE"
echo "SHA-256 sidecar: $SIDECAR"
