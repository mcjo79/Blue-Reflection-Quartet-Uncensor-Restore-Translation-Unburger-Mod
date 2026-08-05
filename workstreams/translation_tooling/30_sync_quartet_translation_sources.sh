#!/usr/bin/env bash
set -Eeuo pipefail
cat >&2 <<'EOF'
ERROR: step 30 is disabled.
The original source sync assigned Quartet b2 to Second Light and b4 to RAY.
That partition mapping is incorrect. Use the guarded correction instead:

  bash workstreams/translation_tooling/31_correct_quartet_game_mapping.sh --apply
EOF
exit 2
