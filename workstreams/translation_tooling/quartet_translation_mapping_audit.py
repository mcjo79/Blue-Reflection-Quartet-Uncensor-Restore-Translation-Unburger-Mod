#!/usr/bin/env python3
"""Audit Quartet translation mapping and optional loose-build output.

Read-only: this script never rewrites translation records or game files.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional


def load_tool(project_root: Path):
    path = project_root / "Blue_Reflection_Text_Tool/br_text_tool.py"
    spec = importlib.util.spec_from_file_location("br_text_tool_runtime", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load translation tool: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def audit(project_root: Path, verify_loose: bool) -> dict[str, Any]:
    tool = load_tool(project_root)
    policy = tool.load_quartet_target_policy(project_root)
    translation_root = project_root / "titles/blue_reflection/translation"
    manifest = json.loads(
        (translation_root / "translation_manifest.json").read_text(encoding="utf-8")
    )
    loose_root = project_root / ".local/build/translation/loose/blue_reflection_quartet"

    action_counts: Counter[str] = Counter()
    unit_counts: Counter[str] = Counter()
    target_only: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    used_policy_ids: set[str] = set()
    mapped_records = 0
    loose_verified_records = 0

    for summary in manifest.get("units", []):
        unit_path = translation_root / summary["path"]
        unit = tool.load_unit(unit_path)
        target = unit.get("targets", {}).get(tool.QUARTET_TARGET_ID)
        if not isinstance(target, dict) or not target.get("template_path"):
            continue
        unit_counts[unit["type"]] += 1
        target_path = project_root / target["template_path"]
        source = unit.get("source", {})
        quartet_jp_value = source.get("auxiliary_jp_path") or source.get("jp_path")
        if not isinstance(quartet_jp_value, str):
            errors.append({"unit": summary["path"], "error": "missing_quartet_jp_template"})
            continue
        quartet_jp_path = project_root / quartet_jp_value

        if unit["type"] == "br_event_translation_unit":
            target_en = tool.parse_ebm(target_path)
            target_jp = tool.parse_ebm(quartet_jp_path)
            en_to_jp, _ = tool.align_messages(target_en, target_jp)
            en_values = [row.text for row in target_en.messages]
            jp_values = [row.text for row in target_jp.messages]
            keys = [f"index:{i}:msg_id:{row.msg_id}" for i, row in enumerate(target_en.messages)]
            parser = tool.parse_ebm
            output_values = lambda parsed: [row.text for row in parsed.messages]
        else:
            target_en = tool.parse_xml_table(target_path)
            target_jp = tool.parse_xml_table(quartet_jp_path)
            en_to_jp, _ = tool.align_rows(target_en, target_jp)
            en_values = [row.text for row in target_en.rows]
            jp_values = [row.text for row in target_jp.rows]
            keys = [f"{tool.row_key(row)[0]}:{tool.row_key(row)[1]}" for row in target_en.rows]
            parser = tool.parse_xml_table
            output_values = lambda parsed: [row.text for row in parsed.rows]

        output: Optional[list[str]] = None
        if verify_loose:
            try:
                _, _, archive_stem, internal_path, _ = tool.parse_workspace_template(
                    project_root, target["template_path"]
                )
                output_path = loose_root / archive_stem / internal_path
                if not output_path.is_file():
                    raise FileNotFoundError(output_path)
                output = output_values(parser(output_path))
                if len(output) != len(en_values):
                    raise ValueError("output_count_mismatch")
            except Exception as exc:  # report all verification failures together
                errors.append({
                    "unit": summary["path"],
                    "error": "loose_output_unavailable",
                    "detail": str(exc),
                })

        mapped_indices: set[int] = set()
        for record in unit["records"]:
            target_index = record.get("alignment", {}).get("target_indices", {}).get(
                tool.QUARTET_TARGET_ID
            )
            if target_index is None:
                continue
            if not isinstance(target_index, int) or not (0 <= target_index < len(en_values)):
                errors.append({
                    "unit": summary["path"],
                    "logical_id": record.get("logical_id"),
                    "error": "invalid_target_index",
                    "target_index": target_index,
                })
                continue
            mapped_indices.add(target_index)
            mapped_records += 1
            jp_index = en_to_jp[target_index] if target_index < len(en_to_jp) else None
            if jp_index is None:
                errors.append({
                    "unit": summary["path"],
                    "logical_id": record.get("logical_id"),
                    "error": "target_en_without_target_jp",
                    "target_index": target_index,
                })
                continue
            try:
                adapted, action = tool.adapt_quartet_text(
                    record=record,
                    editable=tool.validate_record_text(record, unit_path),
                    target_jp=jp_values[jp_index],
                    target_en=en_values[target_index],
                    quartet_policy=policy,
                )
                action_counts[action] += 1
                if action not in {"shared_exact", "redacted_target_import_allowed"}:
                    used_policy_ids.add(str(record.get("logical_id")))
                expected = en_values[target_index] if adapted in {None, ""} else adapted
                if output is not None:
                    if output[target_index] != expected:
                        raise ValueError("loose_output_text_mismatch")
                    loose_verified_records += 1
            except Exception as exc:
                errors.append({
                    "unit": summary["path"],
                    "logical_id": record.get("logical_id"),
                    "target_index": target_index,
                    "error": "adaptation_or_output_verification_failed",
                    "detail": str(exc),
                })

        for index, text in enumerate(en_values):
            if index not in mapped_indices:
                target_only.append({
                    "unit": summary["path"],
                    "target_index": index,
                    "target_key": keys[index],
                    "target_en": text,
                })
                if output is not None:
                    if output[index] != text:
                        errors.append({
                            "unit": summary["path"],
                            "target_index": index,
                            "error": "target_only_record_changed",
                        })
                    else:
                        loose_verified_records += 1

    policy_ids = set(policy["records"])
    stale_policy = sorted(policy_ids - used_policy_ids)
    missing_policy = sorted(used_policy_ids - policy_ids)
    if stale_policy:
        errors.append({"error": "stale_policy_records", "logical_ids": stale_policy})
    if missing_policy:
        errors.append({"error": "missing_policy_records", "logical_ids": missing_policy})

    report = {
        "type": "br_quartet_translation_mapping_audit",
        "format_version": 1,
        "status": "ok" if not errors else "blocked",
        "project_root": "<PROJECT_ROOT>",
        "policy_path": tool.QUARTET_POLICY_RELATIVE.as_posix(),
        "production_text_source": "record.en",
        "translation_records_modified": 0,
        "game_files_modified": 0,
        "verify_loose_build": verify_loose,
        "summary": {
            "units": sum(unit_counts.values()),
            "unit_type_counts": dict(sorted(unit_counts.items())),
            "mapped_records": mapped_records,
            "target_only_records": len(target_only),
            "policy_records": len(policy_ids),
            "policy_records_used": len(used_policy_ids),
            "action_counts": dict(sorted(action_counts.items())),
            "loose_records_verified": loose_verified_records,
            "errors": len(errors),
        },
        "target_only_records": target_only,
        "errors": errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--verify-loose-build", action="store_true")
    args = parser.parse_args()
    root = Path(args.project_root).expanduser().resolve()
    report = audit(root, args.verify_loose_build)
    atomic_json(Path(args.report).expanduser().resolve(), report)
    summary = report["summary"]
    print("Quartet translation mapping audit")
    print(f"Status: {report['status']}")
    print(f"Mapped records: {summary['mapped_records']}")
    print(f"Target-only records preserved: {summary['target_only_records']}")
    print(f"Policy records: {summary['policy_records_used']}/{summary['policy_records']}")
    print(f"Actions: {summary['action_counts']}")
    if args.verify_loose_build:
        print(f"Loose records verified: {summary['loose_records_verified']}")
    print(f"Report: {Path(args.report).expanduser().resolve()}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
