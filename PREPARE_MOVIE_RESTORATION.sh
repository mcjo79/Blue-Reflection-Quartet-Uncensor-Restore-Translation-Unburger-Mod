#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$PROJECT_ROOT/.local/Video/restored_webm"
BR1_ROOT=""
QUARTET_ROOT=""
FORCE=0

usage() {
  cat <<'TXT'
Usage: ./PREPARE_MOVIE_RESTORATION.sh --br1 PATH --quartet PATH [--force]

Developer/bootstrap helper for a fresh project workspace. It creates missing
Quartet-compatible WEBM movie-restoration files from the original BLUE REFLECTION
WMV video while copying the matching Opus audio stream from Quartet.

Existing already-canonical .local/Video/restored_webm/*.webm files are preserved
unless --force is explicitly supplied. Compatible existing files missing the
final BT.709 transfer/primaries tags are normalized once in place by stream
copy. This script is not part of the public installer and does not modify
.unburger-assets.
TXT
}

while (($#)); do
  case "$1" in
    --br1) BR1_ROOT="${2:-}"; shift 2 ;;
    --quartet) QUARTET_ROOT="${2:-}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$BR1_ROOT" && -n "$QUARTET_ROOT" ]] || { usage >&2; exit 2; }
for cmd in ffmpeg ffprobe jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 1; }
done

find_movie_dir() {
  local root="$1" kind="$2" candidate
  if [[ "$kind" == br1 ]]; then
    for candidate in "$root/DATA/x64/Movie" "$root/Data/x64/Movie" "$root/data/x64/Movie"; do
      [[ -d "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
    done
  else
    for candidate in "$root/Data/B1/x64/Movie" "$root/DATA/B1/x64/Movie" "$root/data/b1/x64/Movie"; do
      [[ -d "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
    done
  fi
  return 1
}

BR1_MOVIE_DIR="$(find_movie_dir "$BR1_ROOT" br1)" || { echo "ERROR: BR1 Movie directory not found under $BR1_ROOT" >&2; exit 1; }
QUARTET_MOVIE_DIR="$(find_movie_dir "$QUARTET_ROOT" quartet)" || { echo "ERROR: Quartet B1 Movie directory not found under $QUARTET_ROOT" >&2; exit 1; }
mkdir -p "$OUT_DIR"

MOVIES=(CNG_PC00_00 CNG_PC01_00 CNG_PC02_00)
for n in "${MOVIES[@]}"; do
  src="$BR1_MOVIE_DIR/$n.wmv"
  quartet="$QUARTET_MOVIE_DIR/$n.webm"
  out="$OUT_DIR/$n.webm"
  [[ -f "$src" ]] || { echo "ERROR: missing source WMV: $src" >&2; exit 1; }
  [[ -f "$quartet" ]] || { echo "ERROR: missing Quartet WEBM/audio reference: $quartet" >&2; exit 1; }
  if [[ -f "$out" && "$FORCE" != 1 ]]; then
    echo "==> Preserve existing canonical asset: $out"
    continue
  fi

  frames="$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames -of default=nw=1:nk=1 "$src")"
  [[ "$frames" == 915 ]] || { echo "ERROR: $src has $frames decoded frames; expected 915" >&2; exit 1; }

  echo "==> Convert $n: BR1 WMV video -> Quartet-compatible VP9/WebM"
  tmp="$out.tmp.webm"
  rm -f "$tmp"
  # BR1 has 915 frames. Quartet has 916. Preserve all source frames and clone
  # the terminal frame once; use the original Quartet Opus stream byte-for-byte.
  ffmpeg -hide_banner -loglevel warning -y \
    -i "$src" -i "$quartet" \
    -map 0:v:0 -map 1:a:0 \
    -vf "format=yuv420p,tpad=stop_mode=clone:stop=1,settb=AVTB,setpts=N*1001/(30000*TB),setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
    -frames:v 916 -r 30000/1001 -fps_mode cfr \
    -c:v libvpx-vp9 -profile:v 0 -pix_fmt yuv420p -b:v 12M \
    -deadline good -cpu-used 2 -row-mt 1 \
    -color_range tv -colorspace bt709 -color_trc bt709 -color_primaries bt709 \
    -c:a copy -map_metadata -1 \
    "$tmp"

  vprobe="$(ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,color_range,color_space,color_transfer,color_primaries,nb_read_frames -of json "$tmp")"
  jq -e '.streams|length==1 and .[0].codec_name=="vp9" and .[0].profile=="Profile 0" and .[0].width==1920 and .[0].height==1080 and .[0].pix_fmt=="yuv420p" and .[0].r_frame_rate=="30000/1001" and .[0].avg_frame_rate=="30000/1001" and .[0].color_range=="tv" and .[0].color_space=="bt709" and .[0].color_transfer=="bt709" and .[0].color_primaries=="bt709" and .[0].nb_read_frames=="916"' <<<"$vprobe" >/dev/null || {
    rm -f "$tmp"; echo "ERROR: converted video profile verification failed for $n" >&2; echo "$vprobe" >&2; exit 1;
  }
  aprobe="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,channel_layout -of json "$tmp")"
  jq -e '.streams|length==1 and .[0].codec_name=="opus" and .[0].sample_rate=="48000" and .[0].channels==2 and .[0].channel_layout=="stereo"' <<<"$aprobe" >/dev/null || {
    rm -f "$tmp"; echo "ERROR: converted audio profile verification failed for $n" >&2; echo "$aprobe" >&2; exit 1;
  }
  mv -f "$tmp" "$out"
done

echo "==> Finalize canonical movie metadata"
"$PROJECT_ROOT/NORMALIZE_MOVIE_RESTORATION_ASSETS.sh" --movie-root "$OUT_DIR"

echo "Movie restoration workspace ready: $OUT_DIR"
