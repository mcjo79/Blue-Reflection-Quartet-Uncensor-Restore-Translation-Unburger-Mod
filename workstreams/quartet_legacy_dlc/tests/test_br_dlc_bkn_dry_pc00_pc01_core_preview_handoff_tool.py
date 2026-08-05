from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "br_dlc_bkn_dry_pc00_pc01_core_preview_handoff_tool.py"
spec = importlib.util.spec_from_file_location("handoff_tool", MODULE_PATH)
assert spec and spec.loader
TOOL = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TOOL)

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

def project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    game = tmp_path / "game"
    ws = root / "workstreams/quartet_legacy_dlc"
    ws.mkdir(parents=True)
    (ws / "VERSION").write_text("0.0.43\n", encoding="utf-8")
    (root / "workstreams/core").mkdir(parents=True)
    (root / "workstreams/core/VERSION").write_text("0.0.45\n", encoding="utf-8")
    candidates = [("Data/PACK10_02.PAK", b"combined-pack10"), ("Data/PACK12.PAK", b"combined-pack12")]
    baselines = [("Data/PACK10_02.PAK", b"base-pack10"), ("Data/PACK12.PAK", b"base-pack12")]
    rows = []
    for (relative, candidate), (_, baseline) in zip(candidates, baselines):
        candidate_relative = f".local/build/quartet_legacy_dlc/test/{Path(relative).name}"
        write(root / candidate_relative, candidate)
        write(game / relative, baseline)
        rows.append({"relative_path": relative, "candidate_relative_path": candidate_relative, "candidate_size": len(candidate), "candidate_sha256": digest(candidate), "baseline_size": len(baseline), "baseline_sha256": digest(baseline)})
    acceptance = {"accepted_at_version": "0.0.43", "status": "accepted_for_metadata_only_core_pc00_pc01_payload_preview_handoff", "minimum_core_version": "0.0.42", "content_ids": ["costume_pc00_bkn", "costume_pc01_bkn"], "transaction_files": rows}
    (ws / TOOL.ACCEPTANCE_NAME).write_text(json.dumps(acceptance), encoding="utf-8")
    legacy = f"""package payloadpreview
const (\n legacyDLCSourceKind = "{TOOL.SOURCE_KIND}"\n legacyDLCHandoffRelative = "{TOOL.CURRENT_HANDOFF_PATH}"\n)\nfunc x() {{\n if handoff.Type != "{TOOL.CURRENT_TYPE}" || handoff.HandoffVersion != "{TOOL.CURRENT_HANDOFF_VERSION}" {{}}\n return artifacts, true, "validated dry PC00 BKN handoff; preview-only two-artifact contract"\n}}\n"""
    core_text = {
        TOOL.CORE_FILES[0]: b'{"catalog":true}\n',
        TOOL.CORE_FILES[1]: b'package payloadpreview\n',
        TOOL.CORE_FILES[2]: legacy.encode(),
        TOOL.CORE_FILES[3]: b'package payloadpreview\n',
    }
    for relative, data in core_text.items(): write(root / relative, data)
    return root, game

def test_build_and_validate_metadata_only_handoff(tmp_path: Path) -> None:
    root, game = project(tmp_path)
    report = TOOL.build_report(root, game)
    summary = TOOL.validate_report(report)
    assert summary["artifact_count"] == 2
    assert not any(path.suffix.casefold() == ".pak" for path in report.rglob("*"))

def test_changed_candidate_is_rejected(tmp_path: Path) -> None:
    root, game = project(tmp_path)
    path = root / ".local/build/quartet_legacy_dlc/test/PACK12.PAK"
    path.write_bytes(b"tampered")
    try:
        TOOL.build_report(root, game)
    except TOOL.HandoffError as exc:
        assert "mismatch" in str(exc)
    else:
        raise AssertionError("tampered candidate was accepted")

def test_changed_core_binding_is_rejected(tmp_path: Path) -> None:
    root, game = project(tmp_path)
    path = root / TOOL.CORE_FILES[2]
    path.write_text(path.read_text().replace(TOOL.CURRENT_HANDOFF_VERSION, "different"), encoding="utf-8")
    try:
        TOOL.build_report(root, game)
    except TOOL.HandoffError as exc:
        assert "binding changed" in str(exc)
    else:
        raise AssertionError("changed core binding was accepted")


def test_core_below_minimum_is_rejected(tmp_path: Path) -> None:
    root, game = project(tmp_path)
    (root / "workstreams/core/VERSION").write_text("0.0.41\n", encoding="utf-8")
    try:
        TOOL.build_report(root, game)
    except TOOL.HandoffError as exc:
        assert "too old" in str(exc)
    else:
        raise AssertionError("obsolete core version was accepted")
