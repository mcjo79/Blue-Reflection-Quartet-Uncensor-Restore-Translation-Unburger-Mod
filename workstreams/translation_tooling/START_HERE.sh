#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation_tooling/VERSION")"
printf 'Blue Reflection translation tooling / title marker workstream\n'
printf 'Version: %s\nProject root: %s\n\n' "$VERSION" "$PROJECT_ROOT"
printf '[DONE] active_english runtime adapter confirmed via Tardy Kashiwagi.\n'
printf '[DONE] Second Light production marker visible and approved.\n'
printf '[DONE] Quartet production marker visible and approved at text_rect Y=55.\n'
printf '[DONE] Original Blue Reflection production marker visible and approved.\n'
printf '[LOCKED] Production marker targets: steps 16, 22 and 24.\n'
printf '[DIAGNOSTIC ONLY] Steps 11-15 and 17-23 must not be repeated during normal builds.\n'
printf '[NEXT] Finalize metadata from the live local state, validate closed profiles, then continue with unified installer integration.\n'
printf '\nNext safe actions:\n'
printf '  %q\n' "$PROJECT_ROOT/workstreams/translation_tooling/26_finalize_title_marker_metadata.sh"
printf '  %q\n' "$PROJECT_ROOT/workstreams/translation_tooling/25_validate_title_marker_profiles.sh"
