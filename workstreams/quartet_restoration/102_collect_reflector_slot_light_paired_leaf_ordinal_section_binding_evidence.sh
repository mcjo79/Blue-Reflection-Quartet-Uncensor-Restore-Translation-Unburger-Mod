#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 -u "$ROOT/workstreams/quartet_restoration/collect_reflector_slot_light_paired_leaf_ordinal_section_binding_evidence.py" --project-root "$ROOT" "$@"
