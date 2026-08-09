#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$HERE/../.." && pwd -P)"
PY="$HERE/171_trace_wet_renderer_transition_callpath.py"
REPORT_DIR="$PROJECT_ROOT/.local/reports/quartet_restoration/wet_renderer_transition_callpath_evidence"
REPORT_ARCHIVE="$PROJECT_ROOT/.local/reports/quartet_restoration/BR_quartet_restoration_wet_renderer_transition_callpath_evidence.tar.zst"
USER_UID="$(id -u)"; USER_GID="$(id -g)"
set +e
python3 "$PY" --project-root "$PROJECT_ROOT" "$@"
rc=$?
set -e
if [[ $rc -ne 77 ]]; then exit "$rc"; fi
command -v sudo >/dev/null 2>&1 || { echo "[stage171] perf_event_open is restricted and sudo is unavailable." >&2; exit 77; }
echo "[stage171] Linux perf_event policy blocks same-user read-only sampling; requesting sudo." >&2
sudo -v
set +e
sudo python3 "$PY" --project-root "$PROJECT_ROOT" "$@"
rc=$?
set -e
if [[ $rc -eq 0 ]]; then sudo chown -R "$USER_UID:$USER_GID" "$REPORT_DIR" "$REPORT_ARCHIVE" 2>/dev/null || true; fi
exit "$rc"
