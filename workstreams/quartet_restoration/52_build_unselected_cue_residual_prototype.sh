#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 "$ROOT/workstreams/quartet_restoration/build_unselected_cue_residual_prototype.py" --project-root "$ROOT" "$@"
