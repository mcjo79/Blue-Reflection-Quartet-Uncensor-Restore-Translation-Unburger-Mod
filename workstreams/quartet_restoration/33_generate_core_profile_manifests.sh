#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
GENERATOR="$PROJECT_ROOT/workstreams/quartet_restoration/generate_core_profile_manifests.py"
CORE_LIST="$PROJECT_ROOT/Blue_Reflection_Patcher/cmd/br_quartet_profiles.sh"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -f "$GENERATOR" ]] || fail "Missing profile manifest generator: $GENERATOR"
[[ -f "$CORE_LIST" ]] || fail "Core 0.0.17+ profile command is missing: $CORE_LIST"

python3 "$GENERATOR" --project-root "$PROJECT_ROOT"

printf '\nCore registry validation:\n'
cd "$PROJECT_ROOT"
exec bash "$CORE_LIST" list
