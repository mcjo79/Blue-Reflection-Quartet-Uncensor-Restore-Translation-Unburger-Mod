from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_expanded_scene_effect_member_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_expanded_scene_effect_member_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


class ExpandedSceneEffectEvidenceTests(unittest.TestCase):
    def build_fixture(self, root: Path, *, count: int = 1, stage63_candidates: int = 0):
        project = root / "project"
        reports = project / ".local/reports/quartet_restoration"
        workspace = project / ".local/build/quartet_restoration"
        workspace.mkdir(parents=True)

        core = reports / "core_profile_manifest_evidence"
        write_json(core / "SUMMARY.json", {
            "type": "br_quartet_restoration_core_profile_manifest_evidence_summary",
            "tool_version": "0.0.71",
            "status": "all_current_local_profiles_registered_runtime_unvalidated",
            "profile_rows": 14,
            "pack11_profile_rows": 12,
            "pack10_01_profile_rows": 2,
            "runtime_validated_profile_rows": 0,
        })
        write_tsv(core / "CORE_PROFILE_MANIFESTS.tsv", [
            "profile_id", "runtime_validated", "validation_status",
        ], [
            {"profile_id": f"profile_{index:02d}", "runtime_validated": False, "validation_status": "passed"}
            for index in range(14)
        ])

        stage63 = reports / "remaining_cue_positive_backlog_evidence"
        write_json(stage63 / "SUMMARY.json", {
            "type": "br_quartet_restoration_remaining_cue_positive_backlog_evidence_summary",
            "tool_version": "0.0.72",
            "registry_profile_rows": 14,
            "candidate_backlog_rows": stage63_candidates,
            "promotable_event_rows": 0,
            "policy": {
                "installed_games_modified": False,
                "candidate_ebd_payloads_written": False,
                "pak_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
            },
        })

        stage64 = reports / "opaque_scene_effect_member_evidence"
        write_json(stage64 / "SUMMARY.json", {
            "type": "br_quartet_restoration_opaque_scene_effect_member_evidence_summary",
            "tool_version": "0.0.73",
            "status": "opaque_scene_effect_member_inverse_range_audit_complete_no_payload_written_runtime_deferred",
            "stage8_scene_specific_probe_rows_selected": 0,
            "analyzed_member_rows": 0,
            "promotable_exact_original_member_rows": 0,
            "skipped_rows": 0,
            "policy": {
                "installed_games_modified": False,
                "candidate_effect_payloads_written": False,
                "parent_archive_repack_performed": False,
                "core_registry_modified": False,
                "activation_or_rollback_invoked": False,
            },
        })

        shader = reports / "shader_effect_evidence"
        write_json(shader / "SUMMARY.json", {
            "type": "br_quartet_restoration_shader_effect_evidence_summary",
            "tool_version": "0.0.12",
            "status": "focused_shader_effect_posteffect_evidence_complete_manual_confirmation_required",
            "skipped_rows": 0,
        })

        binary = reports / "binary_delta_evidence"
        write_json(binary / "SUMMARY.json", {
            "type": "br_quartet_restoration_binary_delta_evidence_summary",
            "tool_version": "0.0.13",
            "status": "focused_binary_and_DXBC_chunk_delta_complete_controlled_prototypes_not_generated",
            "skipped_rows": 0,
        })

        payload_deltas: list[dict[str, object]] = []
        payload_metadata: list[dict[str, object]] = []
        pairs: list[dict[str, object]] = []
        source = bytearray(range(64))
        target = bytearray(source)
        target[32:36] = b"\x90\x91\x92\x93"
        source_bytes = bytes(source)
        target_bytes = bytes(target)
        for index in range(count):
            candidate_id = f"effectcand_{index:02d}"
            normalized_path = f"data/x64/effect/bath_scene_{index:02d}.elixir.gz"
            member_key = f"effect_{index:02d}.g1e"
            source_member = f"source_{index:02d}.g1e"
            target_member = f"target_{index:02d}.g1e"
            base = {
                "candidate_id": candidate_id,
                "rule_id": "bath_effect",
                "domain": "steam_or_vapor_occlusion",
                "priority": "critical",
                "evidence_kind": "effect",
                "normalized_path": normalized_path,
                "member_key": member_key,
                "source_member_name": source_member,
                "target_member_name": target_member,
                "extension": ".g1e",
            }
            payload_deltas.append({
                **base,
                "classification": "changed",
                "source_size": len(source_bytes),
                "target_size": len(target_bytes),
                "changed_density": 4 / 64,
                "changed_range_count": 1,
                "delta_cluster_id": f"cluster_{index:02d}",
                "delta_cluster_size": 1,
            })
            for side, payload, member_name in (
                ("source", source_bytes, source_member),
                ("target", target_bytes, target_member),
            ):
                payload_metadata.append({
                    "candidate_id": candidate_id,
                    "rule_id": "bath_effect",
                    "domain": "steam_or_vapor_occlusion",
                    "priority": "critical",
                    "evidence_kind": "effect",
                    "side": side,
                    "normalized_path": normalized_path,
                    "member_key": member_key,
                    "member_name": member_name,
                    "extension": ".g1e",
                    "payload_size": len(payload),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                })
            pairs.append({
                **base,
                "source_payload": source_bytes,
                "target_payload": target_bytes,
            })

        delta_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "classification", "source_size", "target_size",
            "changed_density", "changed_range_count", "delta_cluster_id", "delta_cluster_size",
        ]
        payload_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "side", "normalized_path",
            "member_key", "member_name", "extension", "payload_size", "payload_sha256",
        ]
        write_tsv(binary / "PAYLOAD_BINARY_DELTA.tsv", delta_fields, payload_deltas)
        write_tsv(shader / "RENDER_PAYLOADS.tsv", payload_fields, payload_metadata)

        def pair_loader(**_kwargs):
            return pairs, []

        return project, workspace, reports, pair_loader

    def test_promotes_single_guarded_aligned_exact_original_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary))
            output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                pair_loader=loader,
            )
            self.assertTrue(output.is_file())
            self.assertEqual(summary["analyzed_member_rows"], 1)
            self.assertEqual(summary["promotable_exact_original_member_rows"], 1)
            rows = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "EXPANDED_SCENE_EFFECT_MEMBERS.tsv")
            self.assertEqual(rows[0]["classification"], "expanded_scene_effect_exact_original_candidate_ready_for_local_prototype")
            self.assertEqual(rows[0]["best_candidate_distance_to_source"], "0")
            self.assertEqual(rows[0]["operation_count"], "1")
            self.assertEqual(summary["expanded_focused_binary_delta_rows_selected"], 1)

    def test_recurrent_operation_shape_is_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary), count=2)
            _output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                recurrent_shape_threshold=2,
                pair_loader=loader,
            )
            self.assertEqual(summary["analyzed_member_rows"], 2)
            self.assertEqual(summary["promotable_exact_original_member_rows"], 0)
            operations = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "EXPANDED_SCENE_EFFECT_OPERATIONS.tsv")
            self.assertTrue(all(row["eligible"] == "False" for row in operations))
            self.assertTrue(all("recurrent_operation_shape" in row["exclusion_reasons"] for row in operations))


    def test_linear_operation_discovery_handles_large_repetitive_payload(self) -> None:
        source = bytearray(b"\x00" * (2 * 1024 * 1024))
        target = bytearray(source)
        target[1024:1028] = b"\x01\x02\x03\x04"
        target[-2048:-2044] = b"\x05\x06\x07\x08"
        operations = TOOL.build_operations(
            source=bytes(source),
            target=bytes(target),
            extension=".g1e",
            context_bytes=16,
            header_guard_bytes=16,
            tail_guard_bytes=16,
            maximum_operation_bytes=4096,
        )
        self.assertEqual(len(operations), 2)
        self.assertTrue(all(row["sequence_opcode"] == "replace" for row in operations))
        self.assertTrue(all(row["base_eligible"] for row in operations))

    def test_combination_strategy_is_singletons_plus_full_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary))
            pairs, _ = loader()
            source = bytearray(pairs[0]["source_payload"])
            target = bytearray(source)
            target[24:28] = b"\x80\x81\x82\x83"
            target[40:44] = b"\x90\x91\x92\x93"
            pairs[0]["source_payload"] = bytes(source)
            pairs[0]["target_payload"] = bytes(target)
            binary = reports / "binary_delta_evidence" / "PAYLOAD_BINARY_DELTA.tsv"
            rows = TOOL.read_tsv(binary)
            rows[0]["changed_density"] = str(8 / len(source))
            rows[0]["changed_range_count"] = "2"
            write_tsv(binary, list(rows[0]), rows)
            shader = reports / "shader_effect_evidence" / "RENDER_PAYLOADS.tsv"
            metadata = TOOL.read_tsv(shader)
            for row in metadata:
                payload = bytes(source) if row["side"] == "source" else bytes(target)
                row["payload_size"] = len(payload)
                row["payload_sha256"] = hashlib.sha256(payload).hexdigest()
            write_tsv(shader, list(metadata[0]), metadata)

            def two_operation_loader(**_kwargs):
                return pairs, []

            messages: list[str] = []
            _output, summary = TOOL.collect(
                project_root=project,
                workspace_root=workspace,
                report_root=reports,
                pair_loader=two_operation_loader,
                progress_callback=messages.append,
            )
            self.assertEqual(summary["combination_rows"], 3)
            self.assertEqual(summary["promotable_exact_original_member_rows"], 1)
            self.assertTrue(any("discovering operations" in message for message in messages))
            self.assertTrue(any("evaluating bounded combinations" in message for message in messages))

    def test_rejects_stage64_report_that_selected_a_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary))
            summary_path = reports / "opaque_scene_effect_member_evidence" / "SUMMARY.json"
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["stage8_scene_specific_probe_rows_selected"] = 1
            write_json(summary_path, summary)
            with self.assertRaises(TOOL.ExpandedEffectError):
                TOOL.collect(
                    project_root=project,
                    workspace_root=workspace,
                    report_root=reports,
                    pair_loader=loader,
                )

    def test_rejects_stage63_report_with_remaining_candidate_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary), stage63_candidates=1)
            with self.assertRaises(TOOL.ExpandedEffectError):
                TOOL.collect(
                    project_root=project,
                    workspace_root=workspace,
                    report_root=reports,
                    pair_loader=loader,
                )


if __name__ == "__main__":
    unittest.main()
