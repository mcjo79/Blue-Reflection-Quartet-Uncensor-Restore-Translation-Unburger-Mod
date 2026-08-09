#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$HERE/../.." && pwd -P)"
exec python3 "$HERE/172_collect_graphics_capture_capability_evidence.py" --project-root "$PROJECT_ROOT" "$@"
