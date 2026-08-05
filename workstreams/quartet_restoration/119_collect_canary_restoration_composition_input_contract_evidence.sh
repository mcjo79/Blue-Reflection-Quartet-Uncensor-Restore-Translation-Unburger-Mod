#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
exec python3 "$SCRIPT_DIR/119_collect_canary_restoration_composition_input_contract_evidence.py" \
  --project-root "$PROJECT_ROOT" "$@"
