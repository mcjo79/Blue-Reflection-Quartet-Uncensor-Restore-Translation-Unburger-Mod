#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
exec python3 "$SCRIPT_DIR/123_collect_character_asset_namespace_saturation_audit.py" --project-root "$PROJECT_ROOT" "$@"
