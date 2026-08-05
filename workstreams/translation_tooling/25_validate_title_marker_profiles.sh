#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$PROJECT_ROOT/workstreams/translation_tooling/title_marker_profile_validator.py"

command -v python3 >/dev/null 2>&1 || {
  printf 'ERROR: python3 is required\n' >&2
  exit 1
}

python3 "$TOOL" --project-root "$PROJECT_ROOT"
"$PROJECT_ROOT/04_validate_project_base.sh"
"$PROJECT_ROOT/06_validate_parallel_workstreams.sh"

printf '\nClosed title-marker profiles and project workstream boundaries are valid.\n'
