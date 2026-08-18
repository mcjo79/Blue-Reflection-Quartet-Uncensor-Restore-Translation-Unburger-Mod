#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MOVIE_ROOT="$PROJECT_ROOT/.local/Video/restored_webm"

usage() {
  cat <<'TXT'
Usage: ./NORMALIZE_MOVIE_RESTORATION_ASSETS.sh [--movie-root PATH]

One-time developer migration for existing Quartet movie-restoration WEBMs.
Compatible VP9/Opus files that are missing Matroska BT.709 transfer/primaries
metadata are remuxed in place with stream copy. Video and audio are never
re-encoded.

After this succeeds, BUILD_RELEASE.sh treats these files as immutable canonical
inputs: it verifies them and copies them, but never invokes FFmpeg or rewrites
them again.
TXT
}

while (($#)); do
  case "$1" in
    --movie-root) MOVIE_ROOT="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for cmd in ffmpeg ffprobe jq sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd is required" >&2; exit 1; }
done

MOVIES=(CNG_PC00_00.webm CNG_PC01_00.webm CNG_PC02_00.webm)

verify_base_video_profile() {
  local path="$1" probe
  probe="$(ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,color_range,color_space,color_transfer,color_primaries,nb_read_frames \
    -of json "$path")"
  jq -e '
    .streams|length==1 and
    .[0].codec_name=="vp9" and
    .[0].profile=="Profile 0" and
    .[0].width==1920 and .[0].height==1080 and
    .[0].pix_fmt=="yuv420p" and
    .[0].r_frame_rate=="30000/1001" and
    .[0].avg_frame_rate=="30000/1001" and
    .[0].time_base=="1/1000" and
    .[0].color_range=="tv" and
    .[0].color_space=="bt709" and
    ((.[0].color_transfer // "bt709")=="bt709") and
    ((.[0].color_primaries // "bt709")=="bt709") and
    .[0].nb_read_frames=="916"
  ' <<<"$probe" >/dev/null || {
    echo "ERROR: $(basename "$path") is not compatible with the canonical Quartet restoration video profile" >&2
    jq -r '.streams[0] | "  codec=\(.codec_name) profile=\(.profile) size=\(.width)x\(.height) pix_fmt=\(.pix_fmt) fps=\(.r_frame_rate)/\(.avg_frame_rate) time_base=\(.time_base) range=\(.color_range) matrix=\(.color_space) transfer=\(.color_transfer // "unspecified") primaries=\(.color_primaries // "unspecified") frames=\(.nb_read_frames)"' <<<"$probe" >&2
    return 1
  }
}

verify_audio_profile() {
  local path="$1" probe
  probe="$(ffprobe -v error -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels,channel_layout -of json "$path")"
  jq -e '.streams|length==1 and .[0].codec_name=="opus" and .[0].sample_rate=="48000" and .[0].channels==2 and .[0].channel_layout=="stereo"' <<<"$probe" >/dev/null || {
    echo "ERROR: $(basename "$path") does not contain canonical Quartet Opus 48k stereo audio" >&2
    echo "$probe" >&2
    return 1
  }
}

has_full_bt709_metadata() {
  local path="$1"
  ffprobe -v error -select_streams v:0 \
    -show_entries stream=color_transfer,color_primaries -of json "$path" \
    | jq -e '.streams|length==1 and .[0].color_transfer=="bt709" and .[0].color_primaries=="bt709"' >/dev/null
}

verify_full_canonical_profile() {
  local path="$1" probe
  probe="$(ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=codec_name,profile,width,height,pix_fmt,r_frame_rate,avg_frame_rate,time_base,color_range,color_space,color_transfer,color_primaries,nb_read_frames \
    -of json "$path")"
  jq -e '
    .streams|length==1 and
    .[0].codec_name=="vp9" and
    .[0].profile=="Profile 0" and
    .[0].width==1920 and .[0].height==1080 and
    .[0].pix_fmt=="yuv420p" and
    .[0].r_frame_rate=="30000/1001" and
    .[0].avg_frame_rate=="30000/1001" and
    .[0].time_base=="1/1000" and
    .[0].color_range=="tv" and
    .[0].color_space=="bt709" and
    .[0].color_transfer=="bt709" and
    .[0].color_primaries=="bt709" and
    .[0].nb_read_frames=="916"
  ' <<<"$probe" >/dev/null && verify_audio_profile "$path"
}

mkdir -p "$MOVIE_ROOT"
changed=0
for movie in "${MOVIES[@]}"; do
  path="$MOVIE_ROOT/$movie"
  [[ -f "$path" ]] || { echo "ERROR: missing movie restoration asset: $path" >&2; exit 1; }

  verify_base_video_profile "$path"
  verify_audio_profile "$path"

  if has_full_bt709_metadata "$path"; then
    verify_full_canonical_profile "$path"
    echo "==> Already canonical: $movie"
    continue
  fi

  echo "==> Normalize once: $movie (BT.709 metadata; stream copy only)"
  tmp="$MOVIE_ROOT/.${movie}.normalize.$$.tmp.webm"
  rm -f -- "$tmp"
  trap 'rm -f -- "${tmp:-}"' EXIT
  ffmpeg -hide_banner -loglevel warning -y \
    -i "$path" -map 0:v:0 -map 0:a:0 -c:v copy -c:a copy \
    -color_range tv -colorspace bt709 -color_trc bt709 -color_primaries bt709 \
    -map_metadata -1 "$tmp"
  verify_full_canonical_profile "$tmp" || {
    echo "ERROR: normalized movie failed canonical verification: $movie" >&2
    exit 1
  }
  chmod 0644 "$tmp"
  mv -f -- "$tmp" "$path"
  trap - EXIT
  changed=$((changed + 1))
done

echo
if ((changed)); then
  echo "Canonical movie restoration assets normalized in place: $changed file(s)"
else
  echo "Canonical movie restoration assets were already ready; no files changed."
fi
for movie in "${MOVIES[@]}"; do
  sha256sum "$MOVIE_ROOT/$movie"
done
