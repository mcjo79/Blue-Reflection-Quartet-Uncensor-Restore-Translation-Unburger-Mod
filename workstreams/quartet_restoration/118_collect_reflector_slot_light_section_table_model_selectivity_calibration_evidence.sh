#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/collect_reflector_slot_light_section_table_model_selectivity_calibration_evidence.py" "$@"
