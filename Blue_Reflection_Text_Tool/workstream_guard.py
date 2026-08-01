#!/usr/bin/env python3
"""Validate Blue Reflection parallel workstream ownership and current versions."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    errors: list[str] = []
    rows = read_tsv(root / "config/workstreams.tsv")
    ownership = read_tsv(root / "config/workstream_ownership.tsv")

    ids = [row["workstream_id"] for row in rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate workstream IDs")
    known = set(ids)

    for row in ownership:
        if row["workstream_id"] not in known:
            errors.append(
                f"ownership references unknown workstream: {row['workstream_id']}"
            )
        if not row["path_prefix"]:
            errors.append("empty ownership path prefix")

    current_versions: dict[str, str] = {}
    initial_versions: dict[str, str] = {}
    for row in rows:
        workstream_id = row["workstream_id"]
        version_path = root / "workstreams" / workstream_id / "VERSION"
        if not version_path.is_file():
            errors.append(f"missing version file: {version_path}")
            continue
        current_versions[workstream_id] = version_path.read_text(
            encoding="utf-8"
        ).strip()
        initial_versions[workstream_id] = row.get("initial_version", "").strip()

        entry = root / row["entrypoint"]
        if not entry.is_file():
            errors.append(f"missing workstream entrypoint: {entry}")

    # VERSION files are authoritative. The registry stores only the version at
    # which the public repository baseline was created, so independent updates
    # never require a core-owned TSV edit.
    report = {
        "type": "br_parallel_workstream_validation",
        "format_version": 2,
        "status": "ok" if not errors else "failed",
        "workstreams": ids,
        "current_versions": current_versions,
        "initial_versions": initial_versions,
        "version_source_of_truth": "workstreams/<id>/VERSION",
        "ownership_rules": len(ownership),
        "independent_update_order": True,
        "same_project_root": True,
        "errors": errors,
    }

    out = Path(args.output).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Workstream validation report: {out}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Parallel workstream architecture is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
