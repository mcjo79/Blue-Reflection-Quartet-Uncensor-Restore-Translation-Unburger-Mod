#!/usr/bin/env python3
import argparse
import copy
import json
from pathlib import Path

EXPECTED_ARTIFACTS = ["Data/PACK10_02.PAK", "Data/PACK12.PAK"]
EXPECTED_SOURCE_KIND = "validated_quartet_legacy_dlc_handoff"


def validate_preview_root(root: Path) -> dict:
    preview = json.loads((root / "PAYLOAD_PREVIEW.json").read_text())
    before = json.loads((root / "TRANSACTION_STATUS_BEFORE.json").read_text())
    after = json.loads((root / "TRANSACTION_STATUS_AFTER.json").read_text())
    before_cmp, after_cmp = copy.deepcopy(before), copy.deepcopy(after)
    before_cmp.pop("generated_utc", None)
    after_cmp.pop("generated_utc", None)

    errors = []
    rejections = []
    if preview.get("status") != "ready":
        errors.append(f"preview status={preview.get('status')}")
    if preview.get("commit_enabled") is not False:
        errors.append("CommitEnabled is not false")

    targets = preview.get("targets") or []
    if len(targets) != 1:
        errors.append(f"expected one target, got {len(targets)}")

    artifacts = []
    if targets:
        target = targets[0]
        if target.get("selected_modules") != ["quartet_legacy_dlc"]:
            errors.append("selected modules mismatch")
        for module in target.get("modules") or []:
            if module.get("source_kind") != EXPECTED_SOURCE_KIND:
                errors.append("source kind mismatch")
            if not module.get("ready"):
                rejection = {
                    "module_id": module.get("module_id"),
                    "connection_status": module.get("connection_status"),
                    "reason": module.get("reason") or "module rejected without a reason",
                }
                rejections.append(rejection)
                errors.append(f"module not ready: {rejection['reason']}")
            artifacts.extend(module.get("artifacts") or [])

    paths = sorted(a.get("relative_path") for a in artifacts)
    if paths != EXPECTED_ARTIFACTS:
        errors.append(f"artifact paths mismatch: {paths}")
    if before_cmp != after_cmp:
        errors.append("transaction state changed")
    if (root / "GAME_TARGET_STAT_BEFORE.tsv").read_text() != (root / "GAME_TARGET_STAT_AFTER.tsv").read_text():
        errors.append("game target metadata changed")

    result = {
        "type": "br_quartet_legacy_dlc_generic_manifest_canonical_preview",
        "format_version": 2,
        "status": "pass" if not errors else "fail",
        "preview_status": preview.get("status"),
        "artifact_count": len(artifacts),
        "artifact_paths": paths,
        "all_or_none_ready": not errors,
        "source_kind": EXPECTED_SOURCE_KIND,
        "commit_enabled": preview.get("commit_enabled"),
        "transaction_function_called": False,
        "transaction_prepare_called": False,
        "transaction_commit_called": False,
        "game_modified": False,
        "structured_rejection_reason": rejections[0]["reason"] if rejections else None,
        "policy_rejections": rejections,
        "errors": errors,
    }
    (root / "VALIDATION.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = validate_preview_root(Path(args.output_dir))
    if result["status"] != "pass":
        print(json.dumps({
            "status": "fail",
            "structured_rejection_reason": result["structured_rejection_reason"],
            "errors": result["errors"],
        }, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
