#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'HELP'
Read file-name tables from one or more Gust PAK installations without
extracting game assets.

Usage:
  collect_pak_listings.sh GUST_PAK OUTPUT.tar.zst \
    TARGET_ID GAME_ROOT [TARGET_ID GAME_ROOT ...]

TARGET_ID must contain only lowercase letters, digits and underscores.
HELP
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ $# -ge 4 ]] || {
  usage >&2
  exit 2
}
(( ($# - 2) % 2 == 0 )) ||
  die "Targets must be supplied as TARGET_ID GAME_ROOT pairs"

GUST_PAK_INPUT="$1"
OUTPUT_FILE_INPUT="$2"
shift 2

for cmd in realpath awk find sort timeout sha256sum stat od sed tar zstd; do
  command -v "$cmd" >/dev/null 2>&1 || die "$cmd is required"
done

GUST_PAK="$(realpath -- "$GUST_PAK_INPUT")"
[[ -f "$GUST_PAK" ]] || die "gust_pak not found: $GUST_PAK_INPUT"
[[ -x "$GUST_PAK" ]] || die "gust_pak is not executable: $GUST_PAK"

mkdir -p -- "$(dirname -- "$OUTPUT_FILE_INPUT")"
OUTPUT_FILE="$(realpath -m -- "$OUTPUT_FILE_INPUT")"

case "$OUTPUT_FILE" in
  *.tar.zst) ;;
  *) die "Output file must end with .tar.zst" ;;
esac

TMP="$(mktemp -d)"
REPORT_NAME="BR_series_all_games_pak_listings"
REPORT="$TMP/$REPORT_NAME"
mkdir -p "$REPORT/listings"

cleanup() {
  rm -rf -- "$TMP"
}
trap cleanup EXIT

printf 'report_format\t3\n' > "$REPORT/report_info.tsv"
printf 'generated_utc\t%s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" >> "$REPORT/report_info.tsv"
printf 'mode\tgust_pak_list_only\n' >> "$REPORT/report_info.tsv"

{
  printf 'gust_pak_sha256\t'
  sha256sum -- "$GUST_PAK" | awk '{print $1}'
  printf 'gust_pak_usage_first_line\t'
  "$GUST_PAK" </dev/null 2>&1 | sed -n '1p' || true
} > "$REPORT/tool_info.tsv"

printf 'target\tarchive\tarchive_bytes\theader_file_count\tlisted_file_count\tstatus\tdetected_format\tmaster_key\n' \
  > "$REPORT/archive_summary.tsv"
printf 'target\tarchive\toffset_hex\tsize_hex\tpath\n' > "$REPORT/all_entries.tsv"
printf 'target\tarchive\toffset_hex\tsize_hex\tpath\n' > "$REPORT/candidate_entries.tsv"
printf 'target\tarchive\textension\tcount\n' > "$REPORT/extension_counts.tsv"
printf 'target\tarchive\tstatus\texit_code\n' > "$REPORT/run_status.tsv"

list_target() {
  local target_id="$1"
  local root_input="$2"
  local root
  local found=0

  [[ "$target_id" =~ ^[a-z0-9_]+$ ]] || die "Invalid target ID: $target_id"
  root="$(realpath -- "$root_input")"
  [[ -d "$root" ]] || die "Game root not found for $target_id: $root_input"

  mkdir -p "$REPORT/listings/$target_id"
  printf 'target\t%s\t<GAME_ROOT_%s>\n' \
    "$target_id" "${target_id^^}" >> "$REPORT/report_info.tsv"

  while IFS= read -r -d '' pak; do
    found=1

    local rel="${pak#"$root"/}"
    local safe_name
    safe_name="$(
      printf '%s' "$rel" |
        sed 's#[/\\]#__#g; s#[^A-Za-z0-9._-]#_#g'
    )"

    local raw_log="$REPORT/listings/$target_id/${safe_name}.log"
    local entries="$REPORT/listings/$target_id/${safe_name}.entries.tsv"
    local candidates="$REPORT/listings/$target_id/${safe_name}.candidates.tsv"
    local ext_counts="$REPORT/listings/$target_id/${safe_name}.extensions.tsv"

    local archive_bytes header_count
    archive_bytes="$(stat -c '%s' -- "$pak")"
    header_count="$(od -An -tu4 -j 4 -N 4 -- "$pak" | tr -d '[:space:]')"
    [[ -n "$header_count" ]] || header_count="unknown"

    printf 'Listing [%s] %s\n' "$target_id" "$rel"

    local rc=0
    set +e
    (
      cd -- "$(dirname -- "$pak")"
      timeout 300 "$GUST_PAK" -l "$(basename -- "$pak")" </dev/null
    ) >"$raw_log" 2>&1
    rc=$?
    set -e

    awk '
      length($1) == 9 && $1 !~ /[^0-9A-Fa-f]/ &&
      length($2) == 8 && $2 !~ /[^0-9A-Fa-f]/ {
        offset = $1
        size = $2
        $1 = ""
        $2 = ""
        sub(/^[[:space:]]+/, "", $0)
        sub(/\*$/, "", $0)
        sub(/[[:space:]]+$/, "", $0)
        print offset "\t" size "\t" $0
      }
    ' "$raw_log" > "$entries"

    awk -F '\t' '
      {
        p = tolower($3)
        if (p ~ /\.(ebm|ebd|xml|json|csv|tsv|txt|str|tbl|msg|mes|bin|dat|ini|cfg|lua|ks|lst|dic|po|mo|e)(\.gz)?$/ || p ~ /(^|\/)(event|events|message|messages|text|texts|script|scripts|scenario|scenarios|localize|localization|language|lang)(\/|$)/) {
          print
        }
      }
    ' "$entries" > "$candidates"

    awk -F '\t' '
      {
        p = $3
        n = split(p, a, "/")
        base = a[n]
        ext = "(none)"
        if (base ~ /\./) {
          sub(/^.*\./, "", base)
          ext = tolower(base)
        }
        count[ext]++
      }
      END {
        for (ext in count)
          print ext "\t" count[ext]
      }
    ' "$entries" | LC_ALL=C sort > "$ext_counts"

    local listed_count status detected_format master_key
    listed_count="$(wc -l < "$entries")"
    status="ok"

    if [[ $rc -ne 0 ]]; then
      status="failed"
    elif [[ "$listed_count" -eq 0 && "$header_count" != "0" ]]; then
      status="empty_listing"
    elif [[ "$header_count" != "unknown" && "$listed_count" != "$header_count" ]]; then
      status="count_mismatch"
    fi

    detected_format="$(
      sed -n 's/^Detected \(.*\) PAK format$/\1/p' "$raw_log" | head -n1
    )"
    master_key="$(
      sed -n 's/^Using \(.*\) master key$/\1/p' "$raw_log" | head -n1
    )"
    [[ -n "$detected_format" ]] || detected_format="unknown"
    [[ -n "$master_key" ]] || master_key="none"

    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$target_id" "$rel" "$archive_bytes" "$header_count" "$listed_count" \
      "$status" "$detected_format" "$master_key" \
      >> "$REPORT/archive_summary.tsv"

    printf '%s\t%s\t%s\t%s\n' \
      "$target_id" "$rel" "$status" "$rc" \
      >> "$REPORT/run_status.tsv"

    awk -v target="$target_id" -v archive="$rel" -F '\t' \
      'BEGIN{OFS="\t"} {print target, archive, $1, $2, $3}' \
      "$entries" >> "$REPORT/all_entries.tsv"

    awk -v target="$target_id" -v archive="$rel" -F '\t' \
      'BEGIN{OFS="\t"} {print target, archive, $1, $2, $3}' \
      "$candidates" >> "$REPORT/candidate_entries.tsv"

    awk -v target="$target_id" -v archive="$rel" -F '\t' \
      'BEGIN{OFS="\t"} {print target, archive, $1, $2}' \
      "$ext_counts" >> "$REPORT/extension_counts.tsv"

  done < <(
    find "$root" -type f -iname '*.pak' -print0 |
      LC_ALL=C sort -z
  )

  [[ $found -eq 1 ]] || die "No .PAK archives found under: $root"
}

