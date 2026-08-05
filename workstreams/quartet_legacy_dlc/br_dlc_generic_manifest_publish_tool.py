#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

EXPECTED_CORE_VERSION = "0.0.47"
EXPECTED_DLC_VERSION = "0.0.44"
EXPECTED_MANIFEST_SHA256 = "4f8280c7c3ac8a1205c9daf90c0c08b64d06ee7c4fc1f94bec9f51a38ee75130"
ACTIVE_RELATIVE = Path(".local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json")
REPORT_RELATIVE = Path(".local/reports/quartet_legacy_dlc/generic_manifest_pc00_pc01_publication/PUBLICATION.json")

CORE_GUARDS = {
    "workstreams/core/contracts/quartet_legacy_dlc/GENERIC_ADAPTER_RETURN_CONTRACT.json": "7be5d5e0b9d59997cac0c3cdb3c053c10392d39f9e2facbeed29b8f4535fe316",
    "workstreams/core/contracts/quartet_legacy_dlc/MANIFEST_POLICY.md": "054c6231729db2b979ae2ea0e5e82c82d2aa4ab6c0ff20679599b75e575b0411",
    "workstreams/core/contracts/quartet_legacy_dlc/VALIDATED_QUARTET_LEGACY_DLC_PAYLOAD.schema.json": "e2162dfbe8f6b5a5f78a7ec7a2123ec6a11af6da01790c599d3483e497591fd0",
    "workstreams/core/contracts/quartet_legacy_dlc/examples/PC00_PC01.json": "4f8280c7c3ac8a1205c9daf90c0c08b64d06ee7c4fc1f94bec9f51a38ee75130",
    "workstreams/core/tools/validate_quartet_legacy_dlc_active_manifest.sh": "81044708177aa8c482f8dfd96a3bc293ae799d2dfe2cd5c060be22d13f87ad7d",
    "Blue_Reflection_Patcher/internal/plan/payloadpreview/legacy_dlc_policy.json": "17d31e43dd111caaa182a0a0567d2545fb510005e5cf6c8434307d4e014e011c",
}

EXPECTED_ARTIFACTS = {
    "Data/PACK10_02.PAK": {
        "candidate_relative_path": ".local/build/quartet_legacy_dlc/family_expansion/costume_pc00_pc01_bkn_dry/candidate/PACK10_02.PAK",
        "candidate_size": 11434188952,
        "candidate_sha256": "bcce30ec2e7b5c4253b8626578569a568d0579ad03075cff29ba03cdd03f7798",
        "baseline_size": 11402829898,
        "baseline_sha256": "e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302",
        "added": [
            "data/b1/x64/character/pc00/pc00_dlc_bkn.elixir.gz",
            "data/b1/x64/character/pc00/pc00_dlc_bkn.g1t",
            "data/b1/x64/character/pc01/pc01_dlc_bkn.elixir.gz",
            "data/b1/x64/character/pc01/pc01_dlc_bkn.g1t",
        ],
        "changed": [], "removed": [],
    },
    "Data/PACK12.PAK": {
        "candidate_relative_path": ".local/build/quartet_legacy_dlc/family_expansion/costume_pc00_pc01_bkn_dry/candidate/PACK12.PAK",
        "candidate_size": 26124665,
        "candidate_sha256": "145882cbe4c6d13ef03e7c92ece3082b2d4d0d000e1d2298e4a9c543cc2b9b9b",
        "baseline_size": 26124649,
        "baseline_sha256": "a108a22dd59116e79cf0fabcffd5d0427f72e13de267318869431d28717404f4",
        "added": [], "changed": ["saves/b1/chara/charabase.xml"], "removed": [],
    },
}

EXPECTED_EVIDENCE_RELATIVE = ".local/reports/quartet_legacy_dlc/bkn_dry_pc00_pc01_core_preview_handoff_evidence/DLC_BKN_DRY_PC00_PC01_CORE_PREVIEW_HANDOFF.json"
EXPECTED_EVIDENCE_SHA256 = "f9f93ad2dc8b9bfac0e84ebdec6823cdddbc4f68f40a23d3923f818317c16068"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

class ValidationError(RuntimeError):
    pass

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def regular_file(path: Path, label: str) -> None:
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise ValidationError(f"{label} missing: {path}") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValidationError(f"{label} must be a regular non-symlink file: {path}")

def resolve_relative_under(root: Path, relative: str, label: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValidationError(f"{label} is not a canonical relative path: {relative}")
    root_real = root.resolve(strict=True)
    path = root / rel
    regular_file(path, label)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root_real)
    except ValueError as exc:
        raise ValidationError(f"{label} escapes allowed root: {relative}") from exc
    return resolved

def check_file(path: Path, expected_size: int, expected_sha256: str, label: str) -> dict[str, Any]:
    regular_file(path, label)
    size = path.stat().st_size
    if size != expected_size:
        raise ValidationError(f"{label} size mismatch: expected {expected_size}, got {size}")
    digest = sha256_file(path)
    if digest != expected_sha256:
        raise ValidationError(f"{label} SHA-256 mismatch: expected {expected_sha256}, got {digest}")
    return {"path": str(path), "size": size, "sha256": digest}

