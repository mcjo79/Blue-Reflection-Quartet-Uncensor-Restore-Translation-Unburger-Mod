#!/usr/bin/env bash
set -Eeuo pipefail
cat >&2 <<'EOF'
ERROR: Stage 58 is suspended and reclassified.
The 94 scene-wide literal-dash FE message sets are not currently treated as
base-game decensor payloads.  They have moved to the read-only
legacy_dlc_or_removed_content queue.  Do not rebuild the 282 EBM candidates
through the restoration workstream.

Continue with:
  bash workstreams/quartet_restoration/59_collect_fe13_remaining_residual_evidence.sh
EOF
exit 2
