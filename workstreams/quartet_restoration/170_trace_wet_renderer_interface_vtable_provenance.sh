#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$HERE/../.." && pwd -P)"
exec python3 "$HERE/170_trace_wet_renderer_interface_vtable_provenance.py" --project-root "$PROJECT_ROOT" "$@"
