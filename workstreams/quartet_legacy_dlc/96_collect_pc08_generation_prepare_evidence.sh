#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Użycie:
  bash workstreams/quartet_legacy_dlc/96_collect_pc08_generation_prepare_evidence.sh \
    --original-dir PATH \
    --game-dir PATH \
    [--output-dir PATH]

Zbiera read-only evidence potrzebne do checksum-gated generacji PC08:
- weryfikuje ACTIVE.json generacji 8 (PC00-PC07),
- weryfikuje oba parent candidates i potwierdza, że zmodyfikowana instalacja runtime odpowiada generacji 8,
- zachowuje czyste baseline hashes z ACTIVE.json bez traktowania zmodyfikowanej instalacji jako baseline,
- odczytuje wyłącznie suche assety PC08 z oryginalnego PACK00_02,
- sprawdza wrapper/nested roundtrip bez eksportowania assetów,
- odczytuje rekordy PC08_DLC_BKN i PC08_DLC_BKN_W z parent PACK12,
- zapisuje hashe źródeł i kontraktów,
- tworzy bundle .tar.zst i sidecar.

Nie modyfikuje repozytorium, manifestu ACTIVE.json ani plików gry.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
ORIGINAL_ROOT=""
QUARTET_ROOT=""
OUTPUT_DIR=""

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --project-root)
      [[ $# -ge 2 ]] || fail "--project-root wymaga wartości"
      PROJECT_ROOT="$2"; shift 2 ;;
    --original-dir)
      [[ $# -ge 2 ]] || fail "--original-dir wymaga wartości"
      ORIGINAL_ROOT="$2"; shift 2 ;;
    --game-dir)
      [[ $# -ge 2 ]] || fail "--game-dir wymaga wartości"
      QUARTET_ROOT="$2"; shift 2 ;;
    --output-dir)
      [[ $# -ge 2 ]] || fail "--output-dir wymaga wartości"
      OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      fail "nieznany argument: $1" ;;
  esac
done

[[ -n "$ORIGINAL_ROOT" ]] || fail "podaj --original-dir"
[[ -n "$QUARTET_ROOT" ]] || fail "podaj --game-dir"

PROJECT_ROOT="$(realpath -e -- "$PROJECT_ROOT")"
ORIGINAL_ROOT="$(realpath -e -- "$ORIGINAL_ROOT")"
QUARTET_ROOT="$(realpath -e -- "$QUARTET_ROOT")"

[[ -d "$PROJECT_ROOT/workstreams/quartet_legacy_dlc" ]] || fail "nieprawidłowy project root"
[[ -d "$ORIGINAL_ROOT" ]] || fail "nieprawidłowy original-dir"
[[ -d "$QUARTET_ROOT" ]] || fail "nieprawidłowy game-dir"
[[ "$(tr -d '\r\n' < "$PROJECT_ROOT/workstreams/quartet_legacy_dlc/VERSION")" == "0.0.54" ]] \
  || fail "wymagany jest quartet_legacy_dlc 0.0.54"

ACCEPTANCE="$PROJECT_ROOT/workstreams/quartet_legacy_dlc/BKN_DRY_GENERATION8_AVAILABILITY_ROUTING_ACCEPTANCE.json"
[[ -f "$ACCEPTANCE" && ! -L "$ACCEPTANCE" ]] \
  || fail "PC08 pozostaje zablokowane do czasu przyjęcia audytu availability/UI/unlock; brak BKN_DRY_GENERATION8_AVAILABILITY_ROUTING_ACCEPTANCE.json"
python3 - "$ACCEPTANCE" <<'PY_ACCEPT'
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
d=json.loads(p.read_text(encoding="utf-8"))
if d.get("status") != "accepted" or d.get("pc08_prepare_allowed") is not True:
    raise SystemExit("ERROR: PC08 preparation is not authorized by availability-routing acceptance")
PY_ACCEPT

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$PROJECT_ROOT/.local/reports/quartet_legacy_dlc"
fi
mkdir -p -- "$OUTPUT_DIR"
OUTPUT_DIR="$(realpath -e -- "$OUTPUT_DIR")"

for cmd in python3 sha256sum tar zstd realpath stat find; do
  command -v "$cmd" >/dev/null 2>&1 || fail "brak wymaganego programu: $cmd"
done

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="BR_QUARTET_DLC_BKN_DRY_PC08_GENERATION_PREPARE_${STAMP}"
STAGE="$(mktemp -d)"
ROOT="$STAGE/$NAME"
ARCHIVE="$OUTPUT_DIR/$NAME.tar.zst"
SIDECAR="$ARCHIVE.sha256"

cleanup() {
  rm -rf -- "$STAGE"
}
trap cleanup EXIT
mkdir -p -- "$ROOT"

python3 - "$PROJECT_ROOT" "$ORIGINAL_ROOT" "$QUARTET_ROOT" "$ROOT" <<'PY'
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

project = Path(sys.argv[1])
original = Path(sys.argv[2])
quartet = Path(sys.argv[3])
out = Path(sys.argv[4])

ws = project / "workstreams/quartet_legacy_dlc"
tool_path = ws / "br_dlc_bkn_dry_pc07_generation_tool.py"
if not tool_path.is_file() or tool_path.is_symlink():
    raise SystemExit(f"ERROR: brak bezpiecznego helpera: {tool_path}")

spec = importlib.util.spec_from_file_location("pc07_generation_tool_for_pc08_prepare", tool_path)
if spec is None or spec.loader is None:
    raise SystemExit("ERROR: nie można załadować helpera generacji")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def require_regular(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"ERROR: {label} nie jest zwykłym plikiem: {path}")

def safe_under(root: Path, rel: str, label: str) -> Path:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        raise SystemExit(f"ERROR: niebezpieczna ścieżka {label}: {rel}")
    resolved = (root / p).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise SystemExit(f"ERROR: ścieżka wychodzi poza root ({label}): {rel}")
    return resolved

def write_json(name: str, obj: Any) -> None:
    (out / name).write_text(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

def write_tsv(name: str, rows: list[dict[str, Any]]) -> None:
    path = out / name
    if not rows:
        path.write_text("status\nno_rows\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for row in rows:
            cooked = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, (dict, list, tuple, bool)):
                    value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                cooked[key] = value
            w.writerow(cooked)

active_path = project / ".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json"
require_regular(active_path, "ACTIVE.json")
active_bytes = active_path.read_bytes()
active = json.loads(active_bytes)

expected_members = [f"costume_pc{i:02d}_bkn" for i in range(8)]
if active.get("type") != "validated_quartet_legacy_dlc_payload":
    raise SystemExit("ERROR: nieoczekiwany typ ACTIVE.json")
if active.get("generation") != 8:
    raise SystemExit(f"ERROR: oczekiwano ACTIVE generation 8, jest {active.get('generation')}")
if active.get("members") != expected_members:
    raise SystemExit("ERROR: ACTIVE members nie są dokładnie PC00-PC07")
if active.get("source_kind") != "validated_quartet_legacy_dlc_handoff":
    raise SystemExit("ERROR: nieprawidłowy source_kind")
transaction = active.get("transaction", {})
if transaction.get("all_or_none") is not True or transaction.get("commit_enabled") is not False:
    raise SystemExit("ERROR: ACTIVE nie zachowuje all-or-none / commit_enabled=false")

artifacts = active.get("artifacts", [])
if len(artifacts) != 2 or {x.get("target_path") for x in artifacts} != {
    "Data/PACK10_02.PAK", "Data/PACK12.PAK"
}:
    raise SystemExit("ERROR: ACTIVE nie deklaruje dokładnie dwóch kanonicznych artefaktów")

parent_rows = []
baseline_rows = []
artifact_by_target = {x["target_path"]: x for x in artifacts}
for target in ("Data/PACK10_02.PAK", "Data/PACK12.PAK"):
    row = artifact_by_target[target]
    if row.get("operation") != "replace":
        raise SystemExit(f"ERROR: {target} nie używa operation=replace")
    candidate = safe_under(project, str(row["candidate_relative_path"]), f"candidate {target}")
    require_regular(candidate, f"candidate {target}")
    csize = candidate.stat().st_size
    chash = sha256_file(candidate)
    if csize != int(row["candidate_size"]) or chash != row["candidate_sha256"]:
        raise SystemExit(f"ERROR: candidate gate mismatch: {target}")
    parent_rows.append({
        "target_path": target,
        "relative_path": candidate.relative_to(project).as_posix(),
        "size": csize,
        "sha256": chash,
        "status": "passed",
    })

    installed = safe_under(quartet, target, f"modified runtime installation {target}")
    require_regular(installed, f"modified runtime installation {target}")
    isize = installed.stat().st_size
    ihash = sha256_file(installed)
    if isize != csize or ihash != chash:
        raise SystemExit(f"ERROR: modified runtime installation does not match generation-8 candidate: {target}")
    baseline_rows.append({
        "target_path": target,
        "clean_baseline_size_from_active_manifest": int(row["baseline_size"]),
        "clean_baseline_sha256_from_active_manifest": row["baseline_sha256"],
        "modified_runtime_installation_size": isize,
        "modified_runtime_installation_sha256": ihash,
        "modified_runtime_installation_matches_generation8_candidate": True,
        "clean_baseline_bytes_reverified_by_this_stage": False,
        "status": "passed",
    })

source_archive = module.locate_archive(original, "DATA/PACK00_02.PAK")
require_regular(source_archive, "oryginalny PACK00_02")
source_stat_before = (source_archive.stat().st_size, source_archive.stat().st_mtime_ns)
source_index = module.NESTED.index_pak(source_archive)

asset_specs = [
    {
        "role": "dry_parent",
        "source_archive": "DATA/PACK00_02.PAK",
        "source_member": "data/x64/character/pc08/pc08_dlc_bkn.elixir.gz",
        "target_member": "data/b1/x64/character/pc08/pc08_dlc_bkn.elixir.gz",
    },
    {
        "role": "dry_external_texture",
        "source_archive": "DATA/PACK00_02.PAK",
        "source_member": "data/x64/character/pc08/pc08_dlc_bkn.g1t",
        "target_member": "data/b1/x64/character/pc08/pc08_dlc_bkn.g1t",
    },
]

source_rows = []
payloads: dict[str, bytes] = {}
for spec_row in asset_specs:
    payload, entry = module.NESTED.read_pak_member(source_index, spec_row["source_member"])
    payloads[spec_row["role"]] = payload
    source_rows.append({
        **spec_row,
        "source_entry_index": entry.index,
        "size": len(payload),
        "sha256": sha256_bytes(payload),
        "raw_payload_exported": False,
        "status": "passed",
    })

source_stat_after = (source_archive.stat().st_size, source_archive.stat().st_mtime_ns)
if source_stat_before != source_stat_after:
    raise SystemExit("ERROR: oryginalny PACK00_02 zmienił się podczas odczytu")

parent_payload = payloads["dry_parent"]
decoded, decoded_sizes, _ = module.TRANSFER_BASE.gust_chunk_layout(
    parent_payload, "PC08 dry parent"
)
roundtrip = module.TRANSFER_BASE.encode_gust_chunks(decoded, decoded_sizes)
decoded2, sizes2, _ = module.TRANSFER_BASE.gust_chunk_layout(
    roundtrip, "PC08 dry parent roundtrip"
)
if decoded2 != decoded or sizes2 != decoded_sizes:
    raise SystemExit("ERROR: PC08 GUST wrapper roundtrip zmienił dane")

earc1 = module.BR.parse_earc_payload(
    decoded, label="PC08 BKN dry source", include_member_payloads=True
)
earc2 = module.BR.parse_earc_payload(
    decoded2, label="PC08 BKN dry roundtrip", include_member_payloads=True
)
inv1 = [(x["name"], x["size"], x["sha256"]) for x in earc1["members"]]
inv2 = [(x["name"], x["size"], x["sha256"]) for x in earc2["members"]]
if inv1 != inv2:
    raise SystemExit("ERROR: nested inventory PC08 zmieniło się w roundtrip")

nested_rows = [
    {
        "member_name": x["name"],
        "member_size": x["size"],
        "member_sha256": x["sha256"],
        "roundtrip_identical": True,
        "raw_payload_exported": False,
    }
    for x in earc1["members"]
]

pack12_parent = safe_under(
    project,
    artifact_by_target["Data/PACK12.PAK"]["candidate_relative_path"],
    "generation-8 PACK12 candidate",
)
pack12_index = module.NESTED.index_pak(pack12_parent)
matches = pack12_index.by_name.get(
    module.NESTED.safe_internal_name(module.TARGET_CHARABASE).casefold(), []
)
if len(matches) != 1:
    raise SystemExit("ERROR: parent PACK12 nie zawiera dokładnie jednego charabase.xml")
charabase_raw = module.PACK12_BASE.read_entry_plain(pack12_index, matches[0])
text, encoding = module.decode_xml(charabase_raw)
dry_record = module.find_record(text, "PC08_DLC_BKN").group(0)
wet_record = module.find_record(text, "PC08_DLC_BKN_W").group(0)
dry_attrs = module.attrs_from_record(dry_record)
wet_attrs = module.attrs_from_record(wet_record)

expected_old = {"Model": "PC08/PC08_Scl", "defaultTexture": "PC08/PC08_Scl"}
expected_wet = {"Model": "PC08/PC08_Scl_W", "defaultTexture": "PC08/PC08_Scl_W"}
for key, value in expected_old.items():
    if dry_attrs.get(key) != value:
        raise SystemExit(f"ERROR: PC08 dry {key}={dry_attrs.get(key)!r}, oczekiwano {value!r}")
for key, value in expected_wet.items():
    if wet_attrs.get(key) != value:
        raise SystemExit(f"ERROR: PC08 wet {key}={wet_attrs.get(key)!r}, oczekiwano {value!r}")

charabase = {
    "target_member": module.TARGET_CHARABASE,
    "dry_tag": "PC08_DLC_BKN",
    "wet_tag": "PC08_DLC_BKN_W",
    "encoding": encoding,
    "expected_old_values": expected_old,
    "new_values": {
        "Model": "PC08/PC08_DLC_Bkn",
        "defaultTexture": "PC08/PC08_DLC_Bkn",
    },
    "allowed_changed_fields": ["Model", "defaultTexture"],
    "target_raw_record_sha256": sha256_bytes(dry_record.encode(encoding)),
    "wet_raw_record_sha256": sha256_bytes(wet_record.encode(encoding)),
    "metadata_source_record_sha256": "6e3eefc669778c46de511a5bd29382409c407973bdefd839d33e59c2a60e59c6",
    "metadata_target_record_sha256": "407e490d60b5d3141385b071587b8ddff9514366b98934778fb5211997e9656f",
    "wet_record_preserved": True,
}

helper_names = [
    "br_dlc_transfer_probe_tool.py",
    "br_dlc_dry_pak_insertion_tool.py",
    "br_dlc_bkn_dry_pack12_repack_tool.py",
    "br_dlc_bkn_dry_pc07_generation_tool.py",
    "br_dlc_bkn_dry_generation_publish_tool.py",
]
helper_rows = []
for name in helper_names:
    path = ws / name
    require_regular(path, f"helper {name}")
    helper_rows.append({
        "path": f"workstreams/quartet_legacy_dlc/{name}",
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "status": "passed",
    })

core_paths = [
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc.go",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc_policy.json",
    "workstreams/core/contracts/quartet_legacy_dlc/GENERIC_ADAPTER_RETURN_CONTRACT.json",
    "workstreams/core/contracts/quartet_legacy_dlc/MANIFEST_POLICY.md",
    "workstreams/core/contracts/quartet_legacy_dlc/VALIDATED_QUARTET_LEGACY_DLC_PAYLOAD.schema.json",
    "workstreams/core/tools/validate_quartet_legacy_dlc_active_manifest.sh",
]
core_rows = []
for rel in core_paths:
    path = project / rel
    require_regular(path, f"core contract {rel}")
    core_rows.append({
        "path": rel,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "status": "passed",
    })

# Collect matching historical source-evidence rows without requiring a fixed layout.
evidence_matches = []
report_names = {
    "DLC_BR1_CANONICAL_SOURCE_REGISTRY.tsv",
    "DLC_BR1_DRY_BKN_CONTINUITY.tsv",
    "DLC_BR1_OFFICIAL_OVERLAY_RESOLUTION.tsv",
    "DLC_BKN_INDEX_BLOCK_AUDIT.tsv",
}
reports_root = project / ".local/reports/quartet_legacy_dlc"
for path in sorted(reports_root.rglob("*.tsv")):
    if path.name not in report_names or path.is_symlink():
        continue
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for line_no, row in enumerate(reader, start=2):
                rendered = "\t".join(str(v or "") for v in row.values()).casefold()
                if "pc08" not in rendered:
                    continue
                evidence_matches.append({
                    "report_relative_path": path.relative_to(project).as_posix(),
                    "report_sha256": sha256_file(path),
                    "line": line_no,
                    "row": row,
                })
    except OSError:
        continue

summary = {
    "type": "br_quartet_legacy_dlc_bkn_dry_pc08_generation_prepare_evidence",
    "format_version": 1,
    "status": "pass",
    "workstream_version": (ws / "VERSION").read_text(encoding="utf-8").strip(),
    "selected_character_id": "PC08",
    "candidate_state": "exact_source_and_parent_gates_collected_for_checksum_gated_build",
    "source_evidence": {
        "family_expansion_bundle_sha256": "7c3e88602fd6408f30fabac378561eb6858ae44f4df39777943329c2a035974a",
        "generation8_preview_bundle_sha256": "8d55909552b6d72373cbc621d387dc7631d430f8a371b20b0b130630f32799a0",
        "active_manifest_sha256": sha256_bytes(active_bytes),
    },
    "active_generation8": {
        "generation": 8,
        "members": expected_members,
        "relative_path": active_path.relative_to(project).as_posix(),
        "sha256": sha256_bytes(active_bytes),
    },
    "source_archive": {
        "relative_name": "DATA/PACK00_02.PAK",
        "size": source_archive.stat().st_size,
        "sha256": sha256_file(source_archive),
        "read_only_unchanged": True,
    },
    "source_assets": source_rows,
    "nested_roundtrip": {
        "status": "pass",
        "member_count": len(nested_rows),
        "decoded_size": len(decoded),
        "wrapper_roundtrip_identical": True,
    },
    "charabase_patch": charabase,
    "accepted_generation8_parent_candidates": parent_rows,
    "clean_baseline_metadata_and_modified_runtime_installation": baseline_rows,
    "helper_source_gates": helper_rows,
    "core_contract_gates": core_rows,
    "historical_evidence_match_count": len(evidence_matches),
    "authorization": {
        "local_candidate_build": False,
        "read_only_collection": True,
        "active_manifest_generation_9_publication": False,
        "prepare": False,
        "commit": False,
        "installation": False,
        "profile_registration": False,
        "runtime_validation": False,
        "wet_bkn": False,
        "translation_modification": False,
        "restoration_modification": False,
        "core_modification": False,
        "git_modification": False,
    },
    "raw_assets_exported": False,
    "game_files_written": False,
    "next_action": "construct a checksum-gated quartet_legacy_dlc update for PC08 generation 9 from this accepted evidence",
}

write_json("PC08_GENERATION_PREPARE_EVIDENCE.json", summary)
write_json("ACTIVE_GENERATION_8.json", active)
write_json("PC08_CHARABASE_PATCH.json", charabase)
write_tsv("PC08_SOURCE_ASSETS.tsv", source_rows)
write_tsv("PC08_NESTED_ROUNDTRIP.tsv", nested_rows)
write_tsv("GENERATION_8_PARENT_GATES.tsv", parent_rows)
write_tsv("CLEAN_BASELINE_METADATA_AND_MODIFIED_RUNTIME_INSTALLATION_GATES.tsv", baseline_rows)
write_tsv("HELPER_SOURCE_GATES.tsv", helper_rows)
write_tsv("CORE_CONTRACT_GATES.tsv", core_rows)
write_tsv("HISTORICAL_SOURCE_EVIDENCE_MATCHES.tsv", evidence_matches)
write_json("VALIDATION.json", {
    "type": "br_quartet_legacy_dlc_bkn_dry_pc08_generation_prepare_validation",
    "format_version": 1,
    "status": "pass",
    "generation": 8,
    "members": expected_members,
    "source_asset_count": len(source_rows),
    "parent_candidate_count": len(parent_rows),
    "baseline_metadata_and_runtime_installation_gate_count": len(baseline_rows),
    "wrapper_roundtrip_identical": True,
    "prepare_allowed": False,
    "commit_allowed": False,
    "installation_allowed": False,
    "runtime_validation_allowed": False,
    "game_files_written": False,
    "raw_assets_exported": False,
})
PY

cat > "$ROOT/BUNDLE_INFO.txt" <<EOF
Type: PC08 generation-prepare evidence
Created UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Workstream: quartet_legacy_dlc 0.0.54
Repository modified: no
Game modified by this collector: no
Current game state: modified runtime installation required to match generation-8 candidates
ACTIVE.json modified: no
Prepare called: no
Commit called: no
Raw assets exported: no
EOF

(
  cd "$ROOT"
  find . -type f ! -name SHA256SUMS -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

rm -f -- "$ARCHIVE" "$SIDECAR"
tar --zstd -cf "$ARCHIVE" -C "$STAGE" "$NAME"
(
  cd "$OUTPUT_DIR"
  sha256sum "$NAME.tar.zst" > "$NAME.tar.zst.sha256"
)

echo
echo "PC08 generation-prepare evidence: OK"
echo "Bundle:"
echo "  $ARCHIVE"
echo "Sidecar:"
echo "  $SIDECAR"
cat "$SIDECAR"
