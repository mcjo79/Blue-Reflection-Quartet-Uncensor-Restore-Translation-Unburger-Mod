#!/usr/bin/env python3
"""Build a local, fail-closed dry-BKN composition preflight.

The stage closes the rejected UI numeric-index route, validates the existing
asset-only PACK10_02 candidate, selectively verifies Quartet's installed
PACK12 charabase member, and creates a byte-preserving local charabase
candidate that changes only PC00_DLC_BKN Model/defaultTexture.

No PAK is repacked by this stage and nothing is installed.  Raw table bytes are
kept only under .local/build; the evidence bundle is metadata-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
for item in (SCRIPT_DIR, PROJECT_ROOT_DEFAULT / "Blue_Reflection_Text_Tool"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import br_dlc_bkn_activation_ui_tool as ACTIVATION  # noqa: E402
import br_dlc_bkn_ui_control_schema_tool as UI_SCHEMA  # noqa: E402
import br_dlc_dry_pak_insertion_tool as DRY  # noqa: E402
import br_dlc_nested_container_tool as NESTED  # noqa: E402

TOOL_VERSION = "0.0.20"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "bkn_dry_composition_preflight_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_bkn_dry_composition_preflight_evidence.tar.zst"
BUILD_RELATIVE = Path(".local/build/quartet_legacy_dlc/composition_preflight/costume_pc00_bkn_dry")
DRY_PAK_RELATIVE = Path(".local/build/quartet_legacy_dlc/pak_insertion_tests/costume_pc00_bkn_dry/candidate/PACK10_02.PAK")
TARGET_ARCHIVE_RELATIVE = Path("Data/PACK12.PAK")
TARGET_MEMBER = "saves/b1/chara/charabase.xml"
WORKSPACE_TABLE_RELATIVE = Path("titles/blue_reflection/workspace/quartet/archives/PACK12/saves/b1/chara/charabase.xml")
DRY_TAG = "PC00_DLC_BKN"
WET_TAG = "PC00_DLC_BKN_W"
FORBIDDEN_REPORT_SUFFIXES = {
    ".pak", ".xml", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s",
    ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg", ".kscl", ".kslt",
}


class BknDryCompositionPreflightError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: scalar(row.get(field, "")) for field in fields})


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise BknDryCompositionPreflightError(f"missing TSV: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_composition_bundle_") as temp_name:
        temp_tar = Path(temp_name) / "report.tar"
        with tarfile.open(temp_tar, "w", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(source.rglob("*"), key=lambda p: p.relative_to(source).as_posix().casefold()):
                if not path.is_file():
                    continue
                info = archive.gettarinfo(str(path), arcname=f"{source.name}/{path.relative_to(source).as_posix()}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        subprocess.run(["zstd", "-q", "-f", "-19", str(temp_tar), "-o", str(output)], check=True)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix().casefold()):
        if not path.is_file() or path.name == "REPORT_MANIFEST.json":
            continue
        if any(suffix.casefold() in FORBIDDEN_REPORT_SUFFIXES for suffix in path.suffixes):
            raise BknDryCompositionPreflightError(f"raw asset-like file in report: {path}")
        rows.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
    return rows


def locate_report(project_root: Path, directory: str, archive_name: str, temporary: Path) -> Path:
    parent = project_root / ".local/reports/quartet_legacy_dlc"
    direct = parent / directory
    if direct.is_dir():
        return direct
    packed = parent / archive_name
    if not packed.is_file():
        raise BknDryCompositionPreflightError(f"missing prerequisite report: {direct} / {packed}")
    extract_root = temporary / directory
    extract_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "--zstd", "-xf", str(packed), "-C", str(extract_root)], check=True)
    expected = extract_root / directory
    if expected.is_dir():
        return expected
    candidates = [p for p in extract_root.iterdir() if p.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    raise BknDryCompositionPreflightError(f"could not locate extracted report: {packed}")


def validate_prerequisites(project_root: Path, temporary: Path) -> dict[str, Any]:
    dry_root = locate_report(project_root, DRY.REPORT_DIR_NAME, DRY.REPORT_ARCHIVE_NAME, temporary)
    activation_root = locate_report(project_root, ACTIVATION.REPORT_DIR_NAME, ACTIVATION.REPORT_ARCHIVE_NAME, temporary)
    ui_root = locate_report(project_root, UI_SCHEMA.REPORT_DIR_NAME, UI_SCHEMA.REPORT_ARCHIVE_NAME, temporary)
    dry = DRY.validate_report(dry_root)
    activation = ACTIVATION.validate_report(activation_root)
    ui = UI_SCHEMA.validate_report(ui_root)
    if dry.get("status") != "local_asset_only_pack10_02_candidate_built_not_installed":
        raise BknDryCompositionPreflightError("unexpected stage-28 status")
    if activation.get("status") != "bkn_table_stub_proven_activation_and_ui_still_fail_closed":
        raise BknDryCompositionPreflightError("unexpected stage-31 status")
    if ui.get("status") != "bkn_ui_numeric_index_route_not_supported_by_local_schema":
        raise BknDryCompositionPreflightError("stage-46 UI route is not formally closed")
    if int(ui.get("schema_supported_control_candidates", -1)) != 0:
        raise BknDryCompositionPreflightError("schema-supported UI candidate unexpectedly survives")
    candidate_json = json.loads((activation_root / "DLC_BKN_CHARABASE_PATCH_CANDIDATES.json").read_text(encoding="utf-8"))
    dry_candidates = [row for row in candidate_json.get("candidates", []) if row.get("record_key") == "CharaBase:BaseTag=PC00_DLC_BKN"]
    if len(dry_candidates) != 1:
        raise BknDryCompositionPreflightError("expected exactly one dry charabase patch candidate")
    return {"dry": dry, "activation": activation, "ui": ui, "patch": dry_candidates[0]}


def decode_xml_bytes(raw: bytes) -> tuple[str, str]:
    for encoding in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise BknDryCompositionPreflightError("could not decode charabase XML")


def record_attrs(raw: bytes, tag: str) -> dict[str, str]:
    text, _encoding = decode_xml_bytes(raw)
    pattern = re.compile(r"<CharaBase\b[^>]*\bBaseTag=\"" + re.escape(tag) + r"\"[^>]*/>")
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise BknDryCompositionPreflightError(f"expected exactly one {tag} record, found {len(matches)}")
    return {key: value for key, value in re.findall(r"([A-Za-z0-9_]+)=\"([^\"]*)\"", matches[0])}


def patch_dry_record(raw: bytes, expected_old: Mapping[str, str], new_values: Mapping[str, str]) -> tuple[bytes, dict[str, Any]]:
    text, encoding = decode_xml_bytes(raw)
    pattern = re.compile(r"(<CharaBase\b[^>]*\bBaseTag=\"" + re.escape(DRY_TAG) + r"\"[^>]*/>)")
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise BknDryCompositionPreflightError(f"expected exactly one {DRY_TAG} record")
    before_record = matches[0].group(1)
    after_record = before_record
    for field in ("Model", "defaultTexture"):
        old = str(expected_old.get(field, ""))
        new = str(new_values.get(field, ""))
        attr_pattern = re.compile(r"(" + re.escape(field) + r"=\")" + re.escape(old) + r"(\")")
        after_record, count = attr_pattern.subn(lambda m, n=new: m.group(1) + n + m.group(2), after_record, count=1)
        if count != 1:
            raise BknDryCompositionPreflightError(f"expected exact old {field} value {old!r}")
    after_text = text[:matches[0].start()] + after_record + text[matches[0].end():]
    try:
        output = after_text.encode(encoding)
    except UnicodeEncodeError as exc:
        raise BknDryCompositionPreflightError(f"failed to re-encode charabase as {encoding}") from exc
    before_attrs = record_attrs(raw, DRY_TAG)
    after_attrs = record_attrs(output, DRY_TAG)
    wet_before = record_attrs(raw, WET_TAG)
    wet_after = record_attrs(output, WET_TAG)
    changed = {key: (before_attrs.get(key, ""), after_attrs.get(key, "")) for key in set(before_attrs) | set(after_attrs) if before_attrs.get(key) != after_attrs.get(key)}
    if set(changed) != {"Model", "defaultTexture"}:
        raise BknDryCompositionPreflightError(f"unexpected dry-record fields changed: {sorted(changed)}")
    if wet_before != wet_after:
        raise BknDryCompositionPreflightError("wet BKN record changed during dry-only patch")
    # Remove the one expected record from both texts; all remaining bytes must match.
    before_without = text[:matches[0].start()] + text[matches[0].end():]
    after_match = pattern.search(after_text)
    assert after_match is not None
    after_without = after_text[:after_match.start()] + after_text[after_match.end():]
    if before_without != after_without:
        raise BknDryCompositionPreflightError("bytes outside the dry BKN record changed")
    return output, {"before_attrs": before_attrs, "after_attrs": after_attrs, "changed": changed, "wet_unchanged": True, "encoding": encoding}


def audit(project_root: Path, quartet_root: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    print("[stage49] validating prerequisite reports and closed UI route", flush=True)
    with tempfile.TemporaryDirectory(prefix="br_dlc_bkn_comp_prereq_") as temp_name:
        prereq = validate_prerequisites(project_root, Path(temp_name))

    dry_pak = project_root / DRY_PAK_RELATIVE
    if not dry_pak.is_file():
        raise BknDryCompositionPreflightError(f"missing local dry PACK10_02 candidate; rerun stage 28: {dry_pak}")
    dry_pak_sha = sha256_file(dry_pak)
    if dry_pak_sha != prereq["dry"].get("candidate_sha256"):
        raise BknDryCompositionPreflightError("local dry PACK10_02 candidate hash differs from stage-28 evidence")

    workspace_table = project_root / WORKSPACE_TABLE_RELATIVE
    if not workspace_table.is_file():
        raise BknDryCompositionPreflightError(f"missing Quartet charabase workspace table: {workspace_table}")
    workspace_raw = workspace_table.read_bytes()

    installed_pack12 = quartet_root / TARGET_ARCHIVE_RELATIVE
    print("[stage49] selectively verifying installed PACK12 charabase member", flush=True)
    index = NESTED.index_pak(installed_pack12)
    installed_raw, entry = NESTED.read_pak_member(index, TARGET_MEMBER)
    if installed_raw != workspace_raw:
        raise BknDryCompositionPreflightError(
            "installed PACK12 charabase member differs from the canonical Quartet workspace; refresh extraction or composition baseline"
        )

    patch = prereq["patch"]
    candidate_raw, detail = patch_dry_record(workspace_raw, patch["expected_old_values"], patch["new_values"])
    build_root = project_root / BUILD_RELATIVE
    clean_dir(build_root)
    source_path = build_root / "source_exact" / TARGET_MEMBER
    candidate_path = build_root / "candidate" / TARGET_MEMBER
    source_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(workspace_raw)
    candidate_path.write_bytes(candidate_raw)

    plan = {
        "type": "br_quartet_legacy_dlc_bkn_dry_local_composition_plan",
        "format_version": 1,
        "content_id": "costume_pc00_bkn",
        "status": "preflight_ready_not_built_not_installed",
        "inputs": [
            {"archive": "Data/PACK10_02.PAK", "local_candidate": dry_pak.relative_to(project_root).as_posix(), "sha256": dry_pak_sha, "role": "dry_assets"},
            {"archive": "Data/PACK12.PAK", "member": TARGET_MEMBER, "local_candidate": candidate_path.relative_to(project_root).as_posix(), "sha256": sha256_bytes(candidate_raw), "role": "dry_charabase_redirect"},
        ],
        "charabase_change": {"BaseTag": DRY_TAG, "fields": {field: {"old": old, "new": new} for field, (old, new) in detail["changed"].items()}},
        "preserve_all_other_target_attributes": True,
        "wet_variant_included": False,
        "next_action": "build a local PACK12 replace-member candidate from the current installed archive and verify every non-target entry; then record a two-archive local composition without installing it",
        "policy": {
            "local_pack12_repack_test_allowed": True,
            "local_two_archive_composition_build_allowed": True,
            "profile_build_allowed": False,
            "candidate_installed": False,
            "runtime_validated": False,
            "game_modified": False,
            "translation_modified": False,
        },
    }
    write_json(build_root / "BKN_DRY_LOCAL_COMPOSITION_PLAN.json", plan)

    clean_dir(output_root)
    route_rows = [{
        "route": "selected_costume_ui_numeric_index_route",
        "stage46_status": prereq["ui"].get("status"),
        "schema_supported_candidates": prereq["ui"].get("schema_supported_control_candidates"),
        "closure": "closed_not_supported_by_selected_ui_schema",
        "used_for_composition": False,
    }]
    write_tsv(output_root / "DLC_BKN_UI_ROUTE_CLOSURE.tsv", list(route_rows[0]), route_rows)
    patch_rows = []
    for field, (old, new) in sorted(detail["changed"].items()):
        patch_rows.append({
            "archive": str(TARGET_ARCHIVE_RELATIVE).replace("\\", "/"), "member": TARGET_MEMBER,
            "record_key": f"CharaBase:BaseTag={DRY_TAG}", "field": field,
            "expected_old_value": old, "new_value": new, "preserve_other_attributes": True,
            "candidate_table_sha256": sha256_bytes(candidate_raw), "table_modified_in_game": False,
        })
    write_tsv(output_root / "DLC_BKN_DRY_CHARABASE_PATCH.tsv", list(patch_rows[0]), patch_rows)
    validation_rows = [{
        "source_table_size": len(workspace_raw), "source_table_sha256": sha256_bytes(workspace_raw),
        "candidate_table_size": len(candidate_raw), "candidate_table_sha256": sha256_bytes(candidate_raw),
        "installed_member_size": len(installed_raw), "installed_member_sha256": sha256_bytes(installed_raw),
        "installed_workspace_member_identical": True, "changed_fields": sorted(detail["changed"]),
        "wet_record_unchanged": detail["wet_unchanged"], "outside_dry_record_unchanged": True,
        "encoding": detail["encoding"], "validation_status": "passed",
    }]
    write_tsv(output_root / "DLC_BKN_DRY_CHARABASE_RECORD_VALIDATION.tsv", list(validation_rows[0]), validation_rows)
    input_rows = [
        {"role": "dry_asset_archive", "archive": "Data/PACK10_02.PAK", "path": dry_pak.relative_to(project_root).as_posix(), "size": dry_pak.stat().st_size, "sha256": dry_pak_sha, "state": "local_candidate_uninstalled"},
        {"role": "dry_table_member", "archive": "Data/PACK12.PAK", "path": candidate_path.relative_to(project_root).as_posix(), "size": candidate_path.stat().st_size, "sha256": sha256_file(candidate_path), "state": "local_member_candidate_not_repacked"},
        {"role": "installed_pack12_baseline", "archive": "Data/PACK12.PAK", "path": str(TARGET_ARCHIVE_RELATIVE).replace("\\", "/"), "size": installed_pack12.stat().st_size, "sha256": sha256_file(installed_pack12), "state": "read_only_unchanged"},
    ]
    write_tsv(output_root / "DLC_BKN_DRY_COMPOSITION_INPUTS.tsv", list(input_rows[0]), input_rows)
    gaps = [
        {"dependency": "pack12_replace_member_repack", "status": "not_built", "blocks_installation": True, "next_evidence": "build and independently verify a local PACK12 candidate changing exactly charabase.xml"},
        {"dependency": "owner_ui_icon_or_thumbnail", "status": "unresolved", "blocks_installation": True, "next_evidence": "runtime or format-proven owner binding; isolated UI integers are closed"},
        {"dependency": "wet_variant_conversion", "status": "conversion_blocked", "blocks_installation": True, "next_evidence": "complete G1M/SWG conversion and exact texture binding"},
        {"dependency": "runtime_availability_and_validation", "status": "not_performed", "blocks_installation": True, "next_evidence": "only after a complete local two-archive composition is transactionally prepared and explicitly approved"},
    ]
    write_tsv(output_root / "DLC_BKN_DRY_COMPOSITION_GAPS.tsv", list(gaps[0]), gaps)
    report_plan = {**plan, "inputs": [{k: v for k, v in row.items() if k != "path"} for row in input_rows]}
    write_json(output_root / "DLC_BKN_DRY_COMPOSITION_PLAN.json", report_plan)

    summary = {
        "type": "br_quartet_legacy_dlc_bkn_dry_composition_preflight_summary",
        "format_version": FORMAT_VERSION,
        "tool_version": TOOL_VERSION,
        "status": "local_dry_bkn_composition_preflight_ready_not_built_not_installed",
        "content_id": "costume_pc00_bkn",
        "ui_numeric_route_closed": True,
        "schema_supported_ui_candidates": 0,
        "dry_pack10_02_candidate_sha256": dry_pak_sha,
        "installed_pack12_format": index.format_name,
        "installed_pack12_master_key": index.master_key_label,
        "installed_pack12_entry_count": len(index.entries),
        "installed_charabase_entry_index": entry.index,
        "installed_charabase_sha256": sha256_bytes(installed_raw),
        "candidate_charabase_sha256": sha256_bytes(candidate_raw),
        "candidate_charabase_changed_fields": sorted(detail["changed"]),
        "wet_record_unchanged": True,
        "local_build_root": build_root.relative_to(project_root).as_posix(),
        "unresolved_installation_blockers": len(gaps),
        "next_action": plan["next_action"],
        "policy": {
            "game_modified": False, "git_modified": False, "translation_modified": False,
            "system_table_modified_in_game": False, "target_pak_repacked": False,
            "local_raw_table_candidate_created": True, "raw_table_exported_in_report": False,
            "local_pack12_repack_test_allowed": True, "local_two_archive_composition_build_allowed": True,
            "profile_build_allowed": False, "profile_registered": False, "candidate_installed": False,
            "runtime_validated": False, "wet_variant_included": False,
        },
        "findings": [
            "the selected UI numeric-index route is formally closed by stage 46",
            "the existing dry asset-only PACK10_02 candidate remains hash-identical and uninstalled",
            "the installed PACK12 charabase member matches the canonical Quartet workspace exactly",
            "the local charabase candidate changes only Model/defaultTexture on PC00_DLC_BKN and preserves all Quartet-only attributes",
            "PC00_DLC_BKN_W is unchanged and remains conversion-blocked",
            "this stage authorizes only a future local PACK12 repack test, not a profile or installation",
        ],
    }
    write_json(output_root / "SUMMARY.json", summary)
    write_json(output_root / "REPORT_MANIFEST.json", {"type": "br_report_manifest", "format_version": 1, "files": report_manifest(output_root)})
    archive = output_root.parent / REPORT_ARCHIVE_NAME
    make_archive(output_root, archive)
    print(f"[stage49] local preflight: {build_root}", flush=True)
    print(f"[stage49] report: {archive}", flush=True)
    return archive, summary


def validate_report(report_root: Path) -> dict[str, Any]:
    required = (
        "DLC_BKN_UI_ROUTE_CLOSURE.tsv", "DLC_BKN_DRY_CHARABASE_PATCH.tsv",
        "DLC_BKN_DRY_CHARABASE_RECORD_VALIDATION.tsv", "DLC_BKN_DRY_COMPOSITION_INPUTS.tsv",
        "DLC_BKN_DRY_COMPOSITION_GAPS.tsv", "DLC_BKN_DRY_COMPOSITION_PLAN.json",
        "SUMMARY.json", "REPORT_MANIFEST.json",
    )
    for name in required:
        if not (report_root / name).is_file():
            raise BknDryCompositionPreflightError(f"missing report file: {name}")
    summary = json.loads((report_root / "SUMMARY.json").read_text(encoding="utf-8"))
    if summary.get("status") != "local_dry_bkn_composition_preflight_ready_not_built_not_installed":
        raise BknDryCompositionPreflightError("unexpected composition preflight status")
    policy = summary.get("policy", {})
    forbidden_true = ("game_modified", "translation_modified", "system_table_modified_in_game", "target_pak_repacked", "profile_build_allowed", "profile_registered", "candidate_installed", "runtime_validated", "wet_variant_included", "raw_table_exported_in_report")
    if any(policy.get(key) is True for key in forbidden_true):
        raise BknDryCompositionPreflightError("report violates fail-closed policy")
    if policy.get("local_pack12_repack_test_allowed") is not True:
        raise BknDryCompositionPreflightError("local PACK12 repack test was not explicitly gated")
    patches = read_tsv(report_root / "DLC_BKN_DRY_CHARABASE_PATCH.tsv")
    if len(patches) != 2 or {row["field"] for row in patches} != {"Model", "defaultTexture"}:
        raise BknDryCompositionPreflightError("unexpected charabase patch field set")
    validations = read_tsv(report_root / "DLC_BKN_DRY_CHARABASE_RECORD_VALIDATION.tsv")
    if len(validations) != 1 or validations[0].get("validation_status") != "passed":
        raise BknDryCompositionPreflightError("charabase record validation failed")
    if validations[0].get("wet_record_unchanged") != "true" or validations[0].get("outside_dry_record_unchanged") != "true":
        raise BknDryCompositionPreflightError("dry-only preservation gates failed")
    gaps = read_tsv(report_root / "DLC_BKN_DRY_COMPOSITION_GAPS.tsv")
    if len(gaps) != 4 or any(row.get("blocks_installation") != "true" for row in gaps):
        raise BknDryCompositionPreflightError("installation blockers were weakened")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    audit_cmd = sub.add_parser("audit")
    audit_cmd.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    audit_cmd.add_argument("--quartet-root", type=Path, required=True)
    audit_cmd.add_argument("--output-root", type=Path)
    validate_cmd = sub.add_parser("validate-report")
    validate_cmd.add_argument("--report-root", type=Path, required=True)
    bundle_cmd = sub.add_parser("bundle-report")
    bundle_cmd.add_argument("--report-root", type=Path, required=True)
    bundle_cmd.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "audit":
        project_root = args.project_root.expanduser().resolve()
        output = args.output_root or project_root / ".local/reports/quartet_legacy_dlc" / REPORT_DIR_NAME
        audit(project_root, args.quartet_root.expanduser().resolve(), output.resolve())
    elif args.command == "validate-report":
        summary = validate_report(args.report_root.expanduser().resolve())
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        root = args.report_root.expanduser().resolve()
        validate_report(root)
        make_archive(root, args.output.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
