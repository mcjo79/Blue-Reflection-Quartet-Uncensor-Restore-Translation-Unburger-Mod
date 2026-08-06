#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash workstreams/quartet_legacy_dlc/99_run_quartet_native_costume_positive_control_audit_evidence.sh \
    --game-dir PATH [--state-root PATH ...]

Read-only Quartet-native costume availability audit.
Platform/emulator configuration is auxiliary evidence only. Original-game AppID semantics are never imported.
No game, save, state, manifest, candidate, core or Git file is modified.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${BR_PROJECT_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd -P)}"
GAME_DIR=""
STATE_ROOTS=()

while (($#)); do
  case "$1" in
    --game-dir) GAME_DIR="${2:?}"; shift 2 ;;
    --state-root) STATE_ROOTS+=("${2:?}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$GAME_DIR" ]] || { echo "ERROR: --game-dir is required" >&2; exit 2; }
[[ "$(tr -d '\r\n' < "$SCRIPT_DIR/VERSION")" == "0.0.59" ]] || { echo "ERROR: quartet_legacy_dlc 0.0.59 is required" >&2; exit 1; }

REPORTS="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="BR_QUARTET_NATIVE_COSTUME_POSITIVE_CONTROL_AUDIT_${STAMP}"
STAGE="$(mktemp -d)"
ROOT="$STAGE/$NAME"
ARCHIVE="$REPORTS/$NAME.tar.zst"
SIDECAR="$ARCHIVE.sha256"
cleanup() { rm -rf -- "$STAGE"; }
trap cleanup EXIT
mkdir -p -- "$REPORTS"

ARGS=(--project-root "$PROJECT_ROOT" --game-dir "$GAME_DIR" --output-dir "$ROOT")
for state_root in "${STATE_ROOTS[@]}"; do
  ARGS+=(--state-root "$state_root")
done

python3 "$SCRIPT_DIR/br_dlc_quartet_native_costume_positive_control_audit_tool.py" "${ARGS[@]}"

cat > "$ROOT/BUNDLE_INFO.txt" <<EOF
Type: Quartet-native costume positive-control audit
Created UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Workstream: quartet_legacy_dlc 0.0.59
Game modified: no
Saves modified: no
Platform configuration modified: no
Raw save contents exported: no
Raw binary contents exported: no
Original AppID semantics imported: no
Platform configuration semantic authority: no
Prepare called: no
Commit called: no
Runtime validation performed: no
PC08 build allowed: no
Wet BKN allowed: no
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

echo "Quartet-native positive-control evidence: $ARCHIVE"
echo "SHA-256 sidecar: $SIDECAR"
