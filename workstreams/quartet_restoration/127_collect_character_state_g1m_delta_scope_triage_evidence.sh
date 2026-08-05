#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec python3 -u "$ROOT/workstreams/quartet_restoration/127_collect_character_state_g1m_delta_scope_triage_evidence.py" \
  --project-root "$ROOT" \
  "$@"
