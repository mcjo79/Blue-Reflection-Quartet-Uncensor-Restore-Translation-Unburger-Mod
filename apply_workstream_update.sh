#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/workstream_update.py"

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s WORKSTREAM_UPDATE.zip\n' "$0" >&2
  exit 2
fi

exec python3 "$TOOL" \
  --project-root "$PROJECT_ROOT" \
  --package "$1"
