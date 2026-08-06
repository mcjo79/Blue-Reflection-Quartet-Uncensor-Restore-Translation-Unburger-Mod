#!/usr/bin/env python3
"""Stage 145: canonically verify the Gamma runtime observation and assess GlowLight readiness.

This stage is metadata-only. The 0.1.63 update persists the explicit user-observed
Gamma result in GAMMA_RUNTIME_OBSERVATION.json and RUNTIME_VALIDATION_REGISTRY.json.
The collector verifies those canonical records against the immutable stage-143
profile-preparation report plus the user-run stage-144 activation and rollback
reports. Only after that verification does it assess whether GlowLight is a
technically prepared candidate for a *future*, separately authorized, isolated
Fast Test Lab run.

The collector never reads an installed game file, never activates a profile,
never writes a PAK, and never promotes Gamma or GlowLight.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.63"
REPORT_DIR = "gamma_runtime_observation_glowlight_readiness_evidence"
REPORT_NAME = "BR_quartet_restoration_gamma_runtime_observation_glowlight_readiness_evidence.tar.zst"

OBSERVATION_RELATIVE_PATH = "workstreams/quartet_restoration/GAMMA_RUNTIME_OBSERVATION.json"
REGISTRY_RELATIVE_PATH = "workstreams/quartet_restoration/RUNTIME_VALIDATION_REGISTRY.json"
STATUS_RELATIVE_PATH = "workstreams/quartet_restoration/STATUS.json"

STAGE143_REPORT = "BR_quartet_restoration_effect_posteffect_kps_fast_test_lab_profile_preparation_evidence.tar.zst"
STAGE143_DIR = "effect_posteffect_kps_fast_test_lab_profile_preparation_evidence"
STAGE143_SHA256 = "a104e1129e2f6dc544fb16b43cfaaae95c77617dea1d7540beebf958e2d87c86"

ACTIVATION_REPORT = "BR_quartet_restoration_kps_gamma_fast_test_lab_activation_evidence.tar.zst"
ACTIVATION_DIR = "kps_gamma_fast_test_lab_activation_evidence"
ACTIVATION_SHA256 = "dc8fc9f1244721ca31e19b35f58835725fcd927964fb6310937dc65d218bde5b"

ROLLBACK_REPORT = "BR_quartet_restoration_kps_gamma_fast_test_lab_rollback_evidence.tar.zst"
ROLLBACK_DIR = "kps_gamma_fast_test_lab_rollback_evidence"
ROLLBACK_SHA256 = "9c0faf212bdb3df9e54fcbe71b30d4f844f9cae8f7cf28d7758225fc58f7378f"

OBSERVATION_SHA256 = "d68326e8865b89455bbf9bf1f22a4b8ae1c4676e72e3454e4a2d9a4bfd1d155c"
BASELINE_SHA256 = "cc44e01cca2b1f68714dbe6a3c51b3e3894e612add1e440285e77fd4da5a00b1"
GAMMA_PROFILE_ID = "fast_test_kps_posteffectgamma_target_dword_3c4565adce04"
GAMMA_PROFILE_SHA256 = "3356e32f1660ab9f301c74d1d105a032a8f55566deeb4ec30394d3afe43f3b14"
GLOWLIGHT_PROFILE_ID = "fast_test_kps_posteffectglowlight_target_dword_61389ebb65bb"
GLOWLIGHT_PROFILE_SHA256 = "ecc301ef0dd0e99b2149ecd4509d6766c1b635d0eb6a3852aa29bb46a3482b9e"
BATHROOM_PROFILE_ID = "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"
TARGET_RELATIVE_PATH = "Data/PACK10_01.PAK"
BATHROOM_TARGET_RELATIVE_PATH = "Data/PACK10_03.PAK"

FORBIDDEN_REPORT_EXTENSIONS = (
    ".pak", ".kps", ".dxbc", ".g1e", ".g1em", ".g1m", ".g1s", ".g1t",
    ".elixir", ".elixir.gz", ".ebd", ".ebm",
)


class Stage145Error(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stage145Error(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts, f"unsafe {label}: {value}")
    return path.as_posix()


def read_tsv(path: Path) -> list[dict[str, str]]:
    require(path.is_file(), f"missing TSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def extract_report(archive: Path, expected_root: str, destination: Path) -> Path:
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, capture_output=True)
    require(listed.returncode == 0, listed.stderr.strip() or f"cannot list {archive.name}")
    names = [safe_relative(line, "report member") for line in listed.stdout.splitlines() if line.strip()]
    require(names, f"empty report archive: {archive.name}")
    require({PurePosixPath(name).parts[0] for name in names} == {expected_root}, f"unexpected root in {archive.name}")
    require(not any(name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for name in names), f"proprietary payload in {archive.name}")
    destination.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or f"cannot extract {archive.name}")
    root = destination / expected_root
    require(root.is_dir(), f"missing extracted root: {root}")
    return root


def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    completed = subprocess.run(["tar", "--zstd", "--sort=name", "--mtime=@0", "--owner=0", "--group=0", "--numeric-owner", "-cf", str(temporary), "-C", str(source.parent), source.name], text=True, capture_output=True)
    require(completed.returncode == 0, completed.stderr.strip() or "archive creation failed")
    os.replace(temporary, output)


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"missing {label}: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(data, dict), f"invalid {label}: {path}")
    return data


def build_report(
    project_root: Path,
    *,
    report_root: Path | None = None,
    output_report_root: Path | None = None,
    create_archive: bool = True,
) -> tuple[Path | None, dict[str, Any]]:
    project_root = project_root.resolve()
    workstream = project_root / "workstreams/quartet_restoration"
    version_path = workstream / "VERSION"
    require(version_path.is_file(), f"missing VERSION: {version_path}")
    version_text = version_path.read_text(encoding="utf-8").strip()
    version = tuple(int(part) for part in version_text.split("."))
    require(version >= (0, 1, 63), f"stage 145 requires quartet_restoration 0.1.63 or newer, found {version_text}")

    report_root = (report_root or project_root / ".local/reports/quartet_restoration").resolve()
    output_report_root = (output_report_root or report_root).resolve()

    observation_path = project_root / OBSERVATION_RELATIVE_PATH
    registry_path = project_root / REGISTRY_RELATIVE_PATH
    status_path = project_root / STATUS_RELATIVE_PATH
    require(sha256_file(observation_path) == OBSERVATION_SHA256, "Gamma runtime observation record hash drift")
    observation = load_json(observation_path, "Gamma observation")
    registry = load_json(registry_path, "runtime validation registry")
    status = load_json(status_path, "workstream status")

    require(observation.get("profile_id") == GAMMA_PROFILE_ID, "Gamma observation profile drift")
    require(observation.get("target_relative_path") == TARGET_RELATIVE_PATH, "Gamma observation target drift")
    require(observation.get("profile_sha256") == GAMMA_PROFILE_SHA256, "Gamma observation profile hash drift")
    require(observation.get("runtime_stability_user_reported") is True, "Gamma stability result missing")
    require(observation.get("visible_effect_confirmed") is False, "Gamma visual effect must remain unconfirmed")
    require(observation.get("runtime_status") == "runtime_stable_visual_effect_unconfirmed", "Gamma runtime status drift")
    require(observation.get("runtime_validated") is False, "Gamma must not be runtime-validated")
    require(observation.get("production_eligible") is False, "Gamma must not be production-eligible")
    require(observation.get("confirmed_visual_semantics") is None, "Gamma must not have confirmed visual semantics")
    require(observation.get("exact_pack10_01_baseline_restored") is True, "Gamma rollback result missing")
    require(observation.get("pack10_01_baseline_sha256") == BASELINE_SHA256, "Gamma baseline hash drift")
    require(observation.get("gamma_retest_required") is False, "Gamma must not require a repeat test merely to strengthen the visual claim")
    context = observation.get("test_context", {})
    require(context.get("bathroom_water_profile_id") == BATHROOM_PROFILE_ID, "Gamma test-context profile drift")
    require(context.get("bathroom_water_target_relative_path") == BATHROOM_TARGET_RELATIVE_PATH, "Gamma test-context target drift")
    require(context.get("bathroom_water_profile_was_active") is True, "Gamma test context must preserve active bathroom profile")

    gamma_registry = registry.get("fast_test_results", {}).get(GAMMA_PROFILE_ID)
    require(isinstance(gamma_registry, dict), "Gamma result is missing from runtime registry")
    for key, expected in {
        "target_relative_path": TARGET_RELATIVE_PATH,
        "profile_sha256": GAMMA_PROFILE_SHA256,
        "runtime_status": "runtime_stable_visual_effect_unconfirmed",
        "runtime_tested": True,
        "runtime_stable": True,
        "visible_effect_confirmed": False,
        "runtime_validated": False,
        "production_eligible": False,
        "activation_evidence_sha256": ACTIVATION_SHA256,
        "rollback_evidence_sha256": ROLLBACK_SHA256,
        "exact_pack10_01_baseline_restored": True,
        "pack10_01_baseline_sha256": BASELINE_SHA256,
        "confirmed_semantics": None,
        "gamma_retest_required": False,
    }.items():
        require(gamma_registry.get(key) == expected, f"Gamma registry drift: {key}")
    registry_context = gamma_registry.get("test_context", {})
    require(registry_context.get("bathroom_water_profile_id") == BATHROOM_PROFILE_ID, "Gamma registry context profile drift")
    require(registry_context.get("bathroom_water_target_relative_path") == BATHROOM_TARGET_RELATIVE_PATH, "Gamma registry context target drift")
    require(registry_context.get("bathroom_water_profile_was_active") is True, "Gamma registry context must preserve bathroom profile")

    bathroom = registry.get("profiles", {}).get(BATHROOM_PROFILE_ID)
    require(isinstance(bathroom, dict), "canonical bathroom-water profile missing")
    require(bathroom.get("target_relative_path") == BATHROOM_TARGET_RELATIVE_PATH, "bathroom profile target drift")
    require(bathroom.get("runtime_validated") is True and bathroom.get("production_eligible") is True, "bathroom profile promotion drift")

    stage144 = status.get("kps_gamma_fast_test_lab_runtime_stage", {})
    require(stage144.get("status") == "complete_gamma_runtime_stable_visual_effect_unconfirmed_exact_rollback_verified", "stage-144 status is not canonicalized")
    require(stage144.get("runtime_stability_user_reported") is True, "stage-144 stability result missing")
    require(stage144.get("visible_effect_confirmed") is False, "stage-144 visual result drift")
    require(stage144.get("runtime_validated_after_test") is False, "stage-144 must not promote Gamma")
    require(stage144.get("production_eligible_after_test") is False, "stage-144 must keep Gamma nonproduction")
    require(stage144.get("exact_pack10_01_baseline_restored") is True, "stage-144 exact rollback missing")
    require(stage144.get("pack10_03_modified_by_gamma_workflow") is False, "Gamma workflow must not modify PACK10_03")

    stage145 = status.get("gamma_runtime_observation_glowlight_readiness_stage", {})
    require(stage145.get("stage") == 145 and stage145.get("tool_version") == TOOL_VERSION, "stage-145 status record drift")
    require(stage145.get("gamma_runtime_validated") is False, "stage 145 cannot promote Gamma")
    require(stage145.get("glowlight_runtime_tested") is False, "GlowLight must remain untested")
    require(stage145.get("glowlight_runtime_validated") is False, "GlowLight must remain runtime-unvalidated")
    require(stage145.get("glowlight_production_eligible") is False, "GlowLight must remain nonproduction")
    require(stage145.get("glowlight_activation_authorized") is False, "GlowLight activation must remain unauthorized")
    require(stage145.get("glowlight_requires_separate_user_authorization") is True, "GlowLight must require separate user authorization")
    require(stage145.get("writes_installed_game") is False, "stage 145 must be no-write")

    reports = [
        ("stage143_profile_preparation", STAGE143_REPORT, STAGE143_DIR, STAGE143_SHA256),
        ("gamma_activation", ACTIVATION_REPORT, ACTIVATION_DIR, ACTIVATION_SHA256),
        ("gamma_rollback", ROLLBACK_REPORT, ROLLBACK_DIR, ROLLBACK_SHA256),
    ]
    extracted: dict[str, Path] = {}
    input_rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="stage145-prereq-") as temporary_text:
        temporary = Path(temporary_text)
        for index, (input_id, filename, root_name, expected_sha) in enumerate(reports):
            archive = report_root / filename
            require(archive.is_file(), f"missing prerequisite report: {archive}")
            digest = sha256_file(archive)
            require(digest == expected_sha, f"{input_id} SHA-256 drift: {digest}")
            extracted[input_id] = extract_report(archive, root_name, temporary / str(index))
            input_rows.append({"input_id": input_id, "relative_path": f".local/reports/quartet_restoration/{filename}", "sha256": digest, "verified": True})

        stage143_summary = load_json(extracted["stage143_profile_preparation"] / "SUMMARY.json", "stage-143 summary")
        require(stage143_summary.get("fast_test_profile_rows") == 2, "stage-143 profile cardinality drift")
        require(stage143_summary.get("glowlight_profile_rows") == 1, "stage-143 GlowLight row drift")
        require(stage143_summary.get("runtime_validated_profile_rows_created") == 0, "stage-143 runtime promotion drift")
        require(stage143_summary.get("normal_composer_eligible_profile_rows_created") == 0, "stage-143 composer eligibility drift")
        require(stage143_summary.get("automatic_activation_rows") == 0, "stage-143 automatic activation drift")
        profiles = read_tsv(extracted["stage143_profile_preparation"] / "FAST_TEST_LAB_PROFILES.tsv")
        glow_rows = [row for row in profiles if row.get("profile_id") == GLOWLIGHT_PROFILE_ID]
        require(len(glow_rows) == 1, "expected exactly one GlowLight stage-143 profile row")
        glow = glow_rows[0]
        require(glow.get("member_name") == "PostEffectGlowLight.kps", "GlowLight member drift")
        require(glow.get("profile_pak_sha256") == GLOWLIGHT_PROFILE_SHA256, "GlowLight profile PAK hash drift")
        require(glow.get("target_relative_path") == TARGET_RELATIVE_PATH, "GlowLight target drift")
        require(glow.get("runtime_validated") == "False", "GlowLight stage-143 runtime flag drift")
        require(glow.get("normal_composer_eligible") == "False", "GlowLight stage-143 composer flag drift")
        require(glow.get("installed") == "False", "GlowLight stage-143 install flag drift")

        activation = load_json(extracted["gamma_activation"] / "SUMMARY.json", "Gamma activation summary")
        require(activation.get("profile_id") == GAMMA_PROFILE_ID, "activation profile drift")
        require(activation.get("installed_target_sha256") == GAMMA_PROFILE_SHA256, "activation installed hash drift")
        require(activation.get("runtime_validated") is False, "activation must not set runtime validation")
        require(activation.get("glowlight_activated") is False, "GlowLight was unexpectedly activated during Gamma")
        require(activation.get("rollback_required") is True, "Gamma activation must require rollback")

        rollback = load_json(extracted["gamma_rollback"] / "SUMMARY.json", "Gamma rollback summary")
        require(rollback.get("profile_id") == GAMMA_PROFILE_ID, "rollback profile drift")
        require(rollback.get("exact_baseline_restored") is True, "rollback did not restore exact baseline")
        require(rollback.get("installed_target_sha256") == BASELINE_SHA256, "rollback baseline hash drift")
        require(rollback.get("core_state_status") == "rolled_back", "rollback state drift")
        require(rollback.get("runtime_validated") is False, "rollback must not set runtime validation")
        require(rollback.get("glowlight_activated") is False, "GlowLight was unexpectedly activated")

    # Readiness is evaluated only after the explicit Gamma result and exact rollback are verified.
    glowlight_ready = all([
        observation.get("runtime_stability_user_reported") is True,
        observation.get("visible_effect_confirmed") is False,
        observation.get("runtime_validated") is False,
        rollback.get("exact_baseline_restored") is True,
        glow.get("runtime_validated") == "False",
        glow.get("normal_composer_eligible") == "False",
        glow.get("installed") == "False",
    ])
    require(glowlight_ready is True, "GlowLight technical readiness prerequisites were not met")

    output_report_root.mkdir(parents=True, exist_ok=True)
    out_dir = output_report_root / REPORT_DIR
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    input_rows.extend([
        {"input_id": "gamma_runtime_observation", "relative_path": OBSERVATION_RELATIVE_PATH, "sha256": OBSERVATION_SHA256, "verified": True},
        {"input_id": "runtime_validation_registry", "relative_path": REGISTRY_RELATIVE_PATH, "sha256": sha256_file(registry_path), "verified": True},
        {"input_id": "workstream_status", "relative_path": STATUS_RELATIVE_PATH, "sha256": sha256_file(status_path), "verified": True},
    ])
    write_tsv(out_dir / "INPUT_HASHES.tsv", ["input_id", "relative_path", "sha256", "verified"], input_rows)

    canonical_rows = [{
        "profile_id": GAMMA_PROFILE_ID,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "runtime_status": "runtime_stable_visual_effect_unconfirmed",
        "runtime_tested": True,
        "runtime_stable": True,
        "visible_effect_confirmed": False,
        "runtime_validated": False,
        "production_eligible": False,
        "confirmed_visual_semantics": False,
        "exact_pack10_01_baseline_restored": True,
        "pack10_01_baseline_sha256": BASELINE_SHA256,
        "bathroom_water_profile_active_during_test": True,
        "bathroom_water_target_relative_path": BATHROOM_TARGET_RELATIVE_PATH,
        "gamma_retest_required": False,
    }]
    write_tsv(out_dir / "GAMMA_RUNTIME_RESULT.tsv", list(canonical_rows[0]), canonical_rows)

    glowlight_rows = [{
        "profile_id": GLOWLIGHT_PROFILE_ID,
        "member_name": "PostEffectGlowLight.kps",
        "profile_pak_sha256": GLOWLIGHT_PROFILE_SHA256,
        "target_relative_path": TARGET_RELATIVE_PATH,
        "stage143_profile_preparation_verified": True,
        "runtime_tested": False,
        "runtime_validated": False,
        "production_eligible": False,
        "separate_test_technically_ready_after_exact_baseline_preflight": True,
        "activation_authorized": False,
        "separate_user_authorization_required": True,
        "must_be_tested_alone": True,
        "rollback_required": True,
        "pack10_03_must_not_be_modified": True,
    }]
    write_tsv(out_dir / "GLOWLIGHT_READINESS.tsv", list(glowlight_rows[0]), glowlight_rows)

    summary: dict[str, Any] = {
        "type": "br_quartet_restoration_gamma_runtime_observation_glowlight_readiness_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "status": "gamma_runtime_stable_visual_effect_unconfirmed_canonically_verified_glowlight_separate_test_technically_ready_but_not_authorized",
        "gamma_profile_id": GAMMA_PROFILE_ID,
        "gamma_runtime_tested": True,
        "gamma_runtime_stable": True,
        "gamma_visible_effect_confirmed": False,
        "gamma_runtime_validated": False,
        "gamma_production_eligible": False,
        "gamma_confirmed_visual_semantics": False,
        "gamma_retest_required": False,
        "gamma_activation_evidence_sha256": ACTIVATION_SHA256,
        "gamma_rollback_evidence_sha256": ROLLBACK_SHA256,
        "exact_pack10_01_baseline_restored": True,
        "pack10_01_baseline_sha256": BASELINE_SHA256,
        "bathroom_water_profile_id": BATHROOM_PROFILE_ID,
        "bathroom_water_profile_was_active_during_gamma_test": True,
        "bathroom_water_target_relative_path": BATHROOM_TARGET_RELATIVE_PATH,
        "glowlight_profile_id": GLOWLIGHT_PROFILE_ID,
        "glowlight_profile_sha256": GLOWLIGHT_PROFILE_SHA256,
        "glowlight_stage143_profile_preparation_verified": True,
        "glowlight_runtime_tested": False,
        "glowlight_runtime_validated": False,
        "glowlight_production_eligible": False,
        "glowlight_separate_test_technically_ready_after_exact_baseline_preflight": True,
        "glowlight_activation_authorized": False,
        "glowlight_requires_separate_user_authorization": True,
        "skipped_rows": 0,
        "policy": {
            "metadata_only": True,
            "proprietary_payload_rehydrated": False,
            "installed_game_read": False,
            "installed_game_modified": False,
            "pak_built_or_repacked": False,
            "profile_activated": False,
            "runtime_validation_inferred": False,
            "gamma_runtime_stability_does_not_imply_visual_validation": True,
            "gamma_visual_effect_not_inferred": True,
            "gamma_production_promotion_authorized": False,
            "gamma_repeat_test_required": False,
            "glowlight_runtime_result_inferred": False,
            "glowlight_activation_authorized": False,
            "glowlight_must_be_tested_separately": True,
            "glowlight_exact_pack10_01_baseline_preflight_required": True,
            "glowlight_exact_rollback_required": True,
            "pack10_03_must_not_be_modified": True,
            "core_modified": False,
            "translation_modified": False,
            "legacy_dlc_modified": False,
            "git_modified": False,
        },
        "next_action": "Keep Gamma nonproduction and do not repeat it merely to strengthen the visual claim. If the user separately authorizes an installed-game test, prepare a GlowLight-only Fast Test Lab stage using the existing core PACK10_01 transaction route, require the exact baseline before activation, test GlowLight alone, and roll back exactly afterward. Do not touch PACK10_03.",
    }
    write_json(out_dir / "SUMMARY.json", summary)

    archive_path: Path | None = None
    if create_archive:
        archive_path = output_report_root / REPORT_NAME
        make_archive(out_dir, archive_path)
    return archive_path, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--report-root", default=None)
    parser.add_argument("--output-report-root", default=None)
    parser.add_argument("--no-archive", action="store_true")
    args = parser.parse_args()

    script = Path(__file__).resolve()
    default_project = script.parents[2]
    project_root = Path(args.project_root).expanduser().resolve() if args.project_root else default_project
    report_root = Path(args.report_root).expanduser().resolve() if args.report_root else None
    output_root = Path(args.output_report_root).expanduser().resolve() if args.output_report_root else None
    archive, summary = build_report(project_root, report_root=report_root, output_report_root=output_root, create_archive=not args.no_archive)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if archive is not None:
        print(f"[stage145] report archive: {archive}")
        print(f"[stage145] SHA-256: {sha256_file(archive)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stage145Error as exc:
        print(f"[stage145] ERROR: {exc}", file=__import__('sys').stderr)
        raise SystemExit(1)
