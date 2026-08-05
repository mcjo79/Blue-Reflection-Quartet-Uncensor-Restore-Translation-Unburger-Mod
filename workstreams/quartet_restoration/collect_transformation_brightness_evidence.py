#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

TOOL_VERSION = "0.0.88"
REPORT_NAME = "BR_quartet_restoration_transformation_brightness_evidence.tar.zst"
REPORT_DIR = "transformation_brightness_evidence"
REGISTRY_DIR = "core_profile_manifest_evidence"
STRUCTURAL_DIR = "structural_material_parameter_evidence"
PRESENTATION_DIR = "presentation_surface_evidence"
SHADER_DIR = "shader_effect_evidence"
BINARY_DIR = "binary_delta_evidence"

CHARACTER_TOKENS = {
    "yuzu", "yuzuki", "shijou", "shijo", "yuz", "yzk",
}
TRANSFORMATION_TOKENS = {
    "henshin", "transform", "transformation", "reflector", "rfl",
    "magicchange", "magic_change", "costumechange", "costume_change",
    "awakening", "awaken", "metamorph", "change",
}
BRIGHTNESS_TOKENS = {
    "bright", "brightness", "luminance", "luma", "exposure", "bloom",
    "glare", "flare", "emissive", "emission", "light", "lighting",
    "overbright", "overexposure", "hdr", "tone", "gamma", "radiance",
    "intensity", "white", "color", "colour",
}
BODY_TOKENS = {
    "body", "skin", "nude", "naked", "character", "chara", "chr",
    "model", "mesh", "face", "head",
}


