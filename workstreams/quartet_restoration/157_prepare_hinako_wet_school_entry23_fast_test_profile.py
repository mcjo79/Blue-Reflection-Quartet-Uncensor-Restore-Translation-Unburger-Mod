#!/usr/bin/env python3
"""Stage 157: build a no-install PACK10_02 Fast Test profile for Hinako wet school.

The profile deliberately combines only two previously grounded components:

1. the exact Original ``PC00_Scl_W_P_School_Wet.g1m`` member, already observed
   runtime-stable in Quartet and known to restore the canonical smaller blue
   school-uniform neck/collar component; and
2. a target-native rebuild of Quartet ``pc00_scl_w.g1t`` in which only texture
   entry 23 is replaced by the exact Original wet entry 23.

Stage 156 established that Original and Quartet dry use the same entry-26
payload, Quartet wet entry 23 reuses that dry placeholder exactly, Original wet
entry 23 is a distinct 1024x1024 BC1 entry shared across nkd_w/scl_w/swm_w, and
Quartet's G1T can be rebuilt locally with exactly that one entry changed and
accepted by the parser/gust_g1t.

This stage builds and fully re-extracts a local PACK10_02 profile.  It does not
modify the installed game, does not activate the profile, and does not infer
transparency or droplet semantics from the texture alone.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.76"
PROFILE_ID = "fast_test_pc00_scl_w_school_wet_plus_entry23_cb35139a7e44"
TARGET_RELATIVE_PATH = "Data/PACK10_02.PAK"
EXPECTED_BASELINE_SHA256 = "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
EXPECTED_BASELINE_SIZE = 11402829898

NORMALIZED_PARENT_PATH = "data/x64/character/pc00/pc00_scl_w.elixir.gz"
TARGET_PARENT_SUFFIX = "data/b1/x64/character/pc00/pc00_scl_w.elixir.gz"
TARGET_G1T_SUFFIX = "data/b1/x64/character/pc00/pc00_scl_w.g1t"
NORMALIZED_G1T_PATH = "data/x64/character/pc00/pc00_scl_w.g1t"
EXPECTED_TARGET_PARENT_SHA256 = "9126342ff00977b68e38857e6638ed993b47175416d01078b62be9d2ab8ce8e6"
EXPECTED_TARGET_G1T_SHA256 = "fce98af6902a78f46d502d2b9084ff60e9112492bef6f13da91c13db010b71b0"
EXPECTED_SOURCE_G1T_SHA256 = "1fc4d57315bf480ff777cf86349b7a2747c5131a75d682eb1815ebb6d6c0666c"
FOCUS_TEXTURE_INDEX = 23
EXPECTED_SOURCE_ENTRY23_RAW_SHA256 = "cb35139a7e4435710f6228141fc4e9468f109726c3f2770faf8f73b8454aa047"
EXPECTED_TARGET_ENTRY23_RAW_SHA256 = "def9d9e706345713300d62bf63f292ec4a39af02a6d75a8151de1d5be03a1034"
EXPECTED_SOURCE_ENTRY23_PAYLOAD_SHA256 = "3ac334051bbf5ee86947bdb2a6aecc15dbc0456ba9b41e232278143a9a7f6727"
EXPECTED_TARGET_ENTRY23_PAYLOAD_SHA256 = "d7aea404adf36f9684696ac3ff6825481df126f04e639830254a09a3209cfc3a"

STAGE156_REPORT = "BR_quartet_restoration_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.tar.zst"
STAGE156_SHA256 = "78e975823454ca5416528d6e7f05b522d9b9b7599aab73c99d05b5a25f80367a"
STAGE156_ROOT = "hinako_wet_texture_content_alpha_rebuild_feasibility_evidence"
STAGE147_REPORT_SHA256 = "5e15a3b5c7fa4f37e3d1a8aedeb40a7cf40ceb6f0b5d9490fe94de287141e8d5"
STAGE148_ACTIVATION_SHA256 = "9c6e9431e23a6fd0e96aa5ff08dc897ac003584bfaf4fdd4e20babd08f4f3e49"
STAGE148_ROLLBACK_SHA256 = "113d6527cda4c787013d9af070927a52f1bf89735835600a76ae22644677aaed"

REPORT_DIR = "hinako_wet_school_entry23_fast_test_profile_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_school_entry23_fast_test_profile_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("fast_test_lab/wet_school_entry23_pc00")
MANIFEST_SUBDIR = Path("core_profiles/fast_test_lab")
FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps", ".dds", ".png"
)

class Stage157Error(RuntimeError):
    pass

def require(c: bool, m: str) -> None:
    if not c:
        raise Stage157Error(m)

def progress(m: str) -> None:
    print(f"[stage157] {m}", flush=True)

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def safe_relative(v: str, label: str) -> str:
    p = PurePosixPath(str(v).replace("\\", "/"))
    require(p.parts and not p.is_absolute() and ".." not in p.parts, f"unsafe {label}: {v}")
    return p.as_posix()

def load_module(path: Path, name: str) -> Any:
    require(path.is_file(), f"missing module: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"cannot load module: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "report archive creation failed")
    os.replace(tmp, output)

def extract_stage156(report_root: Path) -> dict[str, Any]:
    arc = report_root / STAGE156_REPORT
    require(arc.is_file(), f"missing stage-156 evidence: {arc}")
    actual = sha256_file(arc)
    require(actual == STAGE156_SHA256, f"stage-156 evidence SHA-256 drift: {actual}")
    with tempfile.TemporaryDirectory(prefix="stage157-prereq-") as td:
        listed = subprocess.run(["tar", "--zstd", "-tf", str(arc)], text=True, capture_output=True)
        require(listed.returncode == 0, listed.stderr.strip() or "cannot list stage-156 report")
        names = [safe_relative(x.strip(), "stage156 member") for x in listed.stdout.splitlines() if x.strip()]
        require(names and {PurePosixPath(x).parts[0] for x in names} == {STAGE156_ROOT}, "unexpected stage-156 report root")
        require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names), "proprietary payload in stage-156 evidence")
        cp = subprocess.run(["tar", "--zstd", "-xf", str(arc), "-C", td], text=True, capture_output=True)
        require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage-156 report")
        root = Path(td) / STAGE156_ROOT
        s = json.loads((root / "SUMMARY.json").read_text(encoding="utf-8"))
        require(s.get("tool_version") == "0.1.75", "stage-156 tool version drift")
        require(s.get("focus_texture_index") == FOCUS_TEXTURE_INDEX, "stage-156 focus texture drift")
        require(s.get("focus_exact_cross_game_dry_control") is True, "stage-156 exact dry control missing")
        require(s.get("focus_target_wet_reuses_exact_dry_entry") is True, "stage-156 target wet no longer reuses dry placeholder")
        require(s.get("focus_source_wet_shared_across_nkd_scl_swm") is True, "stage-156 cross-state wet sharing drift")
        require(s.get("focus_local_target_native_g1t_rebuild_feasible") is True, "stage-156 target-native G1T rebuild not feasible")
        require(s.get("focus_rebuild_changed_texture_entry_rows") == 1, "stage-156 rebuild changed-entry count drift")
        require(s.get("focus_rebuild_gust_g1t_status") == "ok", "stage-156 gust_g1t validation not OK")
        require(s.get("runtime_probe_candidate_rows") == 1, "stage-156 runtime-probe candidate count drift")
        require(s.get("runtime_validated") is False and s.get("production_eligible") is False, "stage-156 unexpectedly promoted")
        p = s.get("policy") or {}
        require(p.get("profile_built") is False and p.get("pak_repacked") is False and p.get("installed_game_modified") is False, "stage-156 write policy drift")
        return s

def find_member_by_suffix(members: Mapping[str, Mapping[str, Any]], suffix: str, label: str) -> tuple[str, Mapping[str, Any]]:
    matches = [(k, r) for k, r in members.items() if str(r.get("name", "")).replace("\\", "/").casefold().endswith(suffix.casefold())]
    require(len(matches) == 1, f"expected exactly one {label}, found {len(matches)}")
    return matches[0]

def verify_g1t_one_entry_change(stage155: Any, stage156: Any, baseline: bytes, candidate: bytes, index: int) -> list[dict[str, Any]]:
    b = stage155.parse_g1t(baseline, "stage157-target-g1t-baseline")
    c = stage155.parse_g1t(candidate, "stage157-target-g1t-candidate")
    require(b["texture_count"] == c["texture_count"], "G1T texture count changed")
    rows: list[dict[str, Any]] = []
    for i in range(int(b["texture_count"])):
        rb = stage156.raw_entry(baseline, b, i)
        rc = stage156.raw_entry(candidate, c, i)
        changed = rb != rc
        rows.append({
            "texture_index": i,
            "selected_entry": i == index,
            "baseline_raw_entry_sha256": sha256_bytes(rb),
            "candidate_raw_entry_sha256": sha256_bytes(rc),
            "changed": changed,
            "verified": (changed if i == index else not changed),
        })
    require(sum(bool(r["changed"]) for r in rows) == 1, "candidate G1T did not change exactly one texture entry")
    require(rows[index]["candidate_raw_entry_sha256"] == EXPECTED_SOURCE_ENTRY23_RAW_SHA256, "candidate G1T entry 23 does not equal Original wet entry")
    require(all(bool(r["verified"]) for r in rows), "G1T per-entry preservation failed")
    return rows

def resolve_source_g1t(project_root: Path, original_root: Path, quartet_root: Path, gust_pak: Path, workspace_root: Path, timeout_seconds: int) -> tuple[Path, bytes]:
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage157_br_g1t")
    stage125 = load_module(SCRIPT_DIR / "125_collect_character_state_exact_rehydration_evidence.py", "stage157_stage125")
    stage155 = load_module(SCRIPT_DIR / "155_collect_hinako_wet_texture_entry_differential_evidence.py", "stage157_stage155_source")
    stage156 = load_module(SCRIPT_DIR / "156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py", "stage157_stage156_source")
    inventories = stage125.load_asset_inventories(project_root)
    stage125.ensure_extraction_cache(
        project_root=project_root,
        workspace_root=workspace_root,
        inventories=inventories,
        required_paths=[NORMALIZED_G1T_PATH],
        original_root=original_root,
        quartet_root=quartet_root,
        gust_pak_path=gust_pak,
        br=br,
        timeout_seconds=timeout_seconds,
    )
    pair_id, entry = inventories[("source", NORMALIZED_G1T_PATH.casefold())]
    local = br.inventory_workspace_file(workspace_root, "source", pair_id, str(entry["archive"]), str(entry["path"]))
    require(local.is_file(), f"missing extracted source G1T: {local}")
    require(sha256_file(local) == EXPECTED_SOURCE_G1T_SHA256, "source pc00_scl_w.g1t hash drift")
    data = local.read_bytes()
    parsed = stage155.parse_g1t(data, "stage157-source-scl_w")
    raw = stage156.raw_entry(data, parsed, FOCUS_TEXTURE_INDEX)
    require(sha256_bytes(raw) == EXPECTED_SOURCE_ENTRY23_RAW_SHA256, "source entry 23 raw hash drift")
    payload = stage156.payload_entry(data, parsed, FOCUS_TEXTURE_INDEX)
    require(sha256_bytes(payload) == EXPECTED_SOURCE_ENTRY23_PAYLOAD_SHA256, "source entry 23 payload hash drift")
    return local, raw

def build_profile_from_inputs(
    project_root: Path,
    *,
    baseline_archive: Path,
    source_school_wet_member: bytes,
    source_entry23_raw: bytes,
    gust_pak: Path,
    workspace_root: Path,
    manifest_root: Path,
    timeout_seconds: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    br = load_module(project_root / "Blue_Reflection_Text_Tool/br_restoration_tool.py", "stage157_br_build")
    stage147 = load_module(SCRIPT_DIR / "147_prepare_hinako_wet_school_uniform_fast_test_profile.py", "stage157_stage147_build")
    stage155 = load_module(SCRIPT_DIR / "155_collect_hinako_wet_texture_entry_differential_evidence.py", "stage157_stage155_build")
    stage156 = load_module(SCRIPT_DIR / "156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py", "stage157_stage156_build")

    baseline_archive = baseline_archive.resolve()
    require(baseline_archive.is_file(), f"missing Quartet PACK10_02: {baseline_archive}")
    require(gust_pak.is_file() and os.access(gust_pak, os.X_OK), f"gust_pak missing or not executable: {gust_pak}")
    progress("hashing exact installed PACK10_02 baseline (read-only)")
    baseline_sha = sha256_file(baseline_archive)
    baseline_size = baseline_archive.stat().st_size
    require(baseline_sha == EXPECTED_BASELINE_SHA256, f"PACK10_02 baseline hash drift: {baseline_sha}")
    require(baseline_size == EXPECTED_BASELINE_SIZE, f"PACK10_02 baseline size drift: {baseline_size}")

    workspace_root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(workspace_root).free
    required_free = baseline_size * 2 + 2 * 1024 * 1024 * 1024
    progress(f"workspace free space: {free} bytes; conservative minimum: {required_free} bytes")
    require(free >= required_free, f"insufficient free space: free={free}, required>={required_free}")

    profile_root = workspace_root / WORKSPACE_SUBDIR / PROFILE_ID
    marker = profile_root / "HARNESS.json"
    if profile_root.exists():
        require(marker.is_file(), f"refusing to remove unmarked profile root: {profile_root}")
        md = json.loads(marker.read_text(encoding="utf-8"))
        require(md.get("type") == "br_quartet_restoration_wet_school_entry23_fast_test_profile_workspace" and md.get("profile_id") == PROFILE_ID, f"refusing to remove foreign profile root: {profile_root}")
        shutil.rmtree(profile_root)
    profile_root.mkdir(parents=True)
    atomic_json(marker, {"type": "br_quartet_restoration_wet_school_entry23_fast_test_profile_workspace", "format_version": 1, "profile_id": PROFILE_ID, "status": "building"})

    baseline_extract = profile_root / "baseline_extract"
    verify_extract = profile_root / "verify_extract"
    output_dir = profile_root / "output" / "Data"
    output_dir.mkdir(parents=True)
    try:
        progress("extracting baseline PACK10_02 into local workspace")
        manifest_path, baseline_manifest = br._extract_pak_for_repack_test(
            archive=baseline_archive, destination=baseline_extract, gust_pak=gust_pak,
            timeout_seconds=timeout_seconds, log_name="baseline_extract.log",
        )
        baseline_members = br._manifest_member_hashes(baseline_extract, baseline_manifest)
        baseline_signature = br._gust_manifest_semantic_signature(baseline_manifest)
        parent_key, parent_row = find_member_by_suffix(baseline_members, TARGET_PARENT_SUFFIX, "pc00_scl_w Elixir")
        g1t_key, g1t_row = find_member_by_suffix(baseline_members, TARGET_G1T_SUFFIX, "pc00_scl_w G1T")
        require(parent_key != g1t_key, "parent and G1T unexpectedly resolve to same PAK member")
        target_parent = baseline_extract / Path(str(parent_row["name"]))
        target_g1t = baseline_extract / Path(str(g1t_row["name"]))
        require(sha256_file(target_parent) == EXPECTED_TARGET_PARENT_SHA256, "baseline pc00_scl_w parent hash drift")
        require(sha256_file(target_g1t) == EXPECTED_TARGET_G1T_SHA256, "baseline pc00_scl_w.g1t hash drift")

        progress("applying the previously runtime-stable School_Wet G1M component")
        candidate_parent, parent_rows, parent_meta = stage147.rebuild_earc_with_member(br, target_parent, source_school_wet_member)
        candidate_parent_sha = sha256_bytes(candidate_parent)
        target_parent.write_bytes(candidate_parent)

        progress("rebuilding target-native pc00_scl_w.g1t with only Original wet entry 23")
        target_g1t_bytes = target_g1t.read_bytes()
        parsed_target = stage155.parse_g1t(target_g1t_bytes, "stage157-target-scl_w-baseline")
        baseline_entry23 = stage156.raw_entry(target_g1t_bytes, parsed_target, FOCUS_TEXTURE_INDEX)
        require(sha256_bytes(baseline_entry23) == EXPECTED_TARGET_ENTRY23_RAW_SHA256, "baseline target entry 23 raw hash drift")
        require(sha256_bytes(stage156.payload_entry(target_g1t_bytes, parsed_target, FOCUS_TEXTURE_INDEX)) == EXPECTED_TARGET_ENTRY23_PAYLOAD_SHA256, "baseline target entry 23 payload hash drift")
        require(sha256_bytes(source_entry23_raw) == EXPECTED_SOURCE_ENTRY23_RAW_SHA256, "source entry 23 raw hash drift")
        candidate_g1t = stage156.rebuild_one_entry(target_g1t_bytes, stage155, FOCUS_TEXTURE_INDEX, source_entry23_raw)
        g1t_rows = verify_g1t_one_entry_change(stage155, stage156, target_g1t_bytes, candidate_g1t, FOCUS_TEXTURE_INDEX)
        candidate_g1t_sha = sha256_bytes(candidate_g1t)
        target_g1t.write_bytes(candidate_g1t)
        gust_g1t = project_root / ".local/vendor/gust_tools/gust_g1t"
        gust_status, gust_count = stage156.gust_list(gust_g1t, target_g1t)
        require(gust_status in {"ok", "not_available"}, f"gust_g1t validation failed: {gust_status}")
        if gust_status == "ok":
            require(gust_count == parsed_target["texture_count"], f"gust_g1t texture count mismatch: {gust_count}")

        stage_manifest = br._load_gust_pak_manifest(manifest_path)
        output_name = str(stage_manifest["safe_output_name"])
        progress("repacking local two-member PACK10_02 Fast Test profile")
        br._run_gust_pak(
            gust_pak=gust_pak, argument_name=manifest_path.name, cwd=baseline_extract,
            log_path=profile_root / "repack.log", timeout_seconds=timeout_seconds,
        )
        generated = baseline_extract / output_name
        require(generated.is_file(), "gust_pak did not produce PACK10_02 candidate")
        final_output = output_dir / "PACK10_02.PAK"
        os.replace(generated, final_output)
        output_sha = sha256_file(final_output)
        output_size = final_output.stat().st_size

        progress("freeing baseline extraction before full verification")
        shutil.rmtree(baseline_extract)
        progress("fully re-extracting profile PAK for byte-level verification")
        _verify_manifest_path, verify_manifest = br._extract_pak_for_repack_test(
            archive=final_output, destination=verify_extract, gust_pak=gust_pak,
            timeout_seconds=timeout_seconds, log_name="verify_extract.log",
        )
        verify_members = br._manifest_member_hashes(verify_extract, verify_manifest)
        verify_signature = br._gust_manifest_semantic_signature(verify_manifest)
        require(set(baseline_members) == set(verify_members), "PACK10_02 member set changed")
        changed_keys = sorted(k for k in baseline_members if baseline_members[k].get("sha256") != verify_members[k].get("sha256"))
        require(set(changed_keys) == {parent_key, g1t_key} and len(changed_keys) == 2, f"PACK10_02 changed unexpected members: {changed_keys[:8]}")
        require(verify_signature == baseline_signature, "PACK10_02 stable manifest semantics changed")
        diffs = br._gust_manifest_metadata_differences(baseline_manifest, verify_manifest, profile_id=PROFILE_ID, modified_member_keys={parent_key, g1t_key})
        require(not any(r.get("gate_effect") == "validation_gate" for r in diffs), "stable PACK10_02 manifest fields changed")

        verified_parent = verify_extract / Path(str(verify_members[parent_key]["name"]))
        require(sha256_file(verified_parent) == candidate_parent_sha, "repacked pc00_scl_w parent hash mismatch")
        stage70 = load_module(SCRIPT_DIR / "prepare_bathroom_river_parent_elixir_repack_test.py", "stage157_stage70_verify")
        decoded, _kind, _meta = stage70.decode_parent(verified_parent, stage147.MAX_PARENT_BYTES)
        p = br.parse_earc_payload(decoded, label="stage157-verify-parent", include_member_payloads=True)
        selected = {str(r["comparison_key"]): r for r in p.get("members", [])}.get(stage147.SELECTED_MEMBER_KEY)
        require(selected is not None and selected.get("sha256") == stage147.EXPECTED_SOURCE_MEMBER_SHA256, "repacked School_Wet G1M mismatch")

        verified_g1t = verify_extract / Path(str(verify_members[g1t_key]["name"]))
        require(sha256_file(verified_g1t) == candidate_g1t_sha, "repacked pc00_scl_w.g1t hash mismatch")
        verified_g1t_rows = verify_g1t_one_entry_change(stage155, stage156, target_g1t_bytes, verified_g1t.read_bytes(), FOCUS_TEXTURE_INDEX)
        require(all(bool(r["verified"]) for r in verified_g1t_rows), "repacked G1T entry verification failed")

        progress("rechecking installed PACK10_02 remained byte-identical")
        require(sha256_file(baseline_archive) == baseline_sha and baseline_archive.stat().st_size == baseline_size, "installed PACK10_02 changed during local build")

        pak_rows: list[dict[str, Any]] = []
        for key in sorted(baseline_members, key=str.casefold):
            left = baseline_members[key]; right = verify_members[key]
            selected_kind = "pc00_scl_w_parent" if key == parent_key else ("pc00_scl_w_g1t" if key == g1t_key else "")
            expected = candidate_parent_sha if key == parent_key else (candidate_g1t_sha if key == g1t_key else left.get("sha256"))
            pak_rows.append({
                "member_key": key, "member_name": left.get("name", ""), "selected_kind": selected_kind,
                "baseline_size": left.get("size", ""), "profile_size": right.get("size", ""),
                "baseline_sha256": left.get("sha256", ""), "profile_sha256": right.get("sha256", ""),
                "verified": right.get("sha256") == expected,
            })
        require(all(bool(r["verified"]) for r in pak_rows), "PACK10_02 per-member verification failed")

        manifest_root.mkdir(parents=True, exist_ok=True)
        local_profile_path = final_output.relative_to(project_root).as_posix()
        profile_manifest = {
            "schema_version": 1,
            "profile_id": PROFILE_ID,
            "target_relative_path": TARGET_RELATIVE_PATH,
            "baseline_sha256": baseline_sha,
            "baseline_size": baseline_size,
            "profile_sha256": output_sha,
            "profile_size": output_size,
            "local_profile_path": local_profile_path,
            "changed_member_count": 2,
            "changed_members": [str(parent_row["name"]).replace("\\", "/"), str(g1t_row["name"]).replace("\\", "/")],
            "retained_runtime_stable_component": stage147.SELECTED_MEMBER_NAME,
            "retained_runtime_stable_component_sha256": stage147.EXPECTED_SOURCE_MEMBER_SHA256,
            "wet_texture_entry_index": FOCUS_TEXTURE_INDEX,
            "wet_texture_source_raw_entry_sha256": EXPECTED_SOURCE_ENTRY23_RAW_SHA256,
            "wet_texture_target_placeholder_raw_entry_sha256": EXPECTED_TARGET_ENTRY23_RAW_SHA256,
            "runtime_validated": False,
            "production_eligible": False,
            "normal_composer_eligible": False,
            "fast_test_only": True,
            "candidate_semantics": "wet_school_entry23_runtime_probe_semantics_unconfirmed",
            "wet_transparency_semantics_confirmed": False,
            "wet_skin_droplet_semantics_confirmed": False,
            "workstream_id": "quartet_restoration",
            "workstream_version": TOOL_VERSION,
        }
        manifest_path_out = manifest_root / f"{PROFILE_ID}.json"
        atomic_json(manifest_path_out, profile_manifest)
        atomic_json(profile_root / "PROFILE.json", profile_manifest)
        atomic_json(marker, {"type": "br_quartet_restoration_wet_school_entry23_fast_test_profile_workspace", "format_version": 1, "profile_id": PROFILE_ID, "status": "ready", "profile_sha256": output_sha})

        validations = {
            "exact_pack10_02_baseline_precondition": baseline_sha == EXPECTED_BASELINE_SHA256,
            "school_wet_component_exact": sha256_bytes(source_school_wet_member) == stage147.EXPECTED_SOURCE_MEMBER_SHA256,
            "entry23_source_exact": sha256_bytes(source_entry23_raw) == EXPECTED_SOURCE_ENTRY23_RAW_SHA256,
            "exactly_one_inner_elixir_member_changed": sum(r["target_sha256"] != r["candidate_sha256"] for r in parent_rows) == 1,
            "exactly_one_g1t_entry_changed": sum(bool(r["changed"]) for r in g1t_rows) == 1,
            "exactly_two_pack_members_changed": len(changed_keys) == 2 and set(changed_keys) == {parent_key, g1t_key},
            "all_other_pack_members_preserved": all(bool(r["verified"]) for r in pak_rows),
            "pack_manifest_semantics_preserved": verify_signature == baseline_signature,
            "installed_game_unchanged": sha256_file(baseline_archive) == baseline_sha,
            "profile_runtime_unvalidated": profile_manifest["runtime_validated"] is False,
            "profile_nonproduction": profile_manifest["production_eligible"] is False,
            "semantics_unconfirmed": profile_manifest["wet_transparency_semantics_confirmed"] is False and profile_manifest["wet_skin_droplet_semantics_confirmed"] is False,
        }
        require(all(validations.values()), "stage-157 profile validation failed")
        validation_rows = [{"check_name": k, "passed": v} for k, v in validations.items()]
        profile = {
            **profile_manifest,
            "candidate_parent_sha256": candidate_parent_sha,
            "candidate_parent_size": len(candidate_parent),
            "candidate_g1t_sha256": candidate_g1t_sha,
            "candidate_g1t_size": len(candidate_g1t),
            "gust_g1t_status": gust_status,
            "gust_g1t_texture_rows": gust_count,
            "pak_member_count": len(pak_rows),
            "manifest_relative_path": manifest_path_out.relative_to(project_root).as_posix(),
        }
        return profile, parent_rows, g1t_rows, pak_rows, validation_rows
    finally:
        shutil.rmtree(baseline_extract, ignore_errors=True)
        shutil.rmtree(verify_extract, ignore_errors=True)

def build_report(
    project_root: Path,
    *,
    quartet_root: Path,
    original_root: Path,
    gust_pak: Path,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    workspace_root: Path | None = None,
    extraction_workspace_root: Path | None = None,
    manifest_root: Path | None = None,
    baseline_archive: Path | None = None,
    timeout_seconds: int = 7200,
    validate_evidence: bool = True,
    create_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    version = (project_root / "workstreams/quartet_restoration/VERSION").read_text(encoding="utf-8").strip()
    require(tuple(map(int, version.split("."))) >= tuple(map(int, TOOL_VERSION.split("."))), f"expected quartet_restoration {TOOL_VERSION} or newer, found {version}")
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    workspace_root = (workspace_root or project_root / ".local/build/quartet_restoration").resolve()
    extraction_workspace_root = (extraction_workspace_root or project_root / ".local/workspaces/quartet_restoration/hinako_wet_texture_entry_differential").resolve()
    manifest_root = (manifest_root or workspace_root / MANIFEST_SUBDIR).resolve()
    output = output_report_root / REPORT_DIR
    archive = output_report_root / REPORT_NAME
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    prereq = extract_stage156(report_root) if validate_evidence else {"tool_version": "synthetic", "focus_local_target_native_g1t_rebuild_feasible": True}
    stage147 = load_module(SCRIPT_DIR / "147_prepare_hinako_wet_school_uniform_fast_test_profile.py", "stage157_stage147_inputs")
    progress("resolving exact Original School_Wet G1M")
    source_parent = stage147.resolve_source_parent(project_root, original_root, gust_pak, timeout_seconds)
    source_school_wet = stage147.source_school_wet_member(project_root, source_parent)
    progress("resolving exact Original scl_w G1T entry 23")
    _source_g1t, source_entry23_raw = resolve_source_g1t(project_root, original_root, quartet_root, gust_pak, extraction_workspace_root, timeout_seconds)
    baseline = baseline_archive.resolve() if baseline_archive else quartet_root.resolve() / TARGET_RELATIVE_PATH

    profile, parent_rows, g1t_rows, pak_rows, validation_rows = build_profile_from_inputs(
        project_root,
        baseline_archive=baseline,
        source_school_wet_member=source_school_wet,
        source_entry23_raw=source_entry23_raw,
        gust_pak=gust_pak.resolve(),
        workspace_root=workspace_root,
        manifest_root=manifest_root,
        timeout_seconds=timeout_seconds,
    )
    write_tsv(output / "PROFILE.tsv", list(profile), [profile])
    write_tsv(output / "PC00_SCL_W_PARENT_MEMBER_VERIFICATION.tsv", list(parent_rows[0]), parent_rows)
    write_tsv(output / "PC00_SCL_W_G1T_ENTRY_VERIFICATION.tsv", list(g1t_rows[0]), g1t_rows)
    write_tsv(output / "PACK10_02_MEMBER_VERIFICATION.tsv", list(pak_rows[0]), pak_rows)
    write_tsv(output / "VALIDATIONS.tsv", ["check_name", "passed"], validation_rows)
    summary = {
        "type": "br_quartet_restoration_hinako_wet_school_entry23_fast_test_profile_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "two_member_local_pack10_02_fast_test_profile_built_school_wet_plus_target_native_entry23_fully_reextracted_not_installed_runtime_unvalidated",
        "stage156_evidence_sha256": STAGE156_SHA256 if validate_evidence else "synthetic",
        "stage147_profile_evidence_sha256": STAGE147_REPORT_SHA256,
        "stage148_activation_evidence_sha256": STAGE148_ACTIVATION_SHA256,
        "stage148_rollback_evidence_sha256": STAGE148_ROLLBACK_SHA256,
        "profile_id": PROFILE_ID,
        "baseline_sha256": profile["baseline_sha256"],
        "baseline_size": profile["baseline_size"],
        "profile_sha256": profile["profile_sha256"],
        "profile_size": profile["profile_size"],
        "pak_changed_member_rows": sum(r["baseline_sha256"] != r["profile_sha256"] for r in pak_rows),
        "parent_changed_member_rows": sum(r["target_sha256"] != r["candidate_sha256"] for r in parent_rows),
        "g1t_changed_texture_entry_rows": sum(bool(r["changed"]) for r in g1t_rows),
        "g1t_focus_texture_index": FOCUS_TEXTURE_INDEX,
        "g1t_focus_source_raw_entry_sha256": EXPECTED_SOURCE_ENTRY23_RAW_SHA256,
        "g1t_focus_target_placeholder_raw_entry_sha256": EXPECTED_TARGET_ENTRY23_RAW_SHA256,
        "retained_school_wet_component": "PC00_Scl_W_P_School_Wet.g1m",
        "retained_school_wet_component_runtime_stable": True,
        "runtime_validated": False,
        "production_eligible": False,
        "fast_test_only": True,
        "wet_transparency_semantics_confirmed": False,
        "wet_skin_droplet_semantics_confirmed": False,
        "validation_rows": len(validation_rows),
        "validation_failures": sum(not bool(r["passed"]) for r in validation_rows),
        "policy": {
            "stage156_missing_wet_transition_is_grounded": True,
            "entry23_semantics_remain_unconfirmed": True,
            "whole_g1t_transplant_used": False,
            "only_one_g1t_entry_replaced": True,
            "whole_g1mm_g1mg_transplant_reuse_forbidden": True,
            "previously_runtime_stable_school_wet_component_retained": True,
            "profile_built_only_under_local_workspace": True,
            "profile_fully_reextracted": True,
            "installed_game_modified": False,
            "runtime_activation_performed": False,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "glowlight_activated": False,
            "proprietary_payloads_in_evidence": False,
        },
        "next_action": "Upload this metadata-only profile evidence. If it confirms exactly two changed PACK10_02 members, exactly one changed pc00_scl_w Elixir member, exactly one changed pc00_scl_w.g1t entry (23), full re-extract verification and exact baseline preservation, prepare a separately authorized isolated runtime activation with exact rollback. Evaluate model integrity, canonical collar shape, wet-shirt transparency and wet-skin/droplet appearance independently.",
    }
    atomic_json(output / "SUMMARY.json", summary)
    require(not [p for p in output.rglob("*") if p.is_file() and p.name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS)], "proprietary payload extension in evidence")
    progress("metadata-only profile evidence assembled; installed game remains unchanged")
    if create_archive:
        make_archive(output, archive)
        return archive, summary
    return None, summary

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    p.add_argument("--quartet-root", type=Path, default=Path(os.environ["BR1_QUARTET_ROOT"]) if os.environ.get("BR1_QUARTET_ROOT") else None)
    p.add_argument("--original-root", type=Path, default=Path(os.environ["BR1_ORIGINAL_ROOT"]) if os.environ.get("BR1_ORIGINAL_ROOT") else None)
    p.add_argument("--gust-pak", type=Path)
    p.add_argument("--timeout-seconds", type=int, default=7200)
    return p.parse_args(argv)

def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    project_root = a.project_root.expanduser().resolve()
    require(a.quartet_root is not None, "Quartet root required via --quartet-root or BR1_QUARTET_ROOT")
    require(a.original_root is not None, "Original root required via --original-root or BR1_ORIGINAL_ROOT")
    gust = (a.gust_pak or project_root / ".local/vendor/gust_tools/gust_pak").expanduser().resolve()
    arc, summary = build_report(
        project_root,
        quartet_root=a.quartet_root.expanduser().resolve(),
        original_root=a.original_root.expanduser().resolve(),
        gust_pak=gust,
        timeout_seconds=a.timeout_seconds,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if arc:
        print(f"[stage157] report archive: {arc}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage157Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
