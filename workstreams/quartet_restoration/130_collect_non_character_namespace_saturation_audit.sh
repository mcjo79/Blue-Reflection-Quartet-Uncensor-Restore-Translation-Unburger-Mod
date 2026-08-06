#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
exec python3 "$SCRIPT_DIR/130_collect_non_character_namespace_saturation_audit.py" --project-root "$PROJECT_ROOT" "$@"
