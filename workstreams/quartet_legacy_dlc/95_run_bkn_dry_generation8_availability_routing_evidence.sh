#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash workstreams/quartet_legacy_dlc/95_run_bkn_dry_generation8_availability_routing_evidence.sh \
    --original-dir PATH \
    --game-dir PATH

Read-only audit of the missing Dressing Room availability route after the
runtime-tested BKN dry generation 8. The current Quartet installation may still
contain the accepted generation-8 candidates or may have been fully rolled back
to the manifest baseline. Mixed or unknown PAK states are rejected.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

ORIGINAL_ROOT=""
GAME_ROOT=""
while (($#)); do
  case "$1" in
    --original-dir)
      [[ $# -ge 2 ]] || fail "--original-dir requires a value"
      ORIGINAL_ROOT="$2"; shift 2 ;;
    --game-dir)
      [[ $# -ge 2 ]] || fail "--game-dir requires a value"
      GAME_ROOT="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      fail "unknown argument: $1" ;;
  esac
done

[[ -n "$ORIGINAL_ROOT" ]] || fail "provide --original-dir"
[[ -n "$GAME_ROOT" ]] || fail "provide --game-dir"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
VERSION="$(tr -d '\r\n' < "$SCRIPT_DIR/VERSION")"
[[ "$VERSION" == "0.0.56" ]] || fail "quartet_legacy_dlc 0.0.56 is required, got $VERSION"

ORIGINAL_ROOT="$(realpath -e -- "$ORIGINAL_ROOT")"
GAME_ROOT="$(realpath -e -- "$GAME_ROOT")"
REPORT_ROOT="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="BR_QUARTET_DLC_BKN_DRY_GENERATION8_AVAILABILITY_ROUTING_${STAMP}"
REPORT_DIR="$REPORT_ROOT/$NAME"
ARCHIVE="$REPORT_ROOT/$NAME.tar.zst"
SIDECAR="$ARCHIVE.sha256"

for command_name in python3 sha256sum tar zstd realpath find; do
  command -v "$command_name" >/dev/null 2>&1 || fail "missing required command: $command_name"
done

mkdir -p -- "$REPORT_ROOT"
rm -rf -- "$REPORT_DIR"
rm -f -- "$ARCHIVE" "$SIDECAR"

python3 "$SCRIPT_DIR/br_dlc_bkn_dry_availability_routing_tool.py" \
  --project-root "$PROJECT_ROOT" \
  --original-dir "$ORIGINAL_ROOT" \
  --game-dir "$GAME_ROOT" \
  --output-dir "$REPORT_DIR"

cat > "$REPORT_DIR/BUNDLE_INFO.txt" <<EOF
Type: generation-8 BKN dry availability-routing audit
Created UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Workstream: quartet_legacy_dlc 0.0.56
Runtime installation state: accepted only when both canonical PAKs are all generation-8 candidates or all manifest baselines
Repository modified: no
Game modified by this audit: no
ACTIVE.json modified: no
Candidate built: no
Prepare called: no
Commit called: no
Runtime validation performed by this audit: no
PC08 built: no
EOF

python3 - "$REPORT_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest_path = root / "REPORT_MANIFEST.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
known = {row["relative_path"]: row for row in manifest["files"]}
info = root / "BUNDLE_INFO.txt"
known["BUNDLE_INFO.txt"] = {
    "relative_path": "BUNDLE_INFO.txt",
    "size": info.stat().st_size,
    "sha256": hashlib.sha256(info.read_bytes()).hexdigest(),
}
manifest["files"] = [known[key] for key in sorted(known, key=str.casefold)]
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

(
  cd "$REPORT_DIR"
  find . -type f ! -name SHA256SUMS -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

tar --zstd -cf "$ARCHIVE" -C "$REPORT_ROOT" "$NAME"
(
  cd "$REPORT_ROOT"
  sha256sum "$NAME.tar.zst" > "$NAME.tar.zst.sha256"
)

printf '\nAvailability-routing evidence: %s\n' "$ARCHIVE"
printf 'SHA-256 sidecar: %s\n' "$SIDECAR"
cat "$SIDECAR"
