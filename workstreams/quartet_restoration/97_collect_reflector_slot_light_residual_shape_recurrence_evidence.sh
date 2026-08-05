#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 "$ROOT/workstreams/quartet_restoration/collect_reflector_slot_light_residual_shape_recurrence_evidence.py" --project-root "$ROOT"
