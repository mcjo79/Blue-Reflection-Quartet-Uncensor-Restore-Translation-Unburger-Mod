#!/usr/bin/env bash
# shellcheck shell=bash

br_workstream_lock_acquire() {
  local project_root="$1"
  local workstream_id="$2"
  local lock_root="$project_root/.local/locks"
  local lock_dir="$lock_root/$workstream_id.lock"

  mkdir -p -- "$lock_root"
  if ! mkdir -- "$lock_dir" 2>/dev/null; then
    printf 'ERROR: workstream is already locked: %s\n' "$workstream_id" >&2
    if [[ -f "$lock_dir/owner" ]]; then
      printf 'Lock owner:\n' >&2
      sed 's/^/  /' "$lock_dir/owner" >&2 || true
    fi
    return 1
  fi

  {
    printf 'pid=%s\n' "$$"
    printf 'host=%s\n' "$(hostname 2>/dev/null || printf unknown)"
    printf 'started_utc=%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    printf 'command='
    printf '%q ' "$0" "$@"
    printf '\n'
  } > "$lock_dir/owner"

  BR_WORKSTREAM_LOCK_DIR="$lock_dir"
  export BR_WORKSTREAM_LOCK_DIR
  trap 'br_workstream_lock_release' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

br_workstream_lock_release() {
  if [[ -n "${BR_WORKSTREAM_LOCK_DIR:-}" && -d "$BR_WORKSTREAM_LOCK_DIR" ]]; then
    rm -rf -- "$BR_WORKSTREAM_LOCK_DIR"
  fi
  BR_WORKSTREAM_LOCK_DIR=""
  export BR_WORKSTREAM_LOCK_DIR
}

br_workstream_lock_main() {
  if [[ $# -lt 4 ]]; then
    printf 'Usage: %s PROJECT_ROOT WORKSTREAM_ID -- COMMAND [ARG...]\n' "$0" >&2
    return 2
  fi

  local project_root="$1"
  local workstream_id="$2"
  shift 2

  if [[ "$1" != "--" ]]; then
    printf 'ERROR: expected -- before command\n' >&2
    return 2
  fi
  shift

  if [[ $# -eq 0 ]]; then
    printf 'ERROR: command is missing after --\n' >&2
    return 2
  fi
  if [[ ! -d "$project_root" ]]; then
    printf 'ERROR: project root does not exist: %s\n' "$project_root" >&2
    return 1
  fi
  if [[ ! "$workstream_id" =~ ^[a-z0-9_]+$ ]]; then
    printf 'ERROR: invalid workstream id: %s\n' "$workstream_id" >&2
    return 2
  fi

  br_workstream_lock_acquire "$project_root" "$workstream_id" "$@"
  "$@"
}

# Behave as a command only when executed directly. Sourcing this file keeps
# the helper functions available without running anything.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -Eeuo pipefail
  br_workstream_lock_main "$@"
fi