def validate_manifest_semantics(manifest: dict[str, Any]) -> None:
    top_keys = {"type","format_version","family_id","generation","members","source_kind","target_id","artifacts","transaction","provenance","authorization"}
    if set(manifest) != top_keys:
        raise ValidationError(f"manifest top-level fields mismatch: {sorted(set(manifest) ^ top_keys)}")
    expected_scalars = {
        "type":"validated_quartet_legacy_dlc_payload", "format_version":1,
        "family_id":"bkn_dry", "generation":2,
        "members":["costume_pc00_bkn","costume_pc01_bkn"],
        "source_kind":"validated_quartet_legacy_dlc_handoff",
        "target_id":"blue_reflection_quartet",
    }
    for key, expected in expected_scalars.items():
        if manifest.get(key) != expected:
            raise ValidationError(f"manifest {key} mismatch: expected {expected!r}, got {manifest.get(key)!r}")
    arts = manifest.get("artifacts")
    if not isinstance(arts, list) or len(arts) != 2:
        raise ValidationError("manifest must contain exactly two artifacts")
    seen: set[str] = set()
    for art in arts:
        required = {"target_path","operation","candidate_relative_path","candidate_size","candidate_sha256","baseline_size","baseline_sha256","member_delta"}
        if not isinstance(art, dict) or set(art) != required:
            raise ValidationError("artifact fields mismatch")
        target = art["target_path"]
        if target in seen or target not in EXPECTED_ARTIFACTS:
            raise ValidationError(f"unexpected or duplicate target: {target}")
        seen.add(target)
        exp = EXPECTED_ARTIFACTS[target]
        if art["operation"] != "replace": raise ValidationError(f"wrong operation for {target}")
        for key in ("candidate_relative_path","candidate_size","candidate_sha256","baseline_size","baseline_sha256"):
            if art[key] != exp[key]: raise ValidationError(f"{target} {key} mismatch")
        delta = art["member_delta"]
        if not isinstance(delta, dict) or set(delta) != {"added","changed","removed"}:
            raise ValidationError(f"{target} member_delta fields mismatch")
        for key in ("added","changed","removed"):
            if delta[key] != exp[key]: raise ValidationError(f"{target} member_delta.{key} mismatch")
    if seen != set(EXPECTED_ARTIFACTS): raise ValidationError("artifact target set mismatch")
    if manifest.get("transaction") != {"group":"quartet_legacy_dlc_bkn_dry","all_or_none":True,"commit_enabled":False}:
        raise ValidationError("transaction policy mismatch")
    prov = manifest.get("provenance")
    if prov != {"workstream_id":"quartet_legacy_dlc","workstream_version":"0.0.43","evidence_relative_path":EXPECTED_EVIDENCE_RELATIVE,"evidence_sha256":EXPECTED_EVIDENCE_SHA256}:
        raise ValidationError("provenance mismatch")
    auth = manifest.get("authorization")
    expected_auth={"core_handoff_ready":True,"real_transaction_prepare_enabled":False,"real_transaction_commit_enabled":False,"candidate_installed":False,"profile_registered":False,"runtime_validated":False,"wet_variant_included":False,"game_modified":False}
    if auth != expected_auth: raise ValidationError("authorization mismatch")

def verify_core(project_root: Path) -> list[dict[str, Any]]:
    core_version=(project_root/"workstreams/core/VERSION").read_text().strip()
    if core_version != EXPECTED_CORE_VERSION:
        raise ValidationError(f"core version mismatch: expected {EXPECTED_CORE_VERSION}, got {core_version}")
    dlc_version=(project_root/"workstreams/quartet_legacy_dlc/VERSION").read_text().strip()
    if dlc_version != EXPECTED_DLC_VERSION:
        raise ValidationError(f"DLC workstream version mismatch: expected {EXPECTED_DLC_VERSION}, got {dlc_version}")
    rows=[]
    for relative, expected in CORE_GUARDS.items():
        path=resolve_relative_under(project_root,relative,"core contract")
        digest=sha256_file(path)
        if digest != expected:
            raise ValidationError(f"core contract changed: {relative}; expected {expected}, got {digest}")
        rows.append({"relative_path":relative,"sha256":digest})
    return rows

