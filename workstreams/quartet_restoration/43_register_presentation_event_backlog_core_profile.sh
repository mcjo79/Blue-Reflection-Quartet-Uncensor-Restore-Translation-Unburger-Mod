#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
REGISTRAR="$PROJECT_ROOT/workstreams/quartet_restoration/register_presentation_event_backlog_core_profile.py"
python3 "$REGISTRAR" --project-root "$PROJECT_ROOT"

printf '\nCore registry validation:\n'
bash "$PROJECT_ROOT/Blue_Reflection_Patcher/cmd/br_quartet_profiles.sh" list
