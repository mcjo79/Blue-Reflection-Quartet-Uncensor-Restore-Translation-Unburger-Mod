#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 -u "$ROOT/workstreams/quartet_restoration/collect_reflector_slot_light_paired_leaf_context_role_evidence.py" --project-root "$ROOT" "$@"
