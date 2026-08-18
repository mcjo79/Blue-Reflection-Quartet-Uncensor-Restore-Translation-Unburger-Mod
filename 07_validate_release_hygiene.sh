#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$PROJECT_ROOT/workstreams/core/validate_release_hygiene.py" --project-root "$PROJECT_ROOT"
