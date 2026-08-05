#!/usr/bin/env bash
set -Eeuo pipefail
cat >&2 <<'EOF'
The former raw-range audit was retired because Gust PAK members may be compressed.
Use the extraction-backed, checksum-verified canonical migration instead:
  bash workstreams/translation_tooling/30_sync_quartet_translation_sources.sh --apply
It preserves all existing records[*].en values and rolls back on validation failure.
EOF
exit 2
