#!/usr/bin/env bash
set -Eeuo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")"
cat <<TXT
BLUE REFLECTION Quartet DLC restoration
Version: $VERSION

[ACTIVE] PC DLC restoration workstream.
[DEFAULT] BLUE REFLECTION and Second Light source families are both selected by default in the guided DLC selector.
[PASS] Core 0.0.107 user runtime: Windows + Linux DLC restoration PASS.
[PASS] Translation composition after restored content PASS.
[PASS] Combined .unburger-assets build/read PASS.

BLUE REFLECTION restoration:
  - 66 source-backed PC costumes across 15 characters
  - 122-entry final wardrobe roster
  - Tropical Island
  - Save Access remains required by the current restoration method

Second Light restoration:
  - costumes, DLC maps/battle fields, events/dialogue/notifications, facilities
  - Resonance Tide / Ryza content and known cauldron fix
  - native Quartet saves do NOT require mandatory save modification
  - access is restored through game-data/story re-gating

Source policy:
  - use user-owned BR1 / Second Light installations or a compatible reduced .unburger-assets bundle
  - one combined bundle supports both source families
  - no raw source-game PAKs are shipped in the public release

Historical numbered research scripts remain in this workstream for provenance and reproducibility.
They are not the current installation workflow. Use the normal patcher/BUILD_RELEASE path for production work.

Current status metadata:
  workstreams/quartet_legacy_dlc/STATUS.json
  titles/blue_reflection/modules/quartet_legacy_dlc/module.json
  config/canonical_state.json
TXT
