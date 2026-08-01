#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'HELP'
Safely extract selected Gust PAK archives into generated project workspaces.

Usage:
  extract_text_archives.sh GUST_PAK PROJECT_ROOT \
    TARGET_ID GAME_ROOT PROJECT_ID WORKSPACE_NAME ARCHIVE_REL [more groups...]

Each target group contains exactly five arguments after PROJECT_ROOT.
The source PAK is opened read-only through a temporary symlink. gust_pak writes
only inside the generated workspace.
HELP
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ $# -ge 7 ]] || {
  usage >&2
  exit 2
}
(( ($# - 2) % 5 == 0 )) ||
  die "Archive definitions must be TARGET_ID GAME_ROOT PROJECT_ID WORKSPACE_NAME ARCHIVE_REL groups"

GUST_PAK_INPUT="$1"
PROJECT_ROOT_INPUT="$2"
shift 2

for cmd in realpath sha256sum stat timeout mktemp mv rm ln awk sed grep date; do
  command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required"
done

GUST_PAK="$(realpath -- "$GUST_PAK_INPUT")"
PROJECT_ROOT="$(realpath -- "$PROJECT_ROOT_INPUT")"
[[ -x "$GUST_PAK" ]] || die "gust_pak not executable: $GUST_PAK"
[[ -d "$PROJECT_ROOT" ]] || die "Project root missing: $PROJECT_ROOT"

TOOL_SHA256="$(sha256sum -- "$GUST_PAK" | awk '{print $1}')"
SUMMARY="$PROJECT_ROOT/.local/reports/BR_text_extraction_summary.tsv"
mkdir -p -- "$(dirname -- "$SUMMARY")"
printf 'target\tproject\tarchive\tsource_bytes\tsource_sha256\ttool_sha256\tstatus\tworkspace\n' > "$SUMMARY"

safe_remove_generated_dir() {
  local dir="$1"
  local marker="$dir/.br_generated_source.tsv"

  [[ -d "$dir" ]] || return 0
  [[ -f "$marker" ]] ||
    die "Refusing to replace unmarked directory: $dir"
  grep -qx $'generated_by\tBlue_Reflection_Text_Tool/extract_text_archives.sh' "$marker" ||
    die "Refusing to replace directory with an unknown marker: $dir"
  rm -rf -- "$dir"
}

extract_one() {
  local target_id="$1"
  local game_root_input="$2"
  local project_id="$3"
  local workspace_name="$4"
  local archive_rel="$5"

  [[ "$target_id" =~ ^[a-z0-9_]+$ ]] || die "Invalid target ID: $target_id"
  [[ "$project_id" =~ ^[a-z0-9_]+$ ]] || die "Invalid project ID: $project_id"
  [[ "$workspace_name" =~ ^[A-Za-z0-9_.-]+$ ]] || die "Invalid workspace name: $workspace_name"
  [[ "$archive_rel" != /* && "$archive_rel" != *".."* ]] ||
    die "Unsafe archive-relative path: $archive_rel"

  local game_root source_archive source_bytes source_sha
  game_root="$(realpath -- "$game_root_input")"
  source_archive="$game_root/$archive_rel"
  [[ -f "$source_archive" ]] || die "Source archive missing: $source_archive"

  source_bytes="$(stat -c '%s' -- "$source_archive")"
  source_sha="$(sha256sum -- "$source_archive" | awk '{print $1}')"

  local archive_base archive_stem parent final marker
  archive_base="$(basename -- "$source_archive")"
  archive_stem="${archive_base%.*}"
  parent="$PROJECT_ROOT/titles/$project_id/workspace/$workspace_name/archives"
  final="$parent/$archive_stem"
  marker="$final/.br_generated_source.tsv"
  mkdir -p -- "$parent"

  if [[ -f "$marker" ]]; then
    local old_source old_tool
    old_source="$(awk -F '\t' '$1=="source_sha256"{print $2}' "$marker")"
    old_tool="$(awk -F '\t' '$1=="tool_sha256"{print $2}' "$marker")"
    if [[ "$old_source" == "$source_sha" && "$old_tool" == "$TOOL_SHA256" &&
          -f "$final/$archive_stem.json" ]]; then
      printf 'Skipping unchanged [%s] %s\n' "$target_id" "$archive_rel"
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$target_id" "$project_id" "$archive_rel" "$source_bytes" "$source_sha" \
        "$TOOL_SHA256" "unchanged" "${final#"$PROJECT_ROOT"/}" >> "$SUMMARY"
      return 0
    fi
  fi

  safe_remove_generated_dir "$final"

  local tmp log manifest
  tmp="$(mktemp -d "$parent/.${archive_stem}.tmp.XXXXXX")"
  log="$tmp/extraction.log"
  manifest="$tmp/$archive_stem.json"

  ln -s -- "$source_archive" "$tmp/$archive_base"

  printf 'Extracting [%s] %s\n' "$target_id" "$archive_rel"
  local rc=0
  set +e
  (
    cd -- "$tmp"
    timeout 1800 "$GUST_PAK" "$archive_base"
  ) >"$log" 2>&1
  rc=$?
  set -e

  rm -f -- "$tmp/$archive_base"

  if [[ $rc -ne 0 ]]; then
    sed -n '1,200p' "$log" >&2
    rm -rf -- "$tmp"
    die "gust_pak failed for $source_archive (exit $rc)"
  fi

  [[ -f "$manifest" ]] || {
    sed -n '1,200p' "$log" >&2
    rm -rf -- "$tmp"
    die "Expected PAK reconstruction manifest was not created: $manifest"
  }

  {
    printf 'generated_by\tBlue_Reflection_Text_Tool/extract_text_archives.sh\n'
    printf 'generated_utc\t%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    printf 'target_id\t%s\n' "$target_id"
    printf 'project_id\t%s\n' "$project_id"
    printf 'archive_relative_path\t%s\n' "$archive_rel"
    printf 'source_bytes\t%s\n' "$source_bytes"
    printf 'source_sha256\t%s\n' "$source_sha"
    printf 'tool_sha256\t%s\n' "$TOOL_SHA256"
  } > "$tmp/.br_generated_source.tsv"

  mv -- "$tmp" "$final"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$target_id" "$project_id" "$archive_rel" "$source_bytes" "$source_sha" \
    "$TOOL_SHA256" "extracted" "${final#"$PROJECT_ROOT"/}" >> "$SUMMARY"
}

while [[ $# -gt 0 ]]; do
  extract_one "$1" "$2" "$3" "$4" "$5"
  shift 5
done

printf '\nExtraction summary:\n  %s\n' "$SUMMARY"
