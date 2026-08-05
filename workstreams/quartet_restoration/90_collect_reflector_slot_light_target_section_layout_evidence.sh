#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
exec python3 -u "$SCRIPT_DIR/collect_reflector_slot_light_target_section_layout_evidence.py" --project-root "$PROJECT_ROOT" "$@"
