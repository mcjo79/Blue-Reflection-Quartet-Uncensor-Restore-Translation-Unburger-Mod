#!/usr/bin/env python3
"""Generate checksum-gated core registry manifests for local Quartet restoration profiles."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

SCHEMA_VERSION = 1
WORKSTREAM_ID = "quartet_restoration"
ALLOWED_TARGETS = {"Data/PACK11.PAK", "Data/PACK10_01.PAK", "Data/PACK10_03.PAK"}
LOCAL_BUILD_PREFIX = ".local/build/quartet_restoration/"
PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
REPORT_NAME = "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst"
RUNTIME_VALIDATION_REGISTRY = "workstreams/quartet_restoration/RUNTIME_VALIDATION_REGISTRY.json"


class ManifestGenerationError(RuntimeError):
    """Raised when a local profile cannot be safely registered."""


@dataclass(frozen=True)
class ProfileSpec:
    profile_id: str
    target_relative_path: str
    baseline_sha256: str
    baseline_size: int
    profile_sha256: str
    profile_size: int
    local_profile_path: str
    changed_members: tuple[str, ...]


CURRENT_PROFILE_SPECS: tuple[ProfileSpec, ...] = (
    ProfileSpec(
        profile_id="repeated_context_69adef108a_c90700a5a2",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="808ac53575b091b42d8d0e20869d2c966922e13b1711108a645e6c5be9578c60",
        profile_size=13371934,
        local_profile_path=".local/build/quartet_restoration/repack_tests/events/profiles/repeated_context_69adef108a_c90700a5a2/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/fo03/event_fo03_090.ebd",
            "event/b1/event_jp/fo05/event_fo05_090.ebd",
            "event/b1/event_jp/fo09/event_fo09_090.ebd",
            "event/b1/event_jp/fo10/event_fo10_090.ebd",
            "event/b1/event_jp/fo11/event_fo11_090.ebd",
            "event/b1/event_jp/fo12/event_fo12_090.ebd",
            "event/b1/event_jp/fo13/event_fo13_090.ebd",
            "event/b1/event_jp/fo14/event_fo14_090.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="route_sequence_te02_a570203aa6",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="bdbbd0dc159a27b051769dd522fbfe1f1dc35762683b96760d25ca268d807fc9",
        profile_size=13372798,
        local_profile_path=".local/build/quartet_restoration/repack_tests/events/profiles/route_sequence_te02_a570203aa6/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/te02/event_te02_150.ebd",
            "event/b1/event_jp/te02/event_te02_160.ebd",
            "event/b1/event_jp/te02/event_te02_170.ebd",
            "event/b1/event_jp/te02/event_te02_180.ebd",
            "event/b1/event_jp/te02/event_te02_220.ebd",
            "event/b1/event_jp/te02/event_te02_250.ebd",
            "event/b1/event_jp/te02/event_te02_260.ebd",
            "event/b1/event_jp/te02/event_te02_270.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="single_scene_event_te02_230_0143f9822b",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="c1511fdecdb12d6abac5c23e1302735cf0d665a596c44555a7cccafba915ae55",
        profile_size=13372370,
        local_profile_path=".local/build/quartet_restoration/repack_tests/events_single_scene/profiles/single_scene_event_te02_230_0143f9822b/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/te02/event_te02_230.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="shared_presentation_d88c7c3a6f",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="6fcb50fbf43643e147085b0cfbedc6961989fe3c8833dc9f36e87198c88b15b6",
        profile_size=13372318,
        local_profile_path=".local/build/quartet_restoration/repack_tests/residual_shared_presentation/profiles/shared_presentation_d88c7c3a6f/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/ce11/event_ce11_070.ebd",
            "event/b1/event_jp/em01/event_em01_090.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_single_scene_multishape_em01_050_954fadd61cac",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="cf13974fa882f461f2236b7a397d7fdf614b8fa3bf372dbde65a2674ac11c01b",
        profile_size=13372302,
        local_profile_path=".local/build/quartet_restoration/repack_tests/presentation_event_backlog/profiles/candidate_single_scene_multishape_em01_050_954fadd61cac/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/em01/event_em01_050.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_subset_ce07_060_1cddf6cac60969c4",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="ce7d5975de799c222483bc794f4d2b2e884bb64d7a322282d3cf06f3fc07920f",
        profile_size=13372366,
        local_profile_path=".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_ce07_060_1cddf6cac60969c4/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/ce07/event_ce07_060.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_subset_ce11_010_abc7939e4ff69ead",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="e7cebe041ed620142ee386683769299e577dd85ba964ebe33aeda0786a5fbc0b",
        profile_size=13372278,
        local_profile_path=".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_ce11_010_abc7939e4ff69ead/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/ce11/event_ce11_010.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_subset_em01_060_43f9052741640b35",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="391d228247246f9ee54cbc0109b99777265b8476803bf0d11a2f2bd7aa9036b3",
        profile_size=13372258,
        local_profile_path=".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_em01_060_43f9052741640b35/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/em01/event_em01_060.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_subset_em02_030_552c84999f656afb",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="95f2a4129abc81b3c0caa68cc8fe36e9bd166634b15ee1fe64095962749d00dd",
        profile_size=13372230,
        local_profile_path=".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_em02_030_552c84999f656afb/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/em02/event_em02_030.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_subset_te01_270_f6e3b892ac7ba1b9",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="a91189fcdd4e6ae1695e7182a00735ba500cc1da50b76b7d2dedc6cbc7880c57",
        profile_size=13371706,
        local_profile_path=".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_te01_270_f6e3b892ac7ba1b9/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/te01/event_te01_270.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_subset_xf07_030_d85e6afc33b5802b",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="946a61f64ed3c89f23ff8f0bb3d932804e7b3c16bde26477c436dbf81182b344",
        profile_size=13372298,
        local_profile_path=".local/build/quartet_restoration/repack_tests/presentation_event_subset/profiles/candidate_subset_xf07_030_d85e6afc33b5802b/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/xf07/event_xf07_030.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_fe13_090_complete_residual_inverse_9a57d11730c0",
        target_relative_path="Data/PACK11.PAK",
        baseline_sha256="bf53826c840cec9f5cb4044a121a4bada29dd14f56c9f1b1b7633b57cc067306",
        baseline_size=13372318,
        profile_sha256="950a037d16f888281b1c071f35054aec1b5da44e68cfa832af442f9a719e847c",
        profile_size=13372230,
        local_profile_path=".local/build/quartet_restoration/repack_tests/fe13_complete_residual/profiles/candidate_fe13_090_complete_residual_inverse_9a57d11730c0/output/Data/PACK11.PAK",
        changed_members=(
            "event/b1/event_jp/fe13/event_fe13_090.ebd",
        ),
    ),
    ProfileSpec(
        profile_id="height_fog_shader_original_code",
        target_relative_path="Data/PACK10_01.PAK",
        baseline_sha256="cc44e01cca2b1f68714dbe6a3c51b3e3894e612add1e440285e77fd4da5a00b1",
        baseline_size=194151990,
        profile_sha256="332ef210348bd956463cd86473089534656b9dcb3db7dd3252fe15c8492187a0",
        profile_size=194152110,
        local_profile_path=".local/build/quartet_restoration/repack_tests/g1s/profiles/height_fog_shader_original_code/output/Data/PACK10_01.PAK",
        changed_members=(
            "data/b1/x64/shader/heightfog.g1s",
        ),
    ),
    ProfileSpec(
        profile_id="water_shader_swater_original_code",
        target_relative_path="Data/PACK10_01.PAK",
        baseline_sha256="cc44e01cca2b1f68714dbe6a3c51b3e3894e612add1e440285e77fd4da5a00b1",
        baseline_size=194151990,
        profile_sha256="46486d8e897a9d1eec486c97c4d426357579e0f99ffb8e811932978106ca177a",
        profile_size=194151970,
        local_profile_path=".local/build/quartet_restoration/repack_tests/g1s/profiles/water_shader_swater_original_code/output/Data/PACK10_01.PAK",
        changed_members=(
            "data/b1/x64/shader/swater.g1s",
        ),
    ),
    ProfileSpec(
        profile_id="candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d",
        target_relative_path="Data/PACK10_03.PAK",
        baseline_sha256="1f96cc82f869643232445586777d189310de56fb7ad1c90fac9785dc95e8d762",
        baseline_size=10082928931,
        profile_sha256="f0eb8da6f2ea2ad9baa1e0eaab26d577f17225968542b7d7b2f66a0ecd14c10d",
        profile_size=10082518244,
        local_profile_path=".local/build/quartet_restoration/repack_tests/bathroom_river_containing_pak/profiles/candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d/output/Data/PACK10_03.PAK",
        changed_members=(
            "data/b1/x64/field/s89_s_hinako_bath_room_01/s89_s_hinako_bath_room_01.elixir.gz",
        ),
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(raw: str, *, label: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ManifestGenerationError(f"unsafe {label}: {raw}")
    canonical = path.as_posix()
    if canonical != raw:
        raise ManifestGenerationError(f"non-canonical {label}: {raw}")
    return canonical


def ensure_within(path: Path, root: Path, *, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ManifestGenerationError(f"{label} escapes allowed root: {path}") from exc


def validate_specs(specs: Sequence[ProfileSpec]) -> None:
    if not specs:
        raise ManifestGenerationError("no profile specifications supplied")
    seen_ids: set[str] = set()
    for spec in specs:
        if not PROFILE_ID_RE.fullmatch(spec.profile_id):
            raise ManifestGenerationError(f"invalid profile_id: {spec.profile_id}")
        if spec.profile_id in seen_ids:
            raise ManifestGenerationError(f"duplicate profile_id: {spec.profile_id}")
        seen_ids.add(spec.profile_id)
        if spec.target_relative_path not in ALLOWED_TARGETS:
            raise ManifestGenerationError(
                f"unsupported target for {spec.profile_id}: {spec.target_relative_path}"
            )
        local_path = safe_relative_path(spec.local_profile_path, label="local_profile_path")
        if not local_path.startswith(LOCAL_BUILD_PREFIX):
            raise ManifestGenerationError(
                f"local profile is outside {LOCAL_BUILD_PREFIX}: {local_path}"
            )
        if spec.baseline_size <= 0 or spec.profile_size <= 0:
            raise ManifestGenerationError(f"invalid archive size for {spec.profile_id}")
        for digest_name, digest in (
            ("baseline_sha256", spec.baseline_sha256),
            ("profile_sha256", spec.profile_sha256),
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ManifestGenerationError(
                    f"invalid {digest_name} for {spec.profile_id}: {digest}"
                )
        if not spec.changed_members:
            raise ManifestGenerationError(f"empty changed_members for {spec.profile_id}")
        if len(set(spec.changed_members)) != len(spec.changed_members):
            raise ManifestGenerationError(f"duplicate changed member for {spec.profile_id}")
        for member in spec.changed_members:
            safe_relative_path(member, label="changed archive member")


def load_runtime_validation_registry(
    project_root: Path,
    specs: Sequence[ProfileSpec],
) -> tuple[dict[str, bool], dict[str, object]]:
    path = project_root / RUNTIME_VALIDATION_REGISTRY
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestGenerationError(f"missing runtime-validation registry: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestGenerationError(f"invalid runtime-validation registry JSON: {exc}") from exc
    if data.get("type") != "br_quartet_restoration_runtime_validation_registry":
        raise ManifestGenerationError("runtime-validation registry type mismatch")
    if data.get("format_version") != 1:
        raise ManifestGenerationError("runtime-validation registry format mismatch")

    spec_by_id = {spec.profile_id: spec for spec in specs}
    decisions: dict[str, bool] = {}
    direct = data.get("profiles")
    if not isinstance(direct, dict):
        raise ManifestGenerationError("runtime-validation registry profiles are missing")
    for profile_id, row in direct.items():
        if profile_id not in spec_by_id:
            raise ManifestGenerationError(f"runtime-validation registry references unknown profile: {profile_id}")
        if not isinstance(row, dict) or not isinstance(row.get("runtime_validated"), bool):
            raise ManifestGenerationError(f"invalid runtime decision for {profile_id}")
        spec = spec_by_id[profile_id]
        if row.get("target_relative_path") != spec.target_relative_path:
            raise ManifestGenerationError(f"runtime target mismatch for {profile_id}")
        if row.get("profile_sha256") != spec.profile_sha256:
            raise ManifestGenerationError(f"runtime profile checksum mismatch for {profile_id}")
        if bool(row.get("production_eligible")) != bool(row.get("runtime_validated")):
            raise ManifestGenerationError(f"runtime production eligibility mismatch for {profile_id}")
        decisions[profile_id] = bool(row["runtime_validated"])

    event_group = data.get("event_group")
    if not isinstance(event_group, dict):
        raise ManifestGenerationError("runtime-validation event group is missing")
    event_ids = event_group.get("profile_ids")
    if not isinstance(event_ids, list) or not all(isinstance(item, str) for item in event_ids):
        raise ManifestGenerationError("runtime-validation event profile IDs are invalid")
    expected_event_ids = {
        spec.profile_id for spec in specs if spec.target_relative_path == "Data/PACK11.PAK"
    }
    if set(event_ids) != expected_event_ids or len(event_ids) != len(expected_event_ids):
        raise ManifestGenerationError("runtime-validation event group does not match current PACK11 specs")
    if event_group.get("profile_count") != len(expected_event_ids):
        raise ManifestGenerationError("runtime-validation event group count mismatch")
    if event_group.get("individual_runtime_validated") is not False:
        raise ManifestGenerationError("PACK11 profiles must remain individually runtime-unvalidated")
    if event_group.get("production_eligible") is not False:
        raise ManifestGenerationError("PACK11 profiles must remain production-ineligible")
    for profile_id in event_ids:
        if profile_id in decisions:
            raise ManifestGenerationError(f"duplicate runtime decision for {profile_id}")
        decisions[profile_id] = False

    if set(decisions) != set(spec_by_id):
        missing = sorted(set(spec_by_id) - set(decisions))
        extra = sorted(set(decisions) - set(spec_by_id))
        raise ManifestGenerationError(
            f"runtime-validation registry coverage mismatch: missing={missing}, extra={extra}"
        )
    validated = sorted(profile_id for profile_id, value in decisions.items() if value)
    bathroom_id = "candidate_bathroom_river_containing_pak_static_inverse_062e39915e7d"
    expected_validated = [bathroom_id] if bathroom_id in spec_by_id else []
    if validated != expected_validated:
        raise ManifestGenerationError(f"unexpected runtime-validated profile set: {validated}")
    return decisions, data


def read_workstream_version(project_root: Path) -> str:
    path = project_root / "workstreams" / WORKSTREAM_ID / "VERSION"
    try:
        version = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ManifestGenerationError(f"missing workstream version: {path}") from exc
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ManifestGenerationError(f"invalid workstream version: {version!r}")
    return version


def validate_local_profile(project_root: Path, spec: ProfileSpec) -> Path:
    build_root = (project_root / ".local" / "build" / WORKSTREAM_ID).resolve(strict=True)
    lexical = project_root / PurePosixPath(spec.local_profile_path)
    if lexical.is_symlink():
        raise ManifestGenerationError(
            f"local profile must not be a symlink: {spec.local_profile_path}"
        )
    try:
        resolved = lexical.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ManifestGenerationError(
            f"local profile PAK is missing: {spec.local_profile_path}"
        ) from exc
    ensure_within(resolved, build_root, label="local profile")
    if not resolved.is_file():
        raise ManifestGenerationError(
            f"local profile is not a regular file: {spec.local_profile_path}"
        )
    actual_size = resolved.stat().st_size
    if actual_size != spec.profile_size:
        raise ManifestGenerationError(
            f"profile size mismatch for {spec.profile_id}: expected {spec.profile_size}, got {actual_size}"
        )
    actual_sha = sha256_file(resolved)
    if actual_sha != spec.profile_sha256:
        raise ManifestGenerationError(
            f"profile checksum mismatch for {spec.profile_id}: expected {spec.profile_sha256}, got {actual_sha}"
        )
    return resolved


def build_manifest(
    spec: ProfileSpec,
    workstream_version: str,
    runtime_validated: bool,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": spec.profile_id,
        "target_relative_path": spec.target_relative_path,
        "baseline_sha256": spec.baseline_sha256,
        "baseline_size": spec.baseline_size,
        "profile_sha256": spec.profile_sha256,
        "profile_size": spec.profile_size,
        "local_profile_path": spec.local_profile_path,
        "changed_member_count": len(spec.changed_members),
        "changed_members": list(spec.changed_members),
        "runtime_validated": runtime_validated,
        "workstream_id": WORKSTREAM_ID,
        "workstream_version": workstream_version,
    }


def atomic_write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    temporary.write_text(payload, encoding="utf-8")
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def replace_generated_directory(
    *,
    project_root: Path,
    manifests: Sequence[tuple[ProfileSpec, dict[str, object]]],
) -> Path:
    registry_root = project_root / ".local" / "build" / WORKSTREAM_ID / "core_profiles"
    generated = registry_root / "generated"
    registry_root.mkdir(parents=True, exist_ok=True)
    if registry_root.is_symlink() or generated.is_symlink():
        raise ManifestGenerationError("core profile registry path must not be a symlink")

    temporary = Path(tempfile.mkdtemp(prefix=".generated.", dir=registry_root))
    old: Path | None = None
    try:
        for spec, manifest in manifests:
            atomic_write_json(temporary / f"{spec.profile_id}.json", manifest)
            loaded = json.loads((temporary / f"{spec.profile_id}.json").read_text(encoding="utf-8"))
            if loaded != manifest:
                raise ManifestGenerationError(
                    f"manifest round-trip mismatch for {spec.profile_id}"
                )

        if generated.exists():
            old = registry_root / f".generated.old.{os.getpid()}"
            os.replace(generated, old)
        try:
            os.replace(temporary, generated)
        except Exception:
            if old is not None and old.exists() and not generated.exists():
                os.replace(old, generated)
                old = None
            raise
        if old is not None and old.exists():
            shutil.rmtree(old)
        return generated
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def write_evidence_report(
    *,
    project_root: Path,
    workstream_version: str,
    manifests: Sequence[tuple[ProfileSpec, dict[str, object]]],
    generated_dir: Path,
    create_archive: bool,
) -> Path | None:
    report_root = project_root / ".local" / "reports" / WORKSTREAM_ID
    evidence_dir = report_root / "core_profile_manifest_evidence"
    if evidence_dir.exists():
        shutil.rmtree(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    tsv_path = evidence_dir / "CORE_PROFILE_MANIFESTS.tsv"
    with tsv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "profile_id",
            "target_relative_path",
            "baseline_sha256",
            "baseline_size",
            "profile_sha256",
            "profile_size",
            "local_profile_path",
            "changed_member_count",
            "manifest_relative_path",
            "runtime_validated",
            "workstream_version",
            "validation_status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for spec, manifest in manifests:
            writer.writerow(
                {
                    "profile_id": spec.profile_id,
                    "target_relative_path": spec.target_relative_path,
                    "baseline_sha256": spec.baseline_sha256,
                    "baseline_size": spec.baseline_size,
                    "profile_sha256": spec.profile_sha256,
                    "profile_size": spec.profile_size,
                    "local_profile_path": spec.local_profile_path,
                    "changed_member_count": len(spec.changed_members),
                    "manifest_relative_path": (
                        generated_dir / f"{spec.profile_id}.json"
                    ).relative_to(project_root).as_posix(),
                    "runtime_validated": str(manifest["runtime_validated"]).lower(),
                    "workstream_version": workstream_version,
                    "validation_status": "passed",
                }
            )

    summary = {
        "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
        "format_version": 1,
        "tool_version": workstream_version,
        "status": (
            "current_local_profiles_registered_with_runtime_validated_subset"
            if any(manifest["runtime_validated"] for _, manifest in manifests)
            else "all_current_local_profiles_registered_runtime_unvalidated"
        ),
        "profile_rows": len(manifests),
        "pack11_profile_rows": sum(
            1 for spec, _ in manifests if spec.target_relative_path == "Data/PACK11.PAK"
        ),
        "pack10_01_profile_rows": sum(
            1 for spec, _ in manifests if spec.target_relative_path == "Data/PACK10_01.PAK"
        ),
        "pack10_03_profile_rows": sum(
            1 for spec, _ in manifests if spec.target_relative_path == "Data/PACK10_03.PAK"
        ),
        "runtime_validated_profile_rows": sum(
            1 for _, manifest in manifests if manifest["runtime_validated"]
        ),
        "runtime_validated_profile_ids": [
            spec.profile_id for spec, manifest in manifests if manifest["runtime_validated"]
        ],
        "runtime_validation_registry": RUNTIME_VALIDATION_REGISTRY,
        "manifest_root": generated_dir.relative_to(project_root).as_posix(),
        "policy": {
            "local_paks_copied": False,
            "activation_or_rollback_scripts_generated": False,
            "core_transaction_state_modified": False,
            "core_backups_modified": False,
            "profile_paks_checksum_and_size_verified": True,
            "runtime_validation_inferred": False,
            "legacy_dlc_in_scope": False,
        },
        "next_action": f"Run Blue_Reflection_Patcher/cmd/br_quartet_profiles.sh list and review all {len(manifests)} independently validated profiles.",
    }
    atomic_write_json(evidence_dir / "SUMMARY.json", summary)

    if not create_archive:
        return None
    report_root.mkdir(parents=True, exist_ok=True)
    archive = report_root / REPORT_NAME
    temporary_archive = archive.with_name(archive.name + f".tmp.{os.getpid()}")
    command = [
        "tar",
        "--zstd",
        "-cf",
        str(temporary_archive),
        "-C",
        str(report_root),
        evidence_dir.name,
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.returncode != 0:
        temporary_archive.unlink(missing_ok=True)
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown tar error"
        raise ManifestGenerationError(f"failed to create evidence report: {detail}")
    os.replace(temporary_archive, archive)
    return archive


def generate_manifests(
    *,
    project_root: Path,
    specs: Sequence[ProfileSpec] = CURRENT_PROFILE_SPECS,
    create_report_archive: bool = True,
) -> tuple[Path, Path | None, list[dict[str, object]]]:
    project_root = project_root.expanduser().resolve()
    if not project_root.is_dir():
        raise ManifestGenerationError(f"project root does not exist: {project_root}")
    validate_specs(specs)
    version = read_workstream_version(project_root)
    runtime_decisions, _ = load_runtime_validation_registry(project_root, specs)

    prepared: list[tuple[ProfileSpec, dict[str, object]]] = []
    for spec in specs:
        validate_local_profile(project_root, spec)
        prepared.append((spec, build_manifest(spec, version, runtime_decisions[spec.profile_id])))

    generated_dir = replace_generated_directory(project_root=project_root, manifests=prepared)
    report = write_evidence_report(
        project_root=project_root,
        workstream_version=version,
        manifests=prepared,
        generated_dir=generated_dir,
        create_archive=create_report_archive,
    )
    return generated_dir, report, [manifest for _, manifest in prepared]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    generated_dir, report, manifests = generate_manifests(
        project_root=Path(args.project_root),
        create_report_archive=not args.no_report_archive,
    )
    print(f"Generated manifests: {len(manifests)}")
    print(f"Manifest directory: {generated_dir}")
    for manifest in manifests:
        print(
            f"- {manifest['profile_id']} -> {manifest['target_relative_path']} "
            f"({manifest['changed_member_count']} changed member(s), runtime_validated={str(manifest['runtime_validated']).lower()})"
        )
    if report is not None:
        print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ManifestGenerationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
