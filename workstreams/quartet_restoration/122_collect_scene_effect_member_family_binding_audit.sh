#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
exec python3 "$SCRIPT_DIR/122_collect_scene_effect_member_family_binding_audit.py" --project-root "$PROJECT_ROOT" "$@"
