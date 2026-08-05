#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
exec python3 "$SCRIPT_DIR/collect_reflector_slot_light_swordflash_g1em_section_table_binding_evidence.py" --project-root "$PROJECT_ROOT" "$@"
