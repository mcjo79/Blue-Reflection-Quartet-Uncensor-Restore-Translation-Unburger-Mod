#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATHS_FILE="$PROJECT_ROOT/.local/paths.sh"
TOOL="$PROJECT_ROOT/Blue_Reflection_Text_Tool/br_distribution_tool.py"
PATCHER_ROOT="$PROJECT_ROOT/Blue_Reflection_Patcher"
MANIFEST="$PROJECT_ROOT/distribution/bundle/manifest.template.json"
REPORT_DIR="$PROJECT_ROOT/.local/reports"
BUILD_DIR="$PROJECT_ROOT/.local/build/patcher"
REPORT_JSON="$REPORT_DIR/BR_PC_PATCHER_ARCHITECTURE_VALIDATION.json"
REPORT_PACKAGE="$REPORT_DIR/BR_pc_patcher_architecture_validation.tar.zst"
DEVELOPMENT_BUNDLE="$BUILD_DIR/BlueReflection_Unburger_development.brpatch"
COMPILE_REPORT="$REPORT_DIR/BR_PATCHER_COMPILE_REPORT.tsv"
DETECTION_REPORT="$REPORT_DIR/BR_PATCHER_DETECTION_REPORT.json"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for cmd in python3 tar zstd sha256sum; do
  command -v "$cmd" >/dev/null 2>&1 || fail "$cmd is required"
done
[[ -f "$PATHS_FILE" ]] || fail "Missing local path configuration: $PATHS_FILE"
[[ -f "$TOOL" ]] || fail "Distribution validator is missing: $TOOL"
[[ -f "$MANIFEST" ]] || fail "Bundle manifest template is missing: $MANIFEST"

# shellcheck source=/dev/null
source "$PATHS_FILE"

mkdir -p -- "$REPORT_DIR" "$BUILD_DIR"

python3 "$TOOL" validate \
  --project-root "$PROJECT_ROOT" \
  --manifest "$MANIFEST" \
  --output "$REPORT_JSON"

python3 "$TOOL" build-bundle \
  --manifest "$MANIFEST" \
  --output "$DEVELOPMENT_BUNDLE"

printf 'component\tstatus\tsha256\tpath\n' > "$COMPILE_REPORT"

if command -v go >/dev/null 2>&1; then
  (
    cd -- "$PATCHER_ROOT"
    module_path="$(go list -m)"
    [[ "$module_path" == "local/blue-reflection-patcher" ]] || fail "Unexpected Go module path: $module_path"
    printf 'Go module namespace: %s (local, not a repository URL)\n' "$module_path"
    go test ./...
    go build -trimpath -o "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" ./cmd/brpatcher
    env GOOS=windows GOARCH=amd64 CGO_ENABLED=0 \
      go build -trimpath -o "$BUILD_DIR/blue-reflection-patcher-windows-x86_64.exe" ./cmd/brpatcher
  )

  for artifact in \
    "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" \
    "$BUILD_DIR/blue-reflection-patcher-windows-x86_64.exe"
  do
    printf '%s\tok\t%s\t%s\n' \
      "$(basename -- "$artifact")" \
      "$(sha256sum -- "$artifact" | awk '{print $1}')" \
      "${artifact#"$PROJECT_ROOT"/}" \
      >> "$COMPILE_REPORT"
  done

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" detect \
    --root "$BR1_ORIGINAL_ROOT" \
    --root "$BR1_QUARTET_ROOT" \
    --root "$BR_SECOND_LIGHT_ROOT" \
    --json "$DETECTION_REPORT"

  python3 - "$DETECTION_REPORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
expected = {
    "blue_reflection_original",
    "blue_reflection_quartet",
    "second_light_original",
}
found = {item["target_id"] for item in data}
if found != expected:
    raise SystemExit(f"Detection mismatch: expected {sorted(expected)}, found {sorted(found)}")
print("Detected all three configured PC installations.")
PY

  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" inspect-bundle \
    --bundle "$DEVELOPMENT_BUNDLE" >/dev/null
  "$BUILD_DIR/blue-reflection-patcher-linux-x86_64" plan \
    --bundle "$DEVELOPMENT_BUNDLE" \
    --root "$BR1_ORIGINAL_ROOT" \
    --root "$BR1_QUARTET_ROOT" \
    --root "$BR_SECOND_LIGHT_ROOT" \
    --json "$REPORT_DIR/BR_PATCHER_DEVELOPMENT_PLAN.json"
else
  printf 'go\tskipped\t-\tGo compiler not installed; source validation only\n' \
    >> "$COMPILE_REPORT"
  printf 'WARNING: Go is not installed; cross-platform binaries were not rebuilt locally.\n' >&2
fi

printf 'development_bundle\tok\t%s\t%s\n' \
  "$(sha256sum -- "$DEVELOPMENT_BUNDLE" | awk '{print $1}')" \
  "${DEVELOPMENT_BUNDLE#"$PROJECT_ROOT"/}" \
  >> "$COMPILE_REPORT"

rm -f -- "$REPORT_PACKAGE"
package_files=(
  config/project_version
  config/modules.tsv
  config/series_targets.tsv
  distribution/bundle/manifest.template.json
  .local/reports/BR_PC_PATCHER_ARCHITECTURE_VALIDATION.json
  .local/reports/BR_PATCHER_COMPILE_REPORT.tsv
)
[[ -f "$DETECTION_REPORT" ]] && package_files+=(.local/reports/BR_PATCHER_DETECTION_REPORT.json)
[[ -f "$REPORT_DIR/BR_PATCHER_DEVELOPMENT_PLAN.json" ]] && package_files+=(.local/reports/BR_PATCHER_DEVELOPMENT_PLAN.json)

tar -C "$PROJECT_ROOT" --zstd -cf "$REPORT_PACKAGE" "${package_files[@]}"

printf '\nValidated unified Windows/Linux patcher architecture.\n'
printf 'The development planner does not modify game files.\n'
printf 'Created report package:\n  %s\n' "$REPORT_PACKAGE"