class TransformationBrightnessEvidenceError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TransformationBrightnessEvidenceError(message)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing required JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransformationBrightnessEvidenceError(f"cannot read JSON {path}: {exc}") from exc
    require(isinstance(data, dict), f"JSON root must be an object: {path}")
    return data


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise TransformationBrightnessEvidenceError(f"missing required TSV: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def folded(value: Any) -> str:
    return str(value or "").strip().casefold()


def token_hits(text: str, tokens: set[str]) -> list[str]:
    value = folded(text)
    normalized = re.sub(r"[^a-z0-9]+", "_", value)
    pieces = {piece for piece in normalized.split("_") if piece}
    hits: set[str] = set()
    for token in tokens:
        if len(token) <= 3:
            if token in pieces:
                hits.add(token)
        elif token in normalized:
            hits.add(token)
    return sorted(hits)


def merged_text(row: dict[str, Any], fields: Iterable[str]) -> str:
    return " ".join(str(row.get(field, "")) for field in fields)


def score_candidate(*, character: list[str], transform: list[str], brightness: list[str], body: list[str], changed: bool, technical: bool) -> int:
    score = 0
    if character:
        score += 4
    if transform:
        score += 3
    if brightness:
        score += 3
    if body:
        score += 1
    if changed:
        score += 1
    if technical:
        score += 1
    return score


def classify_candidate(character: list[str], transform: list[str], brightness: list[str], body: list[str]) -> str:
    if character and transform and brightness:
        return "yuzu_transformation_brightness_direct_lead"
    if transform and brightness and body:
        return "transformation_body_brightness_lead"
    if character and brightness:
        return "yuzu_brightness_lead"
    if character and transform:
        return "yuzu_transformation_locator"
    if transform and brightness:
        return "transformation_brightness_lead"
    if transform and body:
        return "transformation_body_locator"
    if brightness:
        return "generic_brightness_control"
    return "transformation_or_character_locator"


def validate_registry(report_root: Path) -> dict[str, Any]:
    summary = load_json(report_root / REGISTRY_DIR / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_core_profile_manifest_evidence_summary", "core report has unexpected type")
    require(int(summary.get("profile_rows", -1)) == 15, "core report must contain 15 profiles")
    require(int(summary.get("pack11_profile_rows", -1)) == 12, "core report must contain 12 PACK11 profiles")
    require(int(summary.get("pack10_01_profile_rows", -1)) == 2, "core report must contain 2 PACK10_01 profiles")
    require(int(summary.get("pack10_03_profile_rows", -1)) == 1, "core report must contain 1 PACK10_03 profile")
    require(int(summary.get("runtime_validated_profile_rows", -1)) == 0, "registry profiles must remain runtime-unvalidated")
    return summary


def validate_structural_stage(report_root: Path) -> dict[str, Any]:
    root = report_root / STRUCTURAL_DIR
    summary = load_json(root / "SUMMARY.json")
    require(summary.get("type") == "br_quartet_restoration_structural_material_parameter_evidence_summary", "stage-75 report has unexpected type")
    require(int(summary.get("audited_member_rows", -1)) == 16, "stage-75 report must audit 16 G1M members")
    require(int(summary.get("record_rows", -1)) == 48, "stage-75 report must contain 48 structural records")
    require(int(summary.get("record_validation_failures", -1)) == 0, "stage-75 report contains record validation failures")
    require(int(summary.get("skipped_rows", -1)) == 0, "stage-75 report contains skipped members")
    require(int(summary.get("unique_followup_candidate_member_rows", -1)) == 0, "stage-75 unexpectedly contains a build-ready unique material candidate")

    records = read_tsv(root / "STRUCTURAL_PARAMETER_RECORDS.tsv")
    candidates = read_tsv(root / "STRUCTURAL_MEMBER_CANDIDATES.tsv")
    atcolor = [row for row in records if folded(row.get("parameter_name")) == "atcolor"]
    require(len(atcolor) == 1, "stage-75 must contain exactly one atColor record")
    require(atcolor[0].get("structural_class") == "unique_scene_local_structure", "atColor must remain the unique scene-local record")
    unique_rows = [row for row in candidates if row.get("candidate_mode") == "unique_only" and row.get("selected_row_count") == "1"]
    require(len(unique_rows) == 1, "stage-75 must contain one unique-only candidate attempt")
    require(unique_rows[0].get("candidate_available") == "False", "stage-75 unique-only candidate must remain unavailable")
    require("no target mapping" in folded(unique_rows[0].get("unresolved_reasons")), "stage-75 unique-only failure must be the unmapped source block")
    recurrent_main = [
        row for row in candidates
        if row.get("candidate_mode") == "recurrent_only"
        and folded(row.get("member_name")) == "obj-s89-s-hinako-bath-room-01_hi.g1m"
    ]
    require(len(recurrent_main) == 1, "stage-75 must contain the main bathroom recurrent-only attempt")
    require(int(recurrent_main[0].get("distance_improvement", "0")) < 0, "recurrent-only main bathroom inverse must not be promoted")
    return summary


def iter_difference_rows(report_root: Path) -> Iterable[dict[str, Any]]:
    differences = report_root / "differences"
    require(differences.is_dir(), f"missing corrected difference reports: {differences}")
    files = sorted(differences.glob("*.json"))
    require(bool(files), "no corrected difference reports found")
    for path in files:
        report = load_json(path)
        pair_id = str(report.get("source_archive_group", path.stem))
        for entry in report.get("entries", []):
            if not isinstance(entry, dict):
                continue
            source = entry.get("source") or {}
            target = entry.get("target") or {}
            yield {
                "pair_id": pair_id,
                "normalized_path": entry.get("normalized_path", ""),
                "classification": entry.get("classification", ""),
                "scope_status": entry.get("scope_status", ""),
                "source_size": source.get("size", ""),
                "target_size": target.get("size", ""),
            }


def normalize_evidence_row(source_table: str, row: dict[str, str]) -> dict[str, Any]:
    fields = (
        "normalized_path", "source_member_name", "target_member_name", "member_name",
        "member_key", "setting_path", "source_value", "target_value", "keyword_hits",
        "token_key", "source_token", "target_token", "review_basis", "evidence_basis",
        "prototype_action", "domain", "rule_id", "classification", "status",
    )
    text = merged_text(row, fields)
    character = token_hits(text, CHARACTER_TOKENS)
    transform = token_hits(text, TRANSFORMATION_TOKENS)
    brightness = token_hits(text, BRIGHTNESS_TOKENS)
    body = token_hits(text, BODY_TOKENS)
    change_value = folded(row.get("classification") or row.get("status") or row.get("delta"))
    changed = change_value not in {"", "identical", "unchanged"}
    technical = source_table in {
        "LIGHTSHAFT_PRESET_SETTINGS.tsv", "LIGHTSHAFT_EFFECT_MEMBERS.tsv",
        "FOCUSED_SHADER_EFFECT_REVIEW.tsv", "PAYLOAD_BINARY_DELTA.tsv",
        "RESTORATION_PROTOTYPE_CANDIDATES.tsv",
    }
    score = score_candidate(
        character=character,
        transform=transform,
        brightness=brightness,
        body=body,
        changed=changed,
        technical=technical,
    )
    return {
        "evidence_source": source_table,
        "pair_id": row.get("pair_id", ""),
        "candidate_id": row.get("candidate_id", ""),
        "domain": row.get("domain", ""),
        "priority": row.get("priority") or row.get("review_priority", ""),
        "normalized_path": row.get("normalized_path", ""),
        "member_name": row.get("target_member_name") or row.get("source_member_name") or row.get("member_name", ""),
        "member_key": row.get("member_key", ""),
        "setting_path": row.get("setting_path", ""),
        "source_value": row.get("source_value", ""),
        "target_value": row.get("target_value", ""),
        "change_classification": row.get("classification") or row.get("status") or row.get("delta", ""),
        "character_hits": ",".join(character),
        "transformation_hits": ",".join(transform),
        "brightness_hits": ",".join(brightness),
        "body_hits": ",".join(body),
        "evidence_score": score,
        "lead_classification": classify_candidate(character, transform, brightness, body),
        "review_status": "user_reported_transformation_brightness_lead_requires_asset_and_runtime_confirmation",
    }


def collect_existing_evidence(report_root: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    tables: list[tuple[Path, str]] = [
        (report_root / PRESENTATION_DIR / "LIGHTSHAFT_ASSET_CANDIDATES.tsv", "LIGHTSHAFT_ASSET_CANDIDATES.tsv"),
        (report_root / PRESENTATION_DIR / "LIGHTSHAFT_PRESET_SETTINGS.tsv", "LIGHTSHAFT_PRESET_SETTINGS.tsv"),
        (report_root / PRESENTATION_DIR / "LIGHTSHAFT_EFFECT_MEMBERS.tsv", "LIGHTSHAFT_EFFECT_MEMBERS.tsv"),
        (report_root / SHADER_DIR / "FOCUSED_SHADER_EFFECT_REVIEW.tsv", "FOCUSED_SHADER_EFFECT_REVIEW.tsv"),
        (report_root / BINARY_DIR / "PAYLOAD_BINARY_DELTA.tsv", "PAYLOAD_BINARY_DELTA.tsv"),
        (report_root / BINARY_DIR / "RESTORATION_PROTOTYPE_CANDIDATES.tsv", "RESTORATION_PROTOTYPE_CANDIDATES.tsv"),
    ]
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for path, label in tables:
        source_rows = read_tsv(path)
        counts[label] = len(source_rows)
        for row in source_rows:
            normalized = normalize_evidence_row(label, row)
            # Keep direct character/transform hits, or technical brightness rows as controls.
            if normalized["character_hits"] or normalized["transformation_hits"] or normalized["brightness_hits"]:
                rows.append(normalized)
    return rows, counts


def build_report(project_root: Path, *, create_archive: bool = True) -> tuple[Path, Path | None, dict[str, Any]]:
    report_root = project_root / ".local/reports/quartet_restoration"
    registry_summary = validate_registry(report_root)
    structural_summary = validate_structural_stage(report_root)

    path_rows: list[dict[str, Any]] = []
    for row in iter_difference_rows(report_root):
        text = str(row.get("normalized_path", ""))
        character = token_hits(text, CHARACTER_TOKENS)
        transform = token_hits(text, TRANSFORMATION_TOKENS)
        brightness = token_hits(text, BRIGHTNESS_TOKENS)
        body = token_hits(text, BODY_TOKENS)
        if not (character or transform or brightness):
            continue
        changed = folded(row.get("classification")) not in {"", "identical", "unchanged"}
        score = score_candidate(
            character=character,
            transform=transform,
            brightness=brightness,
            body=body,
            changed=changed,
            technical=False,
        )
        path_rows.append({
            **row,
            "character_hits": ",".join(character),
            "transformation_hits": ",".join(transform),
            "brightness_hits": ",".join(brightness),
            "body_hits": ",".join(body),
            "evidence_score": score,
            "lead_classification": classify_candidate(character, transform, brightness, body),
            "review_status": "path_locator_only_not_censorship_proof",
        })

    evidence_rows, source_table_counts = collect_existing_evidence(report_root)
    focused_rows = [
        row for row in evidence_rows
        if int(row.get("evidence_score", 0)) >= 4
        and (
            row.get("character_hits")
            or row.get("transformation_hits")
            or (row.get("brightness_hits") and row.get("body_hits"))
        )
    ]
    focused_path_rows = [row for row in path_rows if int(row.get("evidence_score", 0)) >= 4]

    combined: list[dict[str, Any]] = []
    for row in focused_path_rows:
        combined.append({
            "evidence_source": "corrected_difference_path",
            "pair_id": row.get("pair_id", ""),
            "candidate_id": "",
            "domain": "",
            "priority": "",
            "normalized_path": row.get("normalized_path", ""),
            "member_name": "",
            "member_key": "",
            "setting_path": "",
            "source_value": "",
            "target_value": "",
            "change_classification": row.get("classification", ""),
            "character_hits": row.get("character_hits", ""),
            "transformation_hits": row.get("transformation_hits", ""),
            "brightness_hits": row.get("brightness_hits", ""),
            "body_hits": row.get("body_hits", ""),
            "evidence_score": row.get("evidence_score", 0),
            "lead_classification": row.get("lead_classification", ""),
            "review_status": row.get("review_status", ""),
        })
    combined.extend(focused_rows)

    # Deterministic dedupe across report tables while retaining source provenance.
    deduped: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in combined:
        key = (
            str(row.get("evidence_source", "")),
            str(row.get("normalized_path", "")),
            str(row.get("member_name", "")),
            str(row.get("member_key", "")),
            str(row.get("setting_path", "")),
            str(row.get("change_classification", "")),
        )
        previous = deduped.get(key)
        if previous is None or int(row.get("evidence_score", 0)) > int(previous.get("evidence_score", 0)):
            deduped[key] = row
    review_rows = sorted(
        deduped.values(),
        key=lambda row: (-int(row.get("evidence_score", 0)), str(row.get("normalized_path", "")).casefold(), str(row.get("member_name", "")).casefold()),
    )

    output = report_root / REPORT_DIR
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    path_fields = [
        "pair_id", "normalized_path", "classification", "scope_status", "source_size", "target_size",
        "character_hits", "transformation_hits", "brightness_hits", "body_hits", "evidence_score",
        "lead_classification", "review_status",
    ]
    evidence_fields = [
        "evidence_source", "pair_id", "candidate_id", "domain", "priority", "normalized_path",
        "member_name", "member_key", "setting_path", "source_value", "target_value",
        "change_classification", "character_hits", "transformation_hits", "brightness_hits",
        "body_hits", "evidence_score", "lead_classification", "review_status",
    ]
    write_tsv(output / "TRANSFORMATION_BRIGHTNESS_ASSET_PATHS.tsv", path_fields, sorted(path_rows, key=lambda row: (-int(row["evidence_score"]), str(row["normalized_path"]).casefold())))
    write_tsv(output / "TRANSFORMATION_BRIGHTNESS_EXISTING_EVIDENCE.tsv", evidence_fields, sorted(evidence_rows, key=lambda row: (-int(row["evidence_score"]), str(row["normalized_path"]).casefold(), str(row["member_name"]).casefold())))
    write_tsv(output / "TRANSFORMATION_BRIGHTNESS_FOCUSED_REVIEW.tsv", evidence_fields, review_rows)
    write_tsv(output / "TRANSFORMATION_BRIGHTNESS_SOURCE_TABLES.tsv", ["table_name", "source_row_count"], [
        {"table_name": name, "source_row_count": count} for name, count in sorted(source_table_counts.items())
    ])

    lead_counts = Counter(str(row.get("lead_classification", "")) for row in review_rows)
    yuzu_rows = [row for row in review_rows if row.get("character_hits")]
    transformation_rows = [row for row in review_rows if row.get("transformation_hits")]
    brightness_rows = [row for row in review_rows if row.get("brightness_hits")]
    direct_rows = [row for row in review_rows if row.get("lead_classification") == "yuzu_transformation_brightness_direct_lead"]

    summary = {
        "type": "br_quartet_restoration_transformation_brightness_evidence_summary",
        "format_version": 1,
        "tool_version": TOOL_VERSION,
        "source_registry_tool_version": registry_summary.get("tool_version"),
        "source_structural_material_tool_version": structural_summary.get("tool_version"),
        "status": "user_reported_transformation_body_brightness_lead_located_in_existing_static_evidence_no_payload_written_runtime_deferred",
        "registry_profile_rows": 15,
        "stage75_audited_member_rows": 16,
        "stage75_structural_record_rows": 48,
        "stage75_unique_followup_candidate_member_rows": 0,
        "stage75_conclusion": "atColor remains evidence-only because source shader block 5 has no safe target mapping; recurrent mesh-blend inverses are controls and the main bathroom inverse moves farther from Original",
        "user_reported_lead": "Quartet may increase body brightness during magical transformations; the effect is reportedly most noticeable for Yuzu/Yuzuki.",
        "path_locator_rows": len(path_rows),
        "existing_evidence_rows": len(evidence_rows),
        "focused_review_rows": len(review_rows),
        "yuzu_or_yuzuki_rows": len(yuzu_rows),
        "transformation_rows": len(transformation_rows),
        "brightness_rows": len(brightness_rows),
        "direct_yuzu_transformation_brightness_rows": len(direct_rows),
        "lead_classification_counts": dict(sorted(lead_counts.items())),
        "source_table_counts": dict(sorted(source_table_counts.items())),
        "policy": {
            "installed_game_modified": False,
            "render_payload_written": False,
            "shader_or_effect_payload_written": False,
            "parent_container_rebuilt": False,
            "pak_repacked": False,
            "core_registry_modified": False,
            "profile_activated": False,
            "runtime_validation_inferred": False,
            "censorship_semantics_inferred": False,
            "user_report_treated_as_confirmed_fact": False,
            "canary_track_modified": False,
        },
        "next_action": (
            "Upload this report. If one or more Yuzu/transformation brightness candidates are localized, build a separate read-only occurrence and asset-family audit that compares Original and Quartet render members, presets and event bindings. Do not restore a global bloom or exposure setting without scene-specific binding and exact rollback."
        ),
    }
    atomic_json(output / "SUMMARY.json", summary)

    archive: Path | None = None
    if create_archive:
        archive = report_root / REPORT_NAME
        if archive.exists():
            archive.unlink()
        completed = subprocess.run(
            ["tar", "--zstd", "-cf", str(archive), "-C", str(report_root), REPORT_DIR],
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            raise TransformationBrightnessEvidenceError(completed.stderr.strip() or "tar failed")
    return output, archive, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect read-only evidence for reported body-brightness changes during magical transformations")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--no-report-archive", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve()
    output, archive, summary = build_report(project_root, create_archive=not args.no_report_archive)
    print(f"Validated registry profiles: {summary['registry_profile_rows']}")
    print(f"Stage-75 audited G1M members: {summary['stage75_audited_member_rows']}")
    print(f"Asset path locators: {summary['path_locator_rows']}")
    print(f"Existing evidence rows: {summary['existing_evidence_rows']}")
    print(f"Focused transformation-brightness rows: {summary['focused_review_rows']}")
    print(f"Direct Yuzu transformation-brightness rows: {summary['direct_yuzu_transformation_brightness_rows']}")
    print(f"Report directory: {output}")
    if archive:
        print(f"Report: {archive}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TransformationBrightnessEvidenceError as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1)
