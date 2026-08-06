#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
exec python3 "$SCRIPT_DIR/137_collect_effect_posteffect_bounded_exact_parser_queue_evidence.py" --project-root "$PROJECT_ROOT" "$@"
