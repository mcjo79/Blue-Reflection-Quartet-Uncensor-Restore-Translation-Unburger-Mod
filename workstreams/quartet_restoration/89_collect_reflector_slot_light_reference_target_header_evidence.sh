#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -u "$SCRIPT_DIR/collect_reflector_slot_light_reference_target_header_evidence.py" --project-root "$SCRIPT_DIR/../.." "$@"
