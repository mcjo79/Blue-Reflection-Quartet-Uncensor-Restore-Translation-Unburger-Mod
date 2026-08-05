#!/usr/bin/env python3
"""Test the unselected rare cue-linked residual in fe13_090 in memory.

Stage 51 follows the one remaining cue-positive event family whose rare residual
was not selected by stage 23: fe13_090.  It validates the stage-24 rare residual
and stage-25 clothing/costume cues, reconstructs the exact inverse replacement
from the local Original and Quartet EBDs, and requires preservation of every
other residual counter plus exact reverse round-trip and strict distance
improvement before any later local prototype.  No payload is written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import collect_presentation_event_subset_search_evidence as subset
import collect_complex_repeated_shape_subset_evidence as complex_stage

WORKSTREAM_ID = "quartet_restoration"
TOOL_VERSION = "0.0.59"
TARGET_EVENT_PATH = "event/event_jp/fe13/event_fe13_090.ebd"
TARGET_SHAPE_ID = "8330c2a15d46ecd6f1a7ca60bd51696b69f69e9bc415c568e9610b1cc5ce8be7"
REPORT_NAME = "BR_quartet_restoration_unselected_cue_residual_splice_evidence.tar.zst"
EVIDENCE_DIR_NAME = "unselected_cue_residual_splice_evidence"
REPORT_SPECS = {
    "context": ("event_delta_context_evidence", "BR_quartet_restoration_event_delta_context_evidence.tar.zst"),
    "migration": ("event_tag_migration_evidence", "BR_quartet_restoration_event_tag_migration_evidence.tar.zst"),
    "cue": ("event_scene_cue_evidence", "BR_quartet_restoration_event_scene_cue_evidence.tar.zst"),
    "core": ("core_profile_manifest_evidence", "BR_quartet_restoration_core_profile_manifest_evidence.tar.zst"),
    "complex": ("complex_repeated_shape_subset_evidence", "BR_quartet_restoration_complex_repeated_shape_subset_evidence.tar.zst"),
}

class UnselectedCueResidualError(RuntimeError):
    pass

def parse_bool(value: object) -> bool:
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}

def parse_int(value: object, default: int = 0) -> int:
    try: return int(str(value).strip())
    except (TypeError, ValueError): return default

def normalize_event_member(path: object) -> str:
    return subset.normalize_event_member(path)

def read_tsv(path: Path, *, required: bool = True) -> list[dict[str, str]]:
    return subset.read_tsv(path, required=required)

def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    subset.write_tsv(path, fields, rows)

def load_json(path: Path) -> dict[str, Any]:
    return subset.load_json(path)

def safe_member_name(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise UnselectedCueResidualError(f"unsafe report archive member: {raw}")
    return path.as_posix()

def extract_archive(archive: Path, destination: Path) -> Path:
    if not archive.is_file():
        raise UnselectedCueResidualError(f"missing prerequisite report archive: {archive}")
    listed = subprocess.run(["tar", "--zstd", "-tf", str(archive)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if listed.returncode:
        raise UnselectedCueResidualError(f"cannot list {archive}: {listed.stderr.strip()}")
    roots = {PurePosixPath(safe_member_name(x.strip())).parts[0] for x in listed.stdout.splitlines() if x.strip()}
    if len(roots) != 1:
        raise UnselectedCueResidualError(f"expected one report root in {archive}, found {sorted(roots)}")
    destination.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["tar", "--zstd", "-xf", str(archive), "-C", str(destination)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode:
        raise UnselectedCueResidualError(f"cannot extract {archive}: {done.stderr.strip()}")
    return destination / next(iter(roots))

def locate_report_root(report_root: Path, key: str, temporary: Path) -> Path:
    dirname, archive = REPORT_SPECS[key]
    direct = report_root / dirname
    return direct if direct.is_dir() else extract_archive(report_root / archive, temporary / key)

def make_report_archive(source_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.unlink(missing_ok=True)
    done = subprocess.run(["tar", "--zstd", "-cf", str(tmp), "-C", str(source_dir.parent), source_dir.name], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if done.returncode:
        raise UnselectedCueResidualError(f"cannot create report archive: {done.stderr.strip()}")
    os.replace(tmp, output)

def validate_target_evidence(roots: Mapping[str, Path]) -> dict[str, Any]:
    context = load_json(roots["context"] / "SUMMARY.json")
    if context.get("type") != "br_quartet_restoration_event_delta_context_evidence_summary" or context.get("tool_version") != "0.0.27":
        raise UnselectedCueResidualError("stage-23 report must be the canonical 0.0.27 report")
    selected = read_tsv(roots["context"] / "SELECTED_EVENT_DELTA_SHAPES.tsv")
    occurrences = read_tsv(roots["context"] / "EVENT_DELTA_CONTEXT_OCCURRENCES.tsv")
    if any(row.get("shape_id") == TARGET_SHAPE_ID for row in selected):
        raise UnselectedCueResidualError("target shape unexpectedly appears in stage-23 selected shapes")
    if any(normalize_event_member(row.get("normalized_path")) == TARGET_EVENT_PATH for row in occurrences):
        raise UnselectedCueResidualError("target event unexpectedly appears in stage-23 selected occurrence evidence")

    migration = load_json(roots["migration"] / "SUMMARY.json")
    if migration.get("type") != "br_quartet_restoration_event_tag_migration_evidence_summary" or migration.get("tool_version") != "0.0.24":
        raise UnselectedCueResidualError("stage-24 report must be the canonical 0.0.24 report")
    rows = read_tsv(roots["migration"] / "RESIDUAL_EVENT_TAG_DELTAS.tsv")
    target_rows = [r for r in rows if normalize_event_member(r.get("normalized_path")) == TARGET_EVENT_PATH]
    if len(target_rows) != 1:
        raise UnselectedCueResidualError(f"expected one rare residual row for fe13_090, found {len(target_rows)}")
    row = target_rows[0]
    # Recompute from canonical row rather than trusting a copied hash column.
    project_root = roots["migration"].parents[3] if len(roots["migration"].parents) >= 4 else None
    if row.get("migration_classification") != "rare_event_delta_candidate":
        raise UnselectedCueResidualError("fe13_090 residual is no longer rare-event classified")
    if row.get("sequence_tag") != "replace" or parse_int(row.get("source_atom_count")) != 1 or parse_int(row.get("target_atom_count")) != 2:
        raise UnselectedCueResidualError("fe13_090 residual no longer has the expected replace 1->2 shape")
    if parse_int(row.get("signature_file_count"), -1) != 1 or parse_int(row.get("signature_route_family_count"), -1) != 1:
        raise UnselectedCueResidualError("fe13_090 residual is no longer scene-unique")

    cue = load_json(roots["cue"] / "SUMMARY.json")
    if cue.get("type") != "br_quartet_restoration_event_scene_cue_evidence_summary" or cue.get("tool_version") != "0.0.25":
        raise UnselectedCueResidualError("stage-25 report must be the canonical 0.0.25 report")
    cue_rows = read_tsv(roots["cue"] / "FOCUSED_PRESENTATION_EVENT_REVIEW.tsv")
    matches = [r for r in cue_rows if normalize_event_member(r.get("normalized_path")) == TARGET_EVENT_PATH]
    if len(matches) != 1:
        raise UnselectedCueResidualError("missing unique stage-25 cue row for fe13_090")
    cue_row = matches[0]
    domains = set(str(cue_row.get("cue_domains", "")).split(";"))
    if not {"clothing_state", "costume_or_coverage"}.issubset(domains):
        raise UnselectedCueResidualError("fe13_090 no longer has the expected clothing/costume cues")
    if parse_int(cue_row.get("residual_delta_rows"), -1) != 1 or cue_row.get("event_message_classification") != "changed":
        raise UnselectedCueResidualError("fe13_090 cue/residual relationship changed")

    core = load_json(roots["core"] / "SUMMARY.json")
    if core.get("type") != "br_quartet_restoration_core_profile_manifest_evidence_summary" or core.get("tool_version") != "0.0.54":
        raise UnselectedCueResidualError("current core-profile report must be the 0.0.54 report")
    if parse_int(core.get("profile_rows"), -1) != 13 or parse_int(core.get("runtime_validated_profile_rows"), -1) != 0:
        raise UnselectedCueResidualError("current core-profile report must contain 13 runtime-unvalidated profiles")

    complex_summary = load_json(roots["complex"] / "SUMMARY.json")
    if complex_summary.get("type") != "br_quartet_restoration_complex_repeated_shape_subset_evidence_summary" or complex_summary.get("tool_version") != "0.0.58":
        raise UnselectedCueResidualError("stage-50 report must be the corrected 0.0.58 report")
    if parse_int(complex_summary.get("promotable_event_rows"), -1) != 0 or parse_int(complex_summary.get("reported_combination_rows"), -1) != 7:
        raise UnselectedCueResidualError("stage-50 report must contain seven non-promotable combinations")
    return {"context": context, "migration": migration, "cue": cue, "core": core, "complex": complex_summary, "residual_row": row, "cue_row": cue_row}

def shape_counter(br: Any, source_profile: Mapping[str, object], target_profile: Mapping[str, object]) -> Counter[str]:
    return Counter(br.event_residual_delta_shape_id(row) for row in br.compare_ebd_tag_atoms(source_profile["atoms"], target_profile["atoms"]))

def evaluate_single_unselected_splice(br: Any, source_payload: bytes, target_payload: bytes, shape_id: str = TARGET_SHAPE_ID) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sh = br.parse_ebd_header_schema(source_payload); th = br.parse_ebd_header_schema(target_payload)
    if sh.get("classification") != "observed_ebd_name_description_header" or th.get("classification") != "observed_ebd_name_description_header":
        raise UnselectedCueResidualError("source or target EBD header is not recognized")
    sp = br.profile_ebd_post_header_words(source_payload, int(sh["header_end"]), maximum_words=max(1, len(source_payload)//4+8))
    tp = br.profile_ebd_post_header_words(target_payload, int(th["header_end"]), maximum_words=max(1, len(target_payload)//4+8))
    deltas = br.compare_ebd_tag_atoms(sp["atoms"], tp["atoms"])
    matches = [d for d in deltas if br.event_residual_delta_shape_id(d) == shape_id]
    if len(matches) != 1:
        raise UnselectedCueResidualError(f"expected one reproducible target shape occurrence, found {len(matches)}")
    d = matches[0]
    ss,se = br.event_atom_word_span(sp["atoms"], int(d["source_atom_start"]), int(d["source_atom_end"]), int(sp["word_count"]))
    ts,te = br.event_atom_word_span(tp["atoms"], int(d["target_atom_start"]), int(d["target_atom_end"]), int(tp["word_count"]))
    sw=list(sp["words"])[ss:se]; tw=list(tp["words"])[ts:te]
    words=list(tp["words"]); words[ts:te]=sw
    target_end=int(th["header_end"])+int(tp["word_count"])*4
    packed=struct.pack(f"<{len(words)}I", *words) if words else b""
    candidate=target_payload[:int(th["header_end"])] + packed + target_payload[target_end:]
    ch=br.parse_ebd_header_schema(candidate)
    cp=br.profile_ebd_post_header_words(candidate, int(ch["header_end"]), maximum_words=max(1,len(candidate)//4+8))
    cwords=list(cp["words"]); cwords[ts:ts+len(sw)]=tw
    repacked=struct.pack(f"<{len(cwords)}I", *cwords) if cwords else b""
    candidate_end=int(ch["header_end"])+int(cp["word_count"])*4
    reversed_payload=target_payload[:int(th["header_end"])] + repacked + candidate[candidate_end:]
    before=shape_counter(br,sp,tp); after=shape_counter(br,sp,cp)
    before_other=before.copy(); after_other=after.copy(); before_other.pop(shape_id,None); after_other.pop(shape_id,None)
    target_distance=subset.byte_difference_count(target_payload, source_payload)
    candidate_distance=subset.byte_difference_count(candidate, source_payload)
    checks={
        "target_shape_count_reduced_exactly_once": before.get(shape_id,0)==1 and after.get(shape_id,0)==0,
        "all_other_residual_counters_preserved": before_other==after_other,
        "no_new_residual_shapes": not (set(after)-set(before)),
        "quartet_header_preserved": candidate[:int(th["header_end"])]==target_payload[:int(th["header_end"])],
        "quartet_trailing_bytes_preserved": candidate[candidate_end:]==target_payload[target_end:],
        "exact_target_reverse_roundtrip": reversed_payload==target_payload,
        "candidate_not_farther_from_original": candidate_distance<=target_distance,
    }
    passes_structural=all(v for k,v in checks.items() if k!="candidate_not_farther_from_original")
    strict=passes_structural and candidate_distance<target_distance
    residuals=br.compare_ebd_tag_atoms(sp["atoms"],cp["atoms"])
    return {
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(), "candidate_size": len(candidate),
        "target_distance_to_source": target_distance, "candidate_distance_to_source": candidate_distance,
        "distance_improvement": target_distance-candidate_distance, "checks": checks,
        "passes_structural_gates": passes_structural, "strict_improvement": strict,
        "exact_original": candidate==source_payload, "remaining_residual_rows": len(residuals),
    }, [{"shape_id": br.event_residual_delta_shape_id(r), "sequence_tag": r.get("sequence_tag",""), "source_atom_count": r.get("source_atom_count",""), "target_atom_count": r.get("target_atom_count","")} for r in residuals]

def collect(*, project_root: Path, workspace_root: Path, report_root: Path, maximum_event_bytes: int) -> tuple[Path, dict[str, Any]]:
    sys.path.insert(0, str(project_root / "Blue_Reflection_Text_Tool"))
    try:
        import br_restoration_tool as br
    finally:
        sys.path.pop(0)
    with tempfile.TemporaryDirectory(prefix="br-stage51-") as temp_raw:
        temp=Path(temp_raw)
        roots={key: locate_report_root(report_root,key,temp) for key in REPORT_SPECS}
        evidence=validate_target_evidence(roots)
        # Require current generated registry and ensure fe13_090 is not already owned.
        owners=complex_stage.load_registry_event_owners(project_root)
        if TARGET_EVENT_PATH in owners:
            raise UnselectedCueResidualError(f"target event is already covered by profiles: {owners[TARGET_EVENT_PATH]}")
        differences=br.load_report_jsons(report_root,"differences")
        events=next((r for r in differences if str(r.get("source_archive_group",""))=="br1_events"),None)
        if events is None: raise UnselectedCueResidualError("missing br1_events difference report")
        entry=next((r for r in events.get("entries",[]) if normalize_event_member(r.get("normalized_path"))==TARGET_EVENT_PATH and r.get("scope_status")=="in_scope" and r.get("source") and r.get("target")),None)
        if entry is None: raise UnselectedCueResidualError("missing in-scope difference entry for fe13_090")
        sr=entry["source"]; tr=entry["target"]
        spath=br.inventory_workspace_file(workspace_root,"source","br1_events",str(sr.get("archive","")),str(sr.get("path","")))
        tpath=br.inventory_workspace_file(workspace_root,"target","br1_events",str(tr.get("archive","")),str(tr.get("path","")))
        skipped=[]; event_rows=[]; test_rows=[]; residual_rows=[]
        if not spath.is_file() or not tpath.is_file():
            skipped.append({"normalized_path":TARGET_EVENT_PATH,"shape_id":TARGET_SHAPE_ID,"reason":"workspace_event_payload_missing"})
        else:
            source=spath.read_bytes(); target=tpath.read_bytes()
            if len(source)>maximum_event_bytes or len(target)>maximum_event_bytes:
                skipped.append({"normalized_path":TARGET_EVENT_PATH,"shape_id":TARGET_SHAPE_ID,"reason":"maximum_event_bytes_exceeded"})
            elif sr.get("sha256") and hashlib.sha256(source).hexdigest()!=str(sr.get("sha256")):
                skipped.append({"normalized_path":TARGET_EVENT_PATH,"shape_id":TARGET_SHAPE_ID,"reason":"source_payload_sha256_mismatch"})
            elif tr.get("sha256") and hashlib.sha256(target).hexdigest()!=str(tr.get("sha256")):
                skipped.append({"normalized_path":TARGET_EVENT_PATH,"shape_id":TARGET_SHAPE_ID,"reason":"target_payload_sha256_mismatch"})
            else:
                result,residuals=evaluate_single_unselected_splice(br,source,target)
                ready=bool(result["passes_structural_gates"] and result["strict_improvement"])
                classification="unselected_cue_residual_strict_improvement_ready_for_local_prototype" if ready else "unselected_cue_residual_not_strictly_improving"
                event_rows.append({"normalized_path":TARGET_EVENT_PATH,"event_id":"fe13_090","shape_id":TARGET_SHAPE_ID,"cue_domains":evidence["cue_row"].get("cue_domains",""),"event_message_classification":evidence["cue_row"].get("event_message_classification",""),"target_distance_to_source":result["target_distance_to_source"],"candidate_distance_to_source":result["candidate_distance_to_source"],"distance_improvement":result["distance_improvement"],"candidate_sha256":result["candidate_sha256"],"remaining_residual_rows":result["remaining_residual_rows"],"classification":classification,"safe_to_build_separate_local_profile":ready,"runtime_test_deferred":True,"next_gate":"build_exact_single_event_candidate_as_local_profile" if ready else "retain_as_unselected_cue_context_evidence"})
                for name,value in result["checks"].items(): test_rows.append({"normalized_path":TARGET_EVENT_PATH,"shape_id":TARGET_SHAPE_ID,"validation":name,"passed":value,"details":""})
                test_rows.extend([{"normalized_path":TARGET_EVENT_PATH,"shape_id":TARGET_SHAPE_ID,"validation":"passes_structural_gates","passed":result["passes_structural_gates"],"details":""},{"normalized_path":TARGET_EVENT_PATH,"shape_id":TARGET_SHAPE_ID,"validation":"strict_improvement","passed":result["strict_improvement"],"details":str(result["distance_improvement"]) }])
                for r in residuals: residual_rows.append({"normalized_path":TARGET_EVENT_PATH,**r,"review_status":"remaining_residual_not_assigned_semantics"})
        outdir=report_root/EVIDENCE_DIR_NAME
        if outdir.exists(): shutil.rmtree(outdir)
        outdir.mkdir(parents=True)
        write_tsv(outdir/"UNSELECTED_CUE_RESIDUAL_EVENTS.tsv",["normalized_path","event_id","shape_id","cue_domains","event_message_classification","target_distance_to_source","candidate_distance_to_source","distance_improvement","candidate_sha256","remaining_residual_rows","classification","safe_to_build_separate_local_profile","runtime_test_deferred","next_gate"],event_rows)
        write_tsv(outdir/"UNSELECTED_CUE_RESIDUAL_SPLICE_TESTS.tsv",["normalized_path","shape_id","validation","passed","details"],test_rows)
        write_tsv(outdir/"UNSELECTED_CUE_RESIDUAL_REMAINING.tsv",["normalized_path","shape_id","sequence_tag","source_atom_count","target_atom_count","review_status"],residual_rows)
        write_tsv(outdir/"UNSELECTED_CUE_RESIDUAL_SKIPPED.tsv",["normalized_path","shape_id","reason"],skipped)
        promoted=sum(parse_bool(r.get("safe_to_build_separate_local_profile")) for r in event_rows)
        summary={"type":"br_quartet_restoration_unselected_cue_residual_splice_evidence_summary","format_version":1,"tool_version":TOOL_VERSION,"source_stage23_tool_version":evidence["context"].get("tool_version"),"source_stage24_tool_version":evidence["migration"].get("tool_version"),"source_stage25_tool_version":evidence["cue"].get("tool_version"),"source_core_profile_tool_version":evidence["core"].get("tool_version"),"source_stage50_tool_version":evidence["complex"].get("tool_version"),"status":"unselected_cue_residual_single_splice_evaluated_no_payload_written_runtime_deferred","target_event_rows":1,"analyzed_event_rows":len(event_rows),"promotable_event_rows":promoted,"validation_rows":len(test_rows),"validation_failures":sum(not parse_bool(r.get("passed")) for r in test_rows),"remaining_residual_rows":len(residual_rows),"skipped_rows":len(skipped),"runtime_testing_deferred":True,"policy":{"installed_games_modified":False,"candidate_ebd_payloads_written":False,"pak_repack_performed":False,"profile_manifests_modified":False,"activation_or_rollback_invoked":False,"runtime_validation_inferred":False,"censorship_classification_inferred":False,"binary_field_semantics_inferred":False,"registered_event_paths_excluded":True,"all_other_residual_counters_must_remain_unchanged":True,"exact_reverse_roundtrip_required_for_promotion":True,"strict_original_distance_improvement_required_for_promotion":True,"legacy_dlc_in_scope":False},"next_action":"Upload this metadata report. Build a separate local prototype only if fe13_090 is marked unselected_cue_residual_strict_improvement_ready_for_local_prototype; otherwise retain it as cue-linked context evidence and continue to the next unresolved class."}
        (outdir/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        output=report_root/REPORT_NAME; make_report_archive(outdir,output); return output,summary

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--project-root",required=True); p.add_argument("--workspace-root"); p.add_argument("--report-root"); p.add_argument("--maximum-event-bytes",type=int,default=2*1024*1024); a=p.parse_args()
    root=Path(a.project_root).expanduser().resolve(); workspace=Path(a.workspace_root).expanduser().resolve() if a.workspace_root else root/".local/build/quartet_restoration"; reports=Path(a.report_root).expanduser().resolve() if a.report_root else root/".local/reports/quartet_restoration"
    try: output,summary=collect(project_root=root,workspace_root=workspace,report_root=reports,maximum_event_bytes=a.maximum_event_bytes)
    except (UnselectedCueResidualError, subset.SubsetSearchError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 1
    print(f"Unselected cue events analyzed: {summary['analyzed_event_rows']}"); print(f"Promotable unselected cue residuals: {summary['promotable_event_rows']}"); print(f"Report: {output}"); return 0
if __name__=="__main__": raise SystemExit(main())
