#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -u "$SCRIPT_DIR/collect_reflector_slot_light_paired_leaf_member_role_callsite_evidence.py" "$@"
