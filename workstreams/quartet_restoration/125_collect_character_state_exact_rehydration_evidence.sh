#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 -u "$ROOT/workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py" --project-root "$ROOT" "$@"
