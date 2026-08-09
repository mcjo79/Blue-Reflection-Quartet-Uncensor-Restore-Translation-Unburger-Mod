#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$HERE/../.." && pwd -P)"
exec python3 "$HERE/173_capture_wet_school_dry_wet_renderdoc_frames.py" --project-root "$PROJECT_ROOT" "$@"
