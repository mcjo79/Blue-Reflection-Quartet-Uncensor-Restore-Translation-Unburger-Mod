#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

v() { tr -d '[:space:]' < "$PROJECT_ROOT/$1"; }

printf 'BLUE REFLECTION project\n'
printf 'Core: %s\n' "$(v workstreams/core/VERSION)"
printf 'Translation: %s\n' "$(v workstreams/translation/VERSION)"
printf 'Translation tooling: %s\n' "$(v workstreams/translation_tooling/VERSION)"
printf 'Quartet UNCENSOR/restoration: %s\n' "$(v workstreams/quartet_restoration/VERSION)"
printf 'Quartet DLC restoration: %s\n\n' "$(v workstreams/quartet_legacy_dlc/VERSION)"

cat <<'TXT'
Current PC state:
  [ACTIVE] Translation
  [ACTIVE] Quartet UNCENSOR/restoration
  [ACTIVE] UNCENSOR restored-movie child (default on)
  [ACTIVE] Quartet DLC restoration: BLUE REFLECTION + Second Light (both default on)

Runtime baseline carried into core 0.0.112 release workflow:
  [PASS] core 0.0.108 canonical live project state
  [PASS] underlying runtime behavior on Linux and Windows
  [PASS] DLC restoration
  [PASS] Translation insertion/composition
  [PASS] combined .unburger-assets build/read

Canonical state:
  config/canonical_state.json

Validation:
  ./04_validate_project_base.sh
  ./06_validate_parallel_workstreams.sh

Release:
  ./BUILD_RELEASE.sh
  ./BUILD_RELEASE.sh --refresh
  ./BUILD_RELEASE.sh --refresh --assets   # reuses a verified bundle when available
  ./NORMALIZE_MOVIE_RESTORATION_ASSETS.sh # one-time only if old movie inputs lack final BT.709 tags

Codex/parallel RE agents are research-only. Production integration, builds,
source-assets tooling and runtime-test packages belong to the primary orchestrator.
TXT
