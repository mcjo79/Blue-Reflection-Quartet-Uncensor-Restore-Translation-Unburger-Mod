#!/usr/bin/env bash
# Copy to .local/paths.sh and fill in local values.
# Never commit .local/paths.sh.

BR1_ORIGINAL_ROOT="/path/to/BLUE REFLECTION"
BR1_QUARTET_ROOT="/path/to/BLUE REFLECTION Quartet"
BR_SECOND_LIGHT_ROOT="/path/to/BLUE REFLECTION Second Light"

# Optional explicit binaries. Wrappers also check .local/vendor/gust_tools,
# ~/Downloads/gust_tools and PATH, and can build the local vendor source.
GUST_PAK_BIN=""
GUST_G1T_BIN=""