while [[ $# -gt 0 ]]; do
  target_id="$1"
  root_path="$2"
  shift 2
  list_target "$target_id" "$root_path"
done

{
  printf 'target_count\t%s\n' \
    "$(awk -F '\t' '$1 == "target" {n++} END{print n+0}' "$REPORT/report_info.tsv")"
  printf 'archive_count\t%s\n' \
    "$(( $(wc -l < "$REPORT/archive_summary.tsv") - 1 ))"
  printf 'listed_entry_count\t%s\n' \
    "$(( $(wc -l < "$REPORT/all_entries.tsv") - 1 ))"
  printf 'candidate_entry_count\t%s\n' \
    "$(( $(wc -l < "$REPORT/candidate_entries.tsv") - 1 ))"
  printf 'failed_archive_count\t%s\n' \
    "$(awk -F '\t' 'NR > 1 && $3 != "ok" {n++} END{print n+0}' "$REPORT/run_status.tsv")"
} > "$REPORT/summary.tsv"

rm -f -- "$OUTPUT_FILE"
tar -C "$TMP" --zstd -cf "$OUTPUT_FILE" "$REPORT_NAME"

printf '\nCreated: %s\n' "$OUTPUT_FILE"
printf 'No game assets were extracted or copied; the report contains archive file-name tables only.\n'
