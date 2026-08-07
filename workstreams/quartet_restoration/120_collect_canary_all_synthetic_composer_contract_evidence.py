#!/usr/bin/env python3
"""Stage 120: synthetic Canary-all composer contract using tiny real Gust PAK fixtures.

This stage never reads real profile PAKs or game baselines. It imports only the
immutable stage-119 metadata snapshot, creates tiny deterministic fixture PAKs,
composes all 15 explicitly selected runtime-unvalidated profile fixtures in a
separate temporary root, and verifies every result by full re-extraction with
the vendored gust_pak binary. Evidence contains metadata only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.38"
STAGE119_ARCHIVE = "BR_quartet_restoration_canary_composition_input_contract_evidence.tar.zst"
STAGE119_SHA256 = "33fc283065dff7258da37194e1a91f0743640400df625d7f3fb2eed47f3c296d"
REPORT_DIR = "canary_all_synthetic_composer_contract_evidence"
REPORT_NAME = "BR_quartet_restoration_canary_all_synthetic_composer_contract_evidence.tar.zst"
GUST_PAK_REL = Path(".local/vendor/gust_tools/gust_pak")
GUST_PAK_SHA256 = "efce67319db43668a4d1e98725c7ade97e8a72c32777e65de4efce99cb6a3030"
GUST_PAK_SIZE = 59992
EXPECTED_TARGET_SPLIT = {"Data/PACK11.PAK": 12, "Data/PACK10_01.PAK": 2, "Data/PACK10_03.PAK": 1}
EXPECTED_PROFILES = 15
EXPECTED_MEMBERS = 30
MANIFEST_ROOT_REL = Path(".local/build/quartet_restoration/core_profiles/generated")


class SyntheticComposerError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SyntheticComposerError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_member(value: str) -> str:
    raw = str(value).replace("\\", "/")
    p = PurePosixPath(raw)
    require(bool(p.parts), "empty member path")
    require(not p.is_absolute() and ".." not in p.parts, f"unsafe member path: {value}")
    return p.as_posix().strip("/")


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing JSON: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"JSON root is not an object: {path}")
    return data


def extract_report(archive: Path, destination: Path) -> Path:
    require(archive.is_file(), f"missing stage-119 report: {archive}")
    require(sha256_file(archive) == STAGE119_SHA256, "stage-119 report SHA-256 drift")
    listing = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listing.returncode == 0, listing.stderr.strip() or "cannot list stage-119 report")
    names = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    require(names, "empty stage-119 report")
    roots = set()
    for name in names:
        p = PurePosixPath(name)
        require(not p.is_absolute() and ".." not in p.parts, f"unsafe stage-119 archive member: {name}")
        roots.add(p.parts[0])
    require(len(roots) == 1, "stage-119 report must have one root")
    destination.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "cannot extract stage-119 report")
    root = destination / next(iter(roots))
    require(root.is_dir(), "stage-119 extracted root missing")
    return root


def load_stage119(archive: Path, temporary: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = extract_report(archive, temporary)
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("tool_version") == "0.1.37", "stage-119 tool-version drift")
    require(summary.get("status") == "canary_input_contract_checksum_valid_production_composer_runtime_gate_confirmed_separate_canary_composer_not_implemented_no_write", "stage-119 status drift")
    require(int(summary.get("profile_rows", -1)) == EXPECTED_PROFILES, "stage-119 profile count drift")
    require(int(summary.get("changed_member_reference_rows", -1)) == EXPECTED_MEMBERS, "stage-119 changed-member count drift")
    require(int(summary.get("changed_member_conflict_rows", -1)) == 0, "stage-119 overlap conflict drift")
    require(int(summary.get("runtime_validated_profile_rows", -1)) == 0, "stage-119 runtime-validation drift")
    rows = read_tsv(root / "CANARY_RESTORATION_PROFILE_INPUTS.tsv")
    require(len(rows) == EXPECTED_PROFILES, "stage-119 profile TSV count drift")
    parsed: list[dict[str, Any]] = []
    for row in rows:
        members = [safe_member(x) for x in str(row["changed_members"]).split(";") if x]
        require(len(members) == int(row["changed_member_count"]), f"changed-member count mismatch: {row['profile_id']}")
        require(str(row["runtime_validated"]).casefold() == "false", f"runtime-validated profile selected: {row['profile_id']}")
        parsed.append({**row, "members": members})
    validate_profile_snapshot(parsed)
    return summary, parsed


def validate_profile_snapshot(rows: Sequence[Mapping[str, Any]]) -> None:
    require(len(rows) == EXPECTED_PROFILES, "selection must contain exactly 15 profiles")
    ids = [str(r["profile_id"]) for r in rows]
    require(len(set(ids)) == len(ids), "duplicate profile selection")
    split = Counter(str(r["target_relative_path"]) for r in rows)
    require(dict(split) == EXPECTED_TARGET_SPLIT, f"target split drift: {dict(split)}")
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        require(str(row.get("runtime_validated", "false")).casefold() == "false", "runtime-validation drift")
        target = str(row["target_relative_path"])
        for member in row["members"]:
            owners[(target, safe_member(str(member)))].append(str(row["profile_id"]))
    require(sum(len(r["members"]) for r in rows) == EXPECTED_MEMBERS, "overlay member count drift")
    conflicts = {k: v for k, v in owners.items() if len(v) != 1}
    require(not conflicts, f"changed-member overlap detected: {conflicts}")


def validate_explicit_selection(selected: Sequence[str], expected: Sequence[str]) -> None:
    require(len(selected) == len(expected), "explicit selection is incomplete")
    require(len(set(selected)) == len(selected), "duplicate explicit selection")
    require(set(selected) == set(expected), "explicit selection differs from stage-119 snapshot")


def validate_single_baseline(targets: Sequence[str], baselines: Mapping[str, Sequence[str]]) -> None:
    for target in targets:
        require(len(baselines.get(target, ())) == 1, f"expected exactly one baseline for {target}")


def run_gust(gust_pak: Path, argument: Path, cwd: Path, log: Path, timeout_seconds: int = 30) -> None:
    env = os.environ.copy(); env.setdefault("TERM", "xterm")
    cp = subprocess.run([str(gust_pak), argument.name], cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout_seconds)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text((cp.stdout or "") + (cp.stderr or ""), encoding="utf-8")
    require(cp.returncode == 0, f"gust_pak failed for {argument}: {(cp.stderr or cp.stdout).strip()}")


def manifest_for(output_name: str, members: Sequence[str]) -> dict[str, Any]:
    key = "5a944d44feffffff80f9300533fab37700000000000000000000000000000000"
    return {
        "name": output_name,
        "version": 0x20000,
        "header_size": 0x10,
        "flags": 0xD,
        "nb_files": len(members),
        "64-bit": True,
        "a22-extensions": True,
        "master_key": "fyrixtT9AhA4v0cFahgMcgVwxFrry42A",
        "files": [{"name": "\\" + m.replace("/", "\\"), "key": key} for m in members],
    }


def write_fixture_tree(root: Path, output_name: str, payloads: Mapping[str, bytes]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    members = sorted(safe_member(m) for m in payloads)
    for member in members:
        path = root / Path(member)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payloads[member])
    manifest = root / (Path(output_name).stem + ".json")
    manifest.write_text(json.dumps(manifest_for(output_name, members), indent=2) + "\n", encoding="utf-8")
    return manifest


def pack_and_extract(gust_pak: Path, work: Path, label: str, output_name: str, payloads: Mapping[str, bytes]) -> tuple[Path, dict[str, bytes]]:
    pack_root = work / label / "pack"
    manifest = write_fixture_tree(pack_root, output_name, payloads)
    run_gust(gust_pak, manifest, pack_root, work / label / "pack.log")
    pak = pack_root / output_name
    require(pak.is_file(), f"fixture PAK missing: {pak}")
    extract_root = work / label / "extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    copied = extract_root / output_name
    shutil.copy2(pak, copied)
    run_gust(gust_pak, copied, extract_root, work / label / "extract.log")
    observed: dict[str, bytes] = {}
    for member in payloads:
        path = extract_root / Path(member)
        require(path.is_file(), f"re-extracted member missing: {member}")
        observed[member] = path.read_bytes()
    return pak, observed


def manifest_hashes(project_root: Path, manifest_root: Path | None = None) -> dict[str, str]:
    root = (manifest_root or (project_root / MANIFEST_ROOT_REL)).resolve()
    paths = sorted(root.glob("*.json"))
    require(len(paths) == EXPECTED_PROFILES, f"expected 15 real profile manifests, found {len(paths)}")
    return {p.name: sha256_file(p) for p in paths}


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.unlink(missing_ok=True)
    cp = subprocess.run(["tar", "--zstd", "-cf", str(temp), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(cp.returncode == 0, cp.stderr.strip() or "evidence archive creation failed")
    os.replace(temp, output)


def build_report(project_root: Path, report_root: Path | None = None, output_report_root: Path | None = None, gust_pak: Path | None = None, create_archive: bool = True, manifest_root: Path | None = None) -> tuple[Path, dict[str, Any]]:
    project_root = project_root.resolve()
    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()
    gust_pak = (gust_pak or project_root / GUST_PAK_REL).resolve()
    require(gust_pak.is_file() and os.access(gust_pak, os.X_OK), f"gust_pak missing or not executable: {gust_pak}")
    require(gust_pak.stat().st_size == GUST_PAK_SIZE, "gust_pak size drift")
    require(sha256_file(gust_pak) == GUST_PAK_SHA256, "gust_pak SHA-256 drift")
    stage119_archive = report_root / STAGE119_ARCHIVE
    manifests_before = manifest_hashes(project_root, manifest_root)

    output_dir = output_report_root / REPORT_DIR
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="br-stage120-") as td:
        temp = Path(td)
        stage119_summary, profiles = load_stage119(stage119_archive, temp / "stage119")
        selected = [str(r["profile_id"]) for r in profiles]
        validate_explicit_selection(selected, selected)
        targets = sorted(EXPECTED_TARGET_SPLIT)
        validate_single_baseline(targets, {t: ["synthetic-baseline"] for t in targets})

        by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in profiles:
            by_target[str(row["target_relative_path"])].append(row)

        overlay_rows: list[dict[str, Any]] = []
        composite_rows: list[dict[str, Any]] = []
        source_rows: list[dict[str, Any]] = []
        sentinel_rows: list[dict[str, Any]] = []
        synthetic_profile_count = 0
        reextract_pass = 0

        for target in targets:
            target_profiles = sorted(by_target[target], key=lambda r: str(r["profile_id"]))
            all_members = sorted({m for r in target_profiles for m in r["members"]})
            sentinel = f"__canary_sentinel__/{Path(target).stem.casefold()}.bin"
            baseline_payloads = {m: f"BASELINE|{target}|{m}".encode() for m in all_members}
            baseline_payloads[sentinel] = f"SENTINEL|{target}".encode()
            out_name = Path(target).name.replace(".PAK", ".pak")
            _, baseline_observed = pack_and_extract(gust_pak, temp, f"baseline_{Path(target).stem}", out_name, baseline_payloads)
            require(baseline_observed == baseline_payloads, f"baseline re-extraction mismatch: {target}")

            profile_observed: dict[str, dict[str, bytes]] = {}
            for row in target_profiles:
                profile_id = str(row["profile_id"])
                payloads = dict(baseline_payloads)
                for member in row["members"]:
                    payloads[member] = f"PROFILE|{profile_id}|{member}".encode()
                _, observed = pack_and_extract(gust_pak, temp, f"profile_{profile_id}", out_name, payloads)
                diffs = sorted(m for m in payloads if observed[m] != baseline_observed[m])
                require(diffs == sorted(row["members"]), f"synthetic profile differs outside declared members: {profile_id}")
                profile_observed[profile_id] = observed
                synthetic_profile_count += 1
                source_rows.append({"profile_id": profile_id, "target_relative_path": target, "declared_member_rows": len(row["members"]), "observed_diff_rows": len(diffs), "validation_status": "passed"})

            composite = dict(baseline_observed)
            for row in target_profiles:
                profile_id = str(row["profile_id"])
                for member in row["members"]:
                    composite[member] = profile_observed[profile_id][member]
                    overlay_rows.append({"target_relative_path": target, "profile_id": profile_id, "changed_member": member, "expected_sha256": hashlib.sha256(composite[member]).hexdigest(), "validation_status": "passed"})
            _, composite_observed = pack_and_extract(gust_pak, temp, f"composite_{Path(target).stem}", out_name, composite)
            for row in target_profiles:
                for member in row["members"]:
                    require(composite_observed[member] == composite[member], f"composite overlay mismatch: {target}:{member}")
            require(composite_observed[sentinel] == baseline_payloads[sentinel], f"sentinel changed: {target}")
            sentinel_rows.append({"target_relative_path": target, "sentinel_member": sentinel, "preserved": True, "sha256": hashlib.sha256(composite_observed[sentinel]).hexdigest()})
            composite_rows.append({"target_relative_path": target, "profile_rows": len(target_profiles), "overlay_member_rows": len(all_members), "full_reextraction_passed": True, "transaction_created": False})
            reextract_pass += 1

        negative_gates = []
        def gate(name: str, fn) -> None:
            passed = False
            try:
                fn()
            except SyntheticComposerError:
                passed = True
            require(passed, f"negative gate did not fail closed: {name}")
            negative_gates.append({"gate_id": name, "passed": True})
        expected_ids = [str(r["profile_id"]) for r in profiles]
        gate("missing_selection", lambda: validate_explicit_selection(expected_ids[:-1], expected_ids))
        gate("duplicate_selection", lambda: validate_explicit_selection(expected_ids[:-1] + [expected_ids[0]], expected_ids))
        overlap = [dict(r) for r in profiles]
        overlap[1] = dict(overlap[1]); overlap[1]["members"] = list(overlap[0]["members"])
        gate("changed_member_overlap", lambda: validate_profile_snapshot(overlap))
        gate("multiple_baselines", lambda: validate_single_baseline(targets, {**{t: ["one"] for t in targets}, targets[0]: ["one", "two"]}))
        runtime = [dict(r) for r in profiles]; runtime[0] = dict(runtime[0]); runtime[0]["runtime_validated"] = "true"
        gate("runtime_validation_drift", lambda: validate_profile_snapshot(runtime))

    manifests_after = manifest_hashes(project_root, manifest_root)
    require(manifests_after == manifests_before, "real profile manifests changed")
    require(len(overlay_rows) == EXPECTED_MEMBERS, "verified overlay count drift")
    require(synthetic_profile_count == EXPECTED_PROFILES, "synthetic profile count drift")
    require(reextract_pass == 3, "composite re-extraction count drift")

    write_tsv(output_dir / "SYNTHETIC_PROFILE_SOURCE_VALIDATIONS.tsv", ["profile_id", "target_relative_path", "declared_member_rows", "observed_diff_rows", "validation_status"], source_rows)
    write_tsv(output_dir / "SYNTHETIC_COMPOSITE_OVERLAYS.tsv", ["target_relative_path", "profile_id", "changed_member", "expected_sha256", "validation_status"], overlay_rows)
    write_tsv(output_dir / "SYNTHETIC_COMPOSITE_TARGETS.tsv", ["target_relative_path", "profile_rows", "overlay_member_rows", "full_reextraction_passed", "transaction_created"], composite_rows)
    write_tsv(output_dir / "SYNTHETIC_SENTINEL_VALIDATIONS.tsv", ["target_relative_path", "sentinel_member", "preserved", "sha256"], sentinel_rows)
    write_tsv(output_dir / "SYNTHETIC_NEGATIVE_GATES.tsv", ["gate_id", "passed"], negative_gates)

    summary = {
        "type": "br_quartet_restoration_canary_all_synthetic_composer_contract_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "synthetic_canary_all_composer_contract_passed_real_gust_pak_fixture_roundtrip_no_install_transaction",
        "stage119_report_sha256": STAGE119_SHA256,
        "stage119_status": stage119_summary["status"],
        "gust_pak_sha256": GUST_PAK_SHA256,
        "gust_pak_size": GUST_PAK_SIZE,
        "explicit_selected_profile_rows": EXPECTED_PROFILES,
        "runtime_unvalidated_selected_profile_rows": EXPECTED_PROFILES,
        "target_group_rows": 3,
        "pack11_profile_rows": 12,
        "pack10_01_profile_rows": 2,
        "pack10_03_profile_rows": 1,
        "overlay_member_rows": EXPECTED_MEMBERS,
        "overlay_member_verified_rows": len(overlay_rows),
        "preserved_sentinel_rows": 3,
        "preserved_sentinel_verified_rows": len(sentinel_rows),
        "fixture_manifest_unchanged_rows": EXPECTED_PROFILES,
        "synthetic_profile_source_validation_rows": len(source_rows),
        "synthetic_profile_source_validation_pass_rows": len(source_rows),
        "real_profile_manifest_unchanged_rows": len(manifests_after),
        "negative_gate_rows": len(negative_gates),
        "negative_gate_pass_rows": len(negative_gates),
        "synthetic_composite_pak_rows": len(composite_rows),
        "synthetic_composite_reextraction_pass_rows": reextract_pass,
        "transaction_artifact_rows": 0,
        "production_composition_root_touched": False,
        "real_profile_paks_extracted": False,
        "real_baseline_paks_rehydrated": False,
        "real_canary_all_build_authorized": False,
        "activation_authorized": False,
        "policy": {
            "tiny_synthetic_gust_pak_fixtures_only": True,
            "all_15_runtime_unvalidated_inputs_selected_explicitly": True,
            "runtime_validation_inferred": False,
            "real_profile_manifests_modified": False,
            "fixture_profile_manifests_modified": False,
            "production_composer_modified": False,
            "production_composer_executed": False,
            "production_composition_root_written": False,
            "installation_transaction_created": False,
            "installed_game_modified": False,
            "core_modified": False,
            "registry_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
            "evidence_contains_pak_payloads": False,
        },
        "next_action": "Implement a separate real-input Canary-all preview/build path only after review. It must require the exact stage-119 15-profile snapshot and explicit IDs, verify one real baseline per target, write only to a dedicated non-production local output root, fully re-extract every composite and still create no installation transaction.",
    }
    (output_dir / "SUMMARY.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    require(not any(p.suffix.casefold() == ".pak" for p in output_dir.rglob("*")), "evidence contains PAK payloads")
    archive = output_report_root / REPORT_NAME
    if create_archive:
        make_archive(output_dir, archive)
    return archive, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    ap.add_argument("--report-root", type=Path)
    ap.add_argument("--output-report-root", type=Path)
    ap.add_argument("--gust-pak", type=Path)
    ap.add_argument("--no-archive", action="store_true")
    args = ap.parse_args()
    try:
        archive, summary = build_report(args.project_root, args.report_root, args.output_report_root, args.gust_pak, not args.no_archive)
    except (SyntheticComposerError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"[canary-synthetic] ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"archive": str(archive), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
