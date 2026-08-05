from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "collect_opaque_scene_effect_member_evidence.py"
SPEC = importlib.util.spec_from_file_location("collect_opaque_scene_effect_member_evidence", MODULE_PATH)
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


class OpaqueSceneEffectEvidenceTests(unittest.TestCase):
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

        prototypes: list[dict[str, object]] = []
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
            prototypes.append({
                **base,
                "prototype_action": "controlled_scene_or_wet_effect_member_probe",
                "risk": "medium_high",
                "evidence_basis": "small scene effect delta",
                "payload_delta_shape": "replace",
                "program_structures": "",
                "review_status": "cluster_review_required_before_test",
            })
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

        proto_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "prototype_action", "risk", "evidence_basis",
            "payload_delta_shape", "program_structures", "review_status",
        ]
        delta_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "normalized_path", "member_key",
            "source_member_name", "target_member_name", "extension", "classification", "source_size", "target_size",
            "changed_density", "changed_range_count", "delta_cluster_id", "delta_cluster_size",
        ]
        payload_fields = [
            "candidate_id", "rule_id", "domain", "priority", "evidence_kind", "side", "normalized_path",
            "member_key", "member_name", "extension", "payload_size", "payload_sha256",
        ]
        write_tsv(binary / "RESTORATION_PROTOTYPE_CANDIDATES.tsv", proto_fields, prototypes)
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
            rows = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "OPAQUE_SCENE_EFFECT_MEMBERS.tsv")
            self.assertEqual(rows[0]["classification"], "opaque_scene_effect_exact_original_candidate_ready_for_local_prototype")
            self.assertEqual(rows[0]["best_candidate_distance_to_source"], "0")
            self.assertEqual(rows[0]["operation_count"], "1")

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
            operations = TOOL.read_tsv(reports / TOOL.EVIDENCE_DIR_NAME / "OPAQUE_SCENE_EFFECT_OPERATIONS.tsv")
            self.assertTrue(all(row["eligible"] == "False" for row in operations))
            self.assertTrue(all("recurrent_operation_shape" in row["exclusion_reasons"] for row in operations))

    def test_rejects_stage63_report_with_remaining_candidate_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, workspace, reports, loader = self.build_fixture(Path(temporary), stage63_candidates=1)
            with self.assertRaises(TOOL.OpaqueEffectError):
                TOOL.collect(
                    project_root=project,
                    workspace_root=workspace,
                    report_root=reports,
                    pair_loader=loader,
                )


if __name__ == "__main__":
    unittest.main()