def validate_inputs(project_root: Path, game_dir: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    candidates=[]; baselines=[]
    for art in manifest["artifacts"]:
        target=art["target_path"]
        candidate=resolve_relative_under(project_root,art["candidate_relative_path"],f"candidate {target}")
        candidates.append(check_file(candidate,art["candidate_size"],art["candidate_sha256"],f"candidate {target}"))
        baseline=resolve_relative_under(game_dir,target,f"baseline {target}")
        baselines.append(check_file(baseline,art["baseline_size"],art["baseline_sha256"],f"baseline {target}"))
    evidence=resolve_relative_under(project_root,manifest["provenance"]["evidence_relative_path"],"provenance evidence")
    digest=sha256_file(evidence)
    if digest != manifest["provenance"]["evidence_sha256"]:
        raise ValidationError(f"provenance SHA-256 mismatch: expected {manifest['provenance']['evidence_sha256']}, got {digest}")
    return candidates, baselines, {"path":str(evidence),"size":evidence.stat().st_size,"sha256":digest}

def ensure_safe_parent(project_root: Path, target: Path) -> None:
    root=project_root.resolve(strict=True)
    rel=target.relative_to(project_root)
    current=project_root
    for part in rel.parts[:-1]:
        current=current/part
        if current.exists() and current.is_symlink():
            raise ValidationError(f"publication parent is a symlink: {current}")
    target.parent.mkdir(parents=True,exist_ok=True)
    parent_real=target.parent.resolve(strict=True)
    try: parent_real.relative_to(root)
    except ValueError as exc: raise ValidationError("publication directory escapes project root") from exc
    if target.exists() and target.is_symlink():
        raise ValidationError(f"ACTIVE manifest is a symlink: {target}")

def atomic_write_bytes(project_root: Path, target: Path, data: bytes, allow_different: bool=False) -> str:
    ensure_safe_parent(project_root,target)
    if target.exists():
        regular_file(target,"existing published manifest")
        old=target.read_bytes()
        if old==data: return "already_identical"
        if not allow_different:
            raise ValidationError(f"different ACTIVE manifest already exists: {target}")
    fd,tmp_name=tempfile.mkstemp(prefix=".ACTIVE.json.",dir=target.parent)
    tmp=Path(tmp_name)
    try:
        with os.fdopen(fd,"wb") as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.chmod(tmp,0o644)
        os.replace(tmp,target)
        dfd=os.open(target.parent,os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if tmp.exists(): tmp.unlink()
    return "published"

def write_report(project_root: Path, report: dict[str, Any]) -> None:
    target=project_root/REPORT_RELATIVE
    data=(json.dumps(report,indent=2)+"\n").encode()
    ensure_safe_parent(project_root,target)
    fd,tmp_name=tempfile.mkstemp(prefix=".PUBLICATION.json.",dir=target.parent)
    tmp=Path(tmp_name)
    try:
        with os.fdopen(fd,"wb") as fh:
            fh.write(data); fh.flush(); os.fsync(fh.fileno())
        os.chmod(tmp,0o644); os.replace(tmp,target)
        dfd=os.open(target.parent,os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if tmp.exists(): tmp.unlink()

def publish(project_root: Path, game_dir: Path, source_manifest: Path) -> dict[str, Any]:
    project_root=project_root.resolve(strict=True); game_dir=game_dir.resolve(strict=True)
    regular_file(source_manifest,"source active manifest")
    source_bytes=source_manifest.read_bytes(); source_sha=hashlib.sha256(source_bytes).hexdigest()
    if source_sha != EXPECTED_MANIFEST_SHA256:
        raise ValidationError(f"source manifest SHA-256 mismatch: expected {EXPECTED_MANIFEST_SHA256}, got {source_sha}")
    manifest=json.loads(source_bytes)
    validate_manifest_semantics(manifest)
    core_guards=verify_core(project_root)
    candidates,baselines,evidence=validate_inputs(project_root,game_dir,manifest)
    target=project_root/ACTIVE_RELATIVE
    result=atomic_write_bytes(project_root,target,source_bytes)
    published_sha=sha256_file(target)
    if published_sha != EXPECTED_MANIFEST_SHA256:
        raise ValidationError("published ACTIVE manifest hash mismatch")
    report={
      "type":"br_quartet_legacy_dlc_active_manifest_publication",
      "format_version":1,"status":"pass","publication_result":result,
      "core_version":EXPECTED_CORE_VERSION,"dlc_version":EXPECTED_DLC_VERSION,
      "active_manifest_relative_path":str(ACTIVE_RELATIVE),"active_manifest_sha256":published_sha,
      "family_id":"bkn_dry","generation":2,"members":["costume_pc00_bkn","costume_pc01_bkn"],
      "artifact_paths":["Data/PACK10_02.PAK","Data/PACK12.PAK"],
      "core_contract_guards":core_guards,"candidates":candidates,"baselines":baselines,"provenance":evidence,
      "commit_enabled":False,"transaction_prepare_called":False,"transaction_commit_called":False,
      "candidate_installed":False,"profile_registered":False,"runtime_validated":False,"game_modified":False,
    }
    write_report(project_root,report)
    return report

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root",required=True,type=Path)
    ap.add_argument("--game-dir",required=True,type=Path)
    ap.add_argument("--manifest",required=True,type=Path)
    args=ap.parse_args()
    try:
        report=publish(args.project_root,args.game_dir,args.manifest)
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}",file=__import__('sys').stderr); return 1
    print(json.dumps(report,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
