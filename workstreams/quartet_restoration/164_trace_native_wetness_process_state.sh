#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$HERE/../.." && pwd -P)"
[[ -f "$PROJECT_ROOT/.local/paths.sh" ]] || { echo "Missing $PROJECT_ROOT/.local/paths.sh" >&2; exit 1; }
# shellcheck disable=SC1091
source "$PROJECT_ROOT/.local/paths.sh"
: "${BR1_QUARTET_ROOT:?BR1_QUARTET_ROOT missing from .local/paths.sh}"

PY="$HERE/164_trace_native_wetness_process_state.py"
REPORT_DIR="$PROJECT_ROOT/.local/reports/quartet_restoration/native_wetness_process_state_trace_evidence"
REPORT_ARCHIVE="$PROJECT_ROOT/.local/reports/quartet_restoration/BR_quartet_restoration_native_wetness_process_state_trace_evidence.tar.zst"
USER_UID="$(id -u)"
USER_GID="$(id -g)"

set +e
python3 "$PY" "$PROJECT_ROOT" --game-root "$BR1_QUARTET_ROOT" --probe-access "$@"
probe_rc=$?
set -e

if [[ $probe_rc -eq 0 ]]; then
  exec python3 "$PY" "$PROJECT_ROOT" --game-root "$BR1_QUARTET_ROOT" "$@"
fi

if [[ $probe_rc -ne 77 ]]; then
  exit "$probe_rc"
fi

command -v sudo >/dev/null 2>&1 || {
  echo "[stage164] Process memory is protected and sudo is unavailable." >&2
  echo "[stage164] Rerun with --pid only if automatic process detection was wrong." >&2
  exit 77
}

echo "[stage164] Linux ptrace policy blocks same-user process memory reads; requesting sudo for READ-ONLY snapshots." >&2
sudo -v
set +e
sudo python3 "$PY" "$PROJECT_ROOT" --game-root "$BR1_QUARTET_ROOT" "$@"
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  sudo chown -R "$USER_UID:$USER_GID" "$REPORT_DIR" "$REPORT_ARCHIVE" 2>/dev/null || true
fi
exit "$rc"
