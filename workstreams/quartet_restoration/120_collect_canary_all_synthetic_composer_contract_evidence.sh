#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
export PYTHONPATH="$SCRIPT_DIR:$SCRIPT_DIR/tests${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$SCRIPT_DIR/120_collect_canary_all_synthetic_composer_contract_evidence.py" --project-root "$PROJECT_ROOT" "$@"
