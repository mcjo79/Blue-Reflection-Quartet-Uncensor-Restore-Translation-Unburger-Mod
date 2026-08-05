#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/translation/VERSION")"
printf 'Blue Reflection translation content workstream: %s\n' "$VERSION"
printf 'Scope: translated records, notes, review status and content changelog only.\n'
printf 'Canonical first game: %s\n' "$PROJECT_ROOT/titles/blue_reflection/translation"
printf 'Canonical Second Light: %s\n' "$PROJECT_ROOT/titles/second_light/translation"
printf 'Quartet reuses the first-game records; it has no separate translation database.\n'
printf 'Next package: translation 0.0.0 -> 0.0.1\n'
printf 'Build, repack, runtime tests and markers belong to translation_tooling.\n'
