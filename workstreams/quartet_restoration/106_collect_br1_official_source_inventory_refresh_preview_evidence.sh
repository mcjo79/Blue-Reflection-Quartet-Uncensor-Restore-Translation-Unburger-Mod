#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -u "$SCRIPT_DIR/collect_br1_official_source_inventory_refresh_preview_evidence.py" "$@"
