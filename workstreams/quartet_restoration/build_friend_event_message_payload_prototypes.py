#!/usr/bin/env python3
"""Build local, metadata-preserving EBM prototypes for scene-wide FE dash placeholders.

Stage 57 proved that 94 FE scenes retain their record counts, msg_id sequences,
non-text metadata and sibling EBD while every Quartet language copy consists of
literal '-' payloads.  This stage reconstructs local EBM candidates for the
languages that have an Original source (JP, EN and Traditional Chinese), while
preserving the Quartet EBM container/record metadata exactly.  Simplified
Chinese remains explicitly unresolved because Original has no source copy.

Candidates are written only below .local/build/quartet_restoration.  No PAK,
registry, translation JSON, installed-game file or activation state is changed.
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

import collect_fe01_message_placeholder_evidence as stage57

TOOL_VERSION = "0.0.66"
STAGE57_TOOL_VERSION = "0.0.65"
REPORT_NAME = "BR_quartet_restoration_friend_event_message_payload_prototype_evidence.tar.zst"
EVIDENCE_DIR_NAME = "friend_event_message_payload_prototype_evidence"
STAGE57_REPORT_NAME = "BR_quartet_restoration_fe01_message_placeholder_evidence.tar.zst"
STAGE57_DIR_NAME = "fe01_message_placeholder_evidence"
INVENTORY_REPORT_NAME = "BR_quartet_restoration_inventory_and_diff.tar.zst"
PROTOTYPE_SUBDIR = Path("prototypes/friend_event_message_payload")
RESTORED_LANGUAGE_PAIRS = (
    ("event_jp", "event_jp"),
    ("event_en", "event_en"),
    ("event_tc", "event_tc"),
)
UNRESOLVED_TARGET_LANGUAGES = ("event_sc",)
EXPECTED_SAFE_SCENES = 94
EXPECTED_FAMILIES = (
    "fe01", "fe03", "fe04", "fe05", "fe06", "fe07", "fe08",
    "fe09", "fe10", "fe11", "fe12", "fe13", "fe14",
)


class FriendEventMessagePrototypeError(RuntimeError):
    pass


def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def parse_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    if not path.is_file():
        if required:
            raise FriendEventMessagePrototypeError(f"missing prerequisite table: {path}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FriendEventMessagePrototypeError(f"missing prerequisite JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FriendEventMessagePrototypeError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise FriendEventMessagePrototypeError(f"expected JSON object: {path}")
    return data


def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise FriendEventMessagePrototypeError(f"unsafe report archive member: {raw}")
    return path.as_posix()


def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise FriendEventMessagePrototypeError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(archive)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if listed.returncode:
        raise FriendEventMessagePrototypeError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {
        PurePosixPath(safe_member_name(line.strip())).parts[0]
        for line in listed.stdout.splitlines() if line.strip()
    }
    if len(roots) != 1:
        raise FriendEventMessagePrototypeError(
            f"expected one report root in {archive}, found {sorted(roots)}"
        )
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise FriendEventMessagePrototypeError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))


def locate_named_root(report_root: Path, dirname: str, archive_name: str, temporary: Path) -> Path:
    direct = report_root / dirname
    return direct if direct.is_dir() else extract_archive(report_root / archive_name, temporary)


def locate_inventory_root(report_root: Path, temporary: Path) -> Path:
    if (report_root / "inventories").is_dir() and (report_root / "differences").is_dir():
        return report_root
    direct = report_root / "quartet_restoration"
    if (direct / "inventories").is_dir():
        return direct
    return extract_archive(report_root / INVENTORY_REPORT_NAME, temporary)


def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    done = subprocess.run(
        ["tar", "--zstd", "-cf", str(temporary), "-C", str(source_dir.parent), source_dir.name],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if done.returncode:
        raise FriendEventMessagePrototypeError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(temporary, output)


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def atomic_json(path: Path, data: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def metadata_tuple(message: Any) -> tuple[object, ...]:
    return stage57.metadata_tuple(message)


def metadata_sequence(messages: Sequence[Any]) -> tuple[tuple[object, ...], ...]:
    return tuple(metadata_tuple(message) for message in messages)


def target_member_path(event_id: str, language: str) -> str:
    family = event_id.split("_", 1)[0]
    return f"event/b1/{language}/{family}/event_message_{event_id}.ebm"


def profile_id_for_family(family: str) -> str:
    return f"friend_event_message_payload_{family}"


def validate_stage57(stage57_root: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    summary = load_json(stage57_root / "SUMMARY.json")
    if summary.get("type") != "br_quartet_restoration_fe01_message_placeholder_evidence_summary":
        raise FriendEventMessagePrototypeError("stage-57 report type mismatch")
    if str(summary.get("tool_version")) != STAGE57_TOOL_VERSION:
        raise FriendEventMessagePrototypeError("stage-57 report tool version mismatch")
    if str(summary.get("status")) != "scene_wide_multilingual_dash_placeholders_detected_message_restoration_candidates":
        raise FriendEventMessagePrototypeError("stage-57 report is not ready for message prototypes")
    if parse_int(summary.get("safe_later_message_payload_prototype_rows"), -1) != EXPECTED_SAFE_SCENES:
        raise FriendEventMessagePrototypeError("stage-57 safe prototype count mismatch")
    if parse_int(summary.get("skipped_rows"), -1) != 0:
        raise FriendEventMessagePrototypeError("stage-57 report contains skipped rows")
    rows = read_tsv(stage57_root / "FE_EVENT_PLACEHOLDER_SCENE_CANDIDATES.tsv")
    safe_rows = [row for row in rows if parse_bool(row.get("safe_for_later_message_payload_prototype"))]
    if len(safe_rows) != EXPECTED_SAFE_SCENES:
        raise FriendEventMessagePrototypeError("stage-57 candidate table safe-row count mismatch")
    if tuple(sorted({row["family"] for row in safe_rows})) != EXPECTED_FAMILIES:
        raise FriendEventMessagePrototypeError("stage-57 safe candidate family set mismatch")
    for row in safe_rows:
        required = {
            "classification": "scene_text_replaced_by_multilingual_dash_placeholders_control_identical",
            "event_data_classification": "identical",
            "all_target_languages_exact_dash_placeholders": "True",
            "target_language_payload_hashes_identical": "True",
            "jp_metadata_equal_excluding_text": "True",
            "jp_msg_id_sequence_equal": "True",
            "ebd_hash_equal": "True",
        }
        for field, expected in required.items():
            if str(row.get(field)) != expected:
                raise FriendEventMessagePrototypeError(
                    f"stage-57 safe candidate gate mismatch for {row.get('event_id')}: {field}"
                )
    return summary, sorted(safe_rows, key=lambda row: row["event_id"])


def load_ebm_pair(
    *, br: Any, text_tool: Any, workspace_root: Path,
    source_index: Mapping[str, Mapping[str, Any]], target_index: Mapping[str, Mapping[str, Any]],
    event_id: str, source_language: str, target_language: str,
) -> tuple[Any, Any, Mapping[str, Any], Mapping[str, Any], Path, Path]:
    source_path = stage57.event_message_path(event_id, source_language)
    target_path = stage57.event_message_path(event_id, target_language)
    source_row = source_index.get(source_path)
    target_row = target_index.get(target_path)
    if not source_row or not target_row:
        raise FriendEventMessagePrototypeError(
            f"missing inventory EBM pair for {event_id} {source_language}->{target_language}"
        )
    source_file = stage57.workspace_path(br, workspace_root, "source", source_row)
    target_file = stage57.workspace_path(br, workspace_root, "target", target_row)
    if not source_file.is_file() or not target_file.is_file():
        raise FriendEventMessagePrototypeError(
            f"missing workspace EBM pair for {event_id} {source_language}->{target_language}"
        )
    source_ebm, _ = text_tool._parse_ebm_with_diagnostics(source_file)
    target_ebm, _ = text_tool._parse_ebm_with_diagnostics(target_file)
    if text_tool.serialize_ebm(source_ebm) != source_ebm.raw:
        raise FriendEventMessagePrototypeError(f"source EBM round-trip failed: {source_file}")
    if text_tool.serialize_ebm(target_ebm) != target_ebm.raw:
        raise FriendEventMessagePrototypeError(f"target EBM round-trip failed: {target_file}")
    return source_ebm, target_ebm, source_row, target_row, source_file, target_file


def build_candidate(text_tool: Any, source_ebm: Any, target_ebm: Any, *, label: str) -> tuple[bytes, dict[str, bool]]:
    source_messages = list(source_ebm.messages)
    target_messages = list(target_ebm.messages)
    if len(source_messages) != len(target_messages) or not source_messages:
        raise FriendEventMessagePrototypeError(f"record-count mismatch for {label}")
    source_texts = [message.text for message in source_messages]
    target_texts = [message.text for message in target_messages]
    checks = {
        "source_has_substantive_payload": any(text.strip() not in {"", stage57.PLACEHOLDER_TEXT} for text in source_texts),
        "target_all_exact_dash_placeholders": all(text == stage57.PLACEHOLDER_TEXT for text in target_texts),
        "record_count_equal": len(source_messages) == len(target_messages),
        "msg_id_sequence_equal": [m.msg_id for m in source_messages] == [m.msg_id for m in target_messages],
        "metadata_equal_excluding_text": metadata_sequence(source_messages) == metadata_sequence(target_messages),
        "signed_count_equal": source_ebm.signed_count == target_ebm.signed_count,
        "record_layout_equal": (source_ebm.d1_len, source_ebm.d2_len) == (target_ebm.d1_len, target_ebm.d2_len),
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise FriendEventMessagePrototypeError(f"input validation failed for {label}: {', '.join(failed)}")
    candidate = text_tool.serialize_ebm(target_ebm, source_texts)
    candidate_ebm, _ = text_tool._parse_ebm_data_with_diagnostics(
        candidate, Path(label), forced_layout=(target_ebm.d1_len, target_ebm.d2_len)
    )
    checks.update({
        "candidate_roundtrip_exact": text_tool.serialize_ebm(candidate_ebm) == candidate,
        "candidate_texts_match_source": [m.text for m in candidate_ebm.messages] == source_texts,
        "candidate_metadata_matches_target": metadata_sequence(candidate_ebm.messages) == metadata_sequence(target_messages),
        "candidate_extra_data_matches_target": candidate_ebm.extra_data == target_ebm.extra_data,
        "candidate_differs_from_placeholder_target": candidate != target_ebm.raw,
        "exact_target_reverse_roundtrip": text_tool.serialize_ebm(candidate_ebm, target_texts) == target_ebm.raw,
    })
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise FriendEventMessagePrototypeError(f"candidate validation failed for {label}: {', '.join(failed)}")
    return candidate, checks


def collect(*, project_root: Path, workspace_root: Path, report_root: Path) -> tuple[Path, dict[str, Any]]:
    br, text_tool = stage57.load_tools(project_root)
    report_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="br-fe-message-prototype-") as td:
        temporary = Path(td)
        stage57_root = locate_named_root(
            report_root, STAGE57_DIR_NAME, STAGE57_REPORT_NAME, temporary / "stage57"
        )
        inventory_root = locate_inventory_root(report_root, temporary / "inventory")
        stage57_summary, safe_rows = validate_stage57(stage57_root)
        source_inventory = load_json(inventory_root / "inventories/br1_events.source.json")
        target_inventory = load_json(inventory_root / "inventories/br1_events.target.json")
        source_index = stage57.index_inventory(source_inventory)
        target_index = stage57.index_inventory(target_inventory)

        staging_root = workspace_root / (str(PROTOTYPE_SUBDIR) + ".tmp")
        final_root = workspace_root / PROTOTYPE_SUBDIR
        shutil.rmtree(staging_root, ignore_errors=True)
        staging_root.mkdir(parents=True, exist_ok=True)

        profile_rows: list[dict[str, object]] = []
        file_rows: list[dict[str, object]] = []
        validation_rows: list[dict[str, object]] = []
        unresolved_rows: list[dict[str, object]] = []
        skipped_rows: list[dict[str, object]] = []
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in safe_rows:
            grouped[row["family"]].append(row)

        try:
            for family in EXPECTED_FAMILIES:
                scenes = grouped.get(family, [])
                if not scenes:
                    raise FriendEventMessagePrototypeError(f"no safe scenes for expected family {family}")
                profile_id = profile_id_for_family(family)
                profile_root = staging_root / profile_id
                changed_members: list[dict[str, object]] = []
                family_validation_count = 0
                for scene in scenes:
                    event_id = scene["event_id"]
                    for source_language, target_language in RESTORED_LANGUAGE_PAIRS:
                        label = f"{event_id}:{source_language}->{target_language}"
                        source_ebm, target_ebm, source_row, target_row, _source_file, _target_file = load_ebm_pair(
                            br=br, text_tool=text_tool, workspace_root=workspace_root,
                            source_index=source_index, target_index=target_index,
                            event_id=event_id, source_language=source_language,
                            target_language=target_language,
                        )
                        candidate, checks = build_candidate(text_tool, source_ebm, target_ebm, label=label)
                        member = target_member_path(event_id, target_language)
                        output_path = profile_root / "members" / member
                        atomic_bytes(output_path, candidate)
                        source_sha = str(source_row.get("sha256", "")) or sha256_bytes(source_ebm.raw)
                        target_sha = str(target_row.get("sha256", "")) or sha256_bytes(target_ebm.raw)
                        candidate_sha = sha256_bytes(candidate)
                        row = {
                            "profile_id": profile_id,
                            "family": family,
                            "event_id": event_id,
                            "source_language": source_language,
                            "target_language": target_language,
                            "target_member": member,
                            "local_relative_path": str(output_path.relative_to(workspace_root)),
                            "record_count": len(target_ebm.messages),
                            "source_size": len(source_ebm.raw),
                            "target_size": len(target_ebm.raw),
                            "candidate_size": len(candidate),
                            "source_sha256": source_sha,
                            "target_sha256": target_sha,
                            "candidate_sha256": candidate_sha,
                            "source_text_utf8_bytes": sum(len(m.text.encode("utf-8")) for m in source_ebm.messages),
                            "target_text_utf8_bytes": sum(len(m.text.encode("utf-8")) for m in target_ebm.messages),
                            "candidate_text_utf8_bytes": sum(len(m.text.encode("utf-8")) for m in source_ebm.messages),
                            "status": "local_metadata_preserving_message_payload_prototype",
                        }
                        file_rows.append(row)
                        changed_members.append(dict(row))
                        for check_name, passed in checks.items():
                            validation_rows.append({
                                "profile_id": profile_id,
                                "event_id": event_id,
                                "target_language": target_language,
                                "target_member": member,
                                "check": check_name,
                                "passed": passed,
                            })
                            family_validation_count += 1
                    for unresolved_language in UNRESOLVED_TARGET_LANGUAGES:
                        unresolved_rows.append({
                            "profile_id": profile_id,
                            "family": family,
                            "event_id": event_id,
                            "target_language": unresolved_language,
                            "reason": "no_original_simplified_chinese_source",
                            "policy": "leave_quartet_dash_placeholder_unchanged_until_separate_translation_source_exists",
                        })

                manifest = {
                    "type": "br_quartet_restoration_friend_event_message_payload_prototype",
                    "format_version": 1,
                    "tool_version": TOOL_VERSION,
                    "profile_id": profile_id,
                    "family": family,
                    "status": "experimental_metadata_gated",
                    "runtime_validated": False,
                    "source_stage57_tool_version": STAGE57_TOOL_VERSION,
                    "scene_count": len(scenes),
                    "changed_member_count": len(changed_members),
                    "restored_languages": [target for _source, target in RESTORED_LANGUAGE_PAIRS],
                    "unresolved_languages": list(UNRESOLVED_TARGET_LANGUAGES),
                    "events": [row["event_id"] for row in scenes],
                    "changed_members": changed_members,
                    "policy": {
                        "quartet_record_metadata_preserved": True,
                        "quartet_extra_data_preserved": True,
                        "original_text_payload_used": True,
                        "simplified_chinese_synthesized": False,
                        "pak_repacked": False,
                        "core_registry_modified": False,
                        "profile_activated": False,
                        "installed_game_modified": False,
                        "reachability_claimed": False,
                        "translation_json_modified": False,
                    },
                }
                atomic_json(profile_root / "PROFILE.json", manifest)
                profile_rows.append({
                    "profile_id": profile_id,
                    "family": family,
                    "scene_count": len(scenes),
                    "changed_member_count": len(changed_members),
                    "validation_rows": family_validation_count,
                    "validation_failures": 0,
                    "restored_languages": ";".join(target for _source, target in RESTORED_LANGUAGE_PAIRS),
                    "unresolved_languages": ";".join(UNRESOLVED_TARGET_LANGUAGES),
                    "local_profile_path": str((final_root / profile_id).relative_to(workspace_root)),
                    "status": "experimental_metadata_gated_not_repacked_not_registered",
                    "runtime_validated": False,
                })

            if len(profile_rows) != len(EXPECTED_FAMILIES):
                raise FriendEventMessagePrototypeError("profile count mismatch")
            if len(file_rows) != EXPECTED_SAFE_SCENES * len(RESTORED_LANGUAGE_PAIRS):
                raise FriendEventMessagePrototypeError("prototype file count mismatch")
            if any(not parse_bool(row.get("passed")) for row in validation_rows):
                raise FriendEventMessagePrototypeError("prototype validation failure")
            if len(unresolved_rows) != EXPECTED_SAFE_SCENES * len(UNRESOLVED_TARGET_LANGUAGES):
                raise FriendEventMessagePrototypeError("unresolved-language row count mismatch")

            shutil.rmtree(final_root, ignore_errors=True)
            final_root.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging_root, final_root)
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise

        evidence_dir = report_root / EVIDENCE_DIR_NAME
        shutil.rmtree(evidence_dir, ignore_errors=True)
        evidence_dir.mkdir(parents=True)
        write_tsv(evidence_dir / "FRIEND_EVENT_MESSAGE_PROTOTYPE_PROFILES.tsv", [
            "profile_id", "family", "scene_count", "changed_member_count", "validation_rows",
            "validation_failures", "restored_languages", "unresolved_languages",
            "local_profile_path", "status", "runtime_validated",
        ], profile_rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_MESSAGE_PROTOTYPE_FILES.tsv", [
            "profile_id", "family", "event_id", "source_language", "target_language",
            "target_member", "local_relative_path", "record_count", "source_size", "target_size",
            "candidate_size", "source_sha256", "target_sha256", "candidate_sha256",
            "source_text_utf8_bytes", "target_text_utf8_bytes", "candidate_text_utf8_bytes", "status",
        ], file_rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_MESSAGE_PROTOTYPE_VALIDATIONS.tsv", [
            "profile_id", "event_id", "target_language", "target_member", "check", "passed",
        ], validation_rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_MESSAGE_UNRESOLVED_LANGUAGES.tsv", [
            "profile_id", "family", "event_id", "target_language", "reason", "policy",
        ], unresolved_rows)
        write_tsv(evidence_dir / "FRIEND_EVENT_MESSAGE_PROTOTYPE_SKIPPED.tsv", [
            "profile_id", "event_id", "target_language", "reason", "detail",
        ], skipped_rows)

        by_family = Counter(row["family"] for row in file_rows)
        summary = {
            "type": "br_quartet_restoration_friend_event_message_payload_prototype_evidence_summary",
            "format_version": 1,
            "tool_version": TOOL_VERSION,
            "source_stage57_tool_version": str(stage57_summary.get("tool_version", "")),
            "status": "local_family_message_payload_prototypes_built_runtime_unvalidated",
            "safe_scene_rows": len(safe_rows),
            "profile_rows": len(profile_rows),
            "prototype_file_rows": len(file_rows),
            "validation_rows": len(validation_rows),
            "validation_failures": sum(not parse_bool(row["passed"]) for row in validation_rows),
            "unresolved_language_rows": len(unresolved_rows),
            "skipped_rows": len(skipped_rows),
            "families": {family: by_family[family] for family in EXPECTED_FAMILIES},
            "restored_languages": [target for _source, target in RESTORED_LANGUAGE_PAIRS],
            "unresolved_languages": list(UNRESOLVED_TARGET_LANGUAGES),
            "user_listed_safe_scene_rows": parse_int(stage57_summary.get("user_listed_safe_prototype_rows")),
            "prototype_root": str(final_root),
            "policy": {
                "original_japanese_payload_used": True,
                "original_english_payload_used": True,
                "original_traditional_chinese_payload_used": True,
                "simplified_chinese_synthesized": False,
                "quartet_non_text_metadata_preserved": True,
                "quartet_extra_data_preserved": True,
                "translation_json_modified": False,
                "br_text_tool_modified": False,
                "ebm_written_to_local_workspace_only": True,
                "pak_repacked": False,
                "core_registry_modified": False,
                "profile_activated": False,
                "installed_game_modified": False,
                "runtime_reachability_claimed": False,
            },
            "next_action": (
                "Prepare separate current-PACK11 repack tests per FE family. Preserve any active non-placeholder "
                "English translation member instead of overwriting it; restore Original EN only when the installed "
                "member remains an exact dash-placeholder scene."
            ),
        }
        atomic_json(evidence_dir / "SUMMARY.json", summary)
        output = report_root / REPORT_NAME
        make_report_archive(evidence_dir, output)
        return output, summary


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", required=True)
    p.add_argument("--workspace-root")
    p.add_argument("--report-root")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.is_dir():
        raise FriendEventMessagePrototypeError(f"project root does not exist: {project_root}")
    workspace_root = (
        Path(args.workspace_root).expanduser().resolve()
        if args.workspace_root else project_root / ".local/build/quartet_restoration"
    )
    report_root = (
        Path(args.report_root).expanduser().resolve()
        if args.report_root else project_root / ".local/reports/quartet_restoration"
    )
    output, summary = collect(
        project_root=project_root, workspace_root=workspace_root, report_root=report_root
    )
    print(f"Safe FE scenes: {summary['safe_scene_rows']}")
    print(f"Family profiles built: {summary['profile_rows']}")
    print(f"Local EBM prototypes: {summary['prototype_file_rows']}")
    print(f"Validation failures: {summary['validation_failures']}")
    print(f"Unresolved SC scenes: {summary['unresolved_language_rows']}")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FriendEventMessagePrototypeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
