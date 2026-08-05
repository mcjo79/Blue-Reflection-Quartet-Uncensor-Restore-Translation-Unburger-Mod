#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/workstreams/quartet_restoration/collect_reflector_slot_light_continuing_record_transition_partition_evidence.py" --project-root "$ROOT"
