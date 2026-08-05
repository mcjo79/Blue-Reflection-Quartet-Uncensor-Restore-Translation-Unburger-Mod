#!/usr/bin/env python3
"""Derive conservative BR1->Quartet compatibility evidence from bounded DLC controls."""
from __future__ import annotations
import argparse, csv, hashlib, json, shutil, subprocess, tarfile, tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.0.11"
FORMAT_VERSION = 1
REPORT_DIR_NAME = "control_compatibility_evidence"
REPORT_ARCHIVE_NAME = "BR_quartet_legacy_dlc_control_compatibility_evidence.tar.zst"
FORBIDDEN_SUFFIXES = {".pak", ".ebm", ".ebd", ".g1m", ".g1t", ".g1a", ".g1e", ".g1s", ".elixir", ".gz", ".bin", ".swg", ".dds", ".wav", ".ogg"}

class ControlCompatibilityError(RuntimeError): pass

def scalar(v: Any) -> str:
    if v is None: return ""
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, (list, dict, tuple, set)): return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(v)

def sha256_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def read_tsv(p: Path) -> list[dict[str,str]]:
    if not p.is_file(): raise ControlCompatibilityError(f"missing prerequisite TSV: {p}")
    with p.open(encoding='utf-8-sig', newline='') as f: return [dict(r) for r in csv.DictReader(f, delimiter='\t')]

def write_tsv(p: Path, fields: Sequence[str], rows: Iterable[Mapping[str,Any]]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding='utf-8', newline='') as f:
        w=csv.DictWriter(f, fieldnames=list(fields), delimiter='\t', lineterminator='\n'); w.writeheader()
        for r in rows: w.writerow({k:scalar(r.get(k,'')) for k in fields})

def write_json(p: Path, value: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)+'\n', encoding='utf-8')

def clean_dir(p: Path) -> None:
    if p.exists(): shutil.rmtree(p)
    p.mkdir(parents=True)

def locate(report_root: Path, directory: str, archive: str, temp: Path) -> Path:
    d=report_root/directory
    if d.is_dir(): return d
    a=report_root/archive
    if not a.is_file(): raise ControlCompatibilityError(f"missing prerequisite report: {d} / {a}")
    subprocess.run(['tar','--zstd','-xf',str(a),'-C',str(temp)], check=True)
    x=temp/directory
    if x.is_dir(): return x
    ds=[p for p in temp.iterdir() if p.is_dir()]
    if len(ds)==1: return ds[0]
    raise ControlCompatibilityError(f"could not locate extracted prerequisite: {a}")

def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='br_dlc_control_bundle_') as td:
        temp_tar=Path(td)/'report.tar'
        with tarfile.open(temp_tar,'w',format=tarfile.PAX_FORMAT) as ar:
            for p in sorted(source.rglob('*'), key=lambda x:x.relative_to(source).as_posix().casefold()):
                if not p.is_file(): continue
                info=ar.gettarinfo(str(p), arcname=f"{source.name}/{p.relative_to(source).as_posix()}")
                info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=0
                with p.open('rb') as f: ar.addfile(info,f)
        subprocess.run(['zstd','-q','-f','-19',str(temp_tar),'-o',str(output)], check=True)

def member_part(name: str) -> str:
    n=name.casefold()
    if '_p_accessory' in n: return 'accessory'
    if '_p_tear' in n: return 'tear'
    if '_default' in n: return 'default'
    if n.endswith('.swg'): return 'cloth_structure'
    if 'oid.bin' in n: return 'object_descriptor'
    return 'base'

def block_index(rows: list[dict[str,str]]) -> dict[tuple[str,str,str,str,str], list[dict[str,str]]]:
    out: dict[tuple[str,str,str,str,str], list[dict[str,str]]] = defaultdict(list)
    for r in rows:
        key=(r['content_id'],r['parent_role'],member_part(r['member_name']),r['side'],r['shader_block_index'])
        out[key].append(r)
    return out

def signature(rows: list[dict[str,str]], *, values: bool, remove_blend: bool=False) -> tuple:
    vals=[]
    for r in rows:
        name=r['parameter_name'].casefold()
        if remove_blend and name=='parameterformeshblend': continue
        base=(name,r['buffer_type'],r['buffer_count'])
        vals.append(base+(r['value_hex_sha256'],) if values else base)
    return tuple(sorted(vals))

def match_blocks(source_rows: list[dict[str,str]], target_blocks: dict[str,list[dict[str,str]]], *, remove_target_blend: bool=False) -> tuple[str,list[str]]:
    exact=[]; shape=[]
    sv=signature(source_rows, values=True)
    ss=signature(source_rows, values=False)
    for idx, rows in target_blocks.items():
        if sv==signature(rows, values=True, remove_blend=remove_target_blend): exact.append(idx)
        if ss==signature(rows, values=False, remove_blend=remove_target_blend): shape.append(idx)
    if len(exact)==1: return 'exact_unique', exact
    if len(exact)>1: return 'exact_ambiguous', exact
    if len(shape)==1: return 'shape_unique', shape
    if len(shape)>1: return 'shape_ambiguous', shape
    return 'unmatched', []

def audit(project_root: Path, output_root: Path) -> tuple[Path,dict[str,Any]]:
    reports=project_root/'.local/reports/quartet_legacy_dlc'
    with tempfile.TemporaryDirectory(prefix='br_dlc_control_prereq_') as td:
        temp=Path(td)
        bounded=locate(reports,'bounded_family_evidence','BR_quartet_legacy_dlc_bounded_family_evidence.tar.zst',temp)
        external=locate(reports,'external_dependency_closure_evidence','BR_quartet_legacy_dlc_external_dependency_closure_evidence.tar.zst',temp)
        bsum=json.loads((bounded/'SUMMARY.json').read_text(encoding='utf-8'))
        if bsum.get('tool_version')!='0.0.10': raise ControlCompatibilityError(f"expected bounded report 0.0.10, got {bsum.get('tool_version')}")
        params=read_tsv(bounded/'DLC_BOUNDED_G1M_MATERIAL_PARAMETERS.tsv')
        diffs=read_tsv(bounded/'DLC_BOUNDED_G1M_MATERIAL_DIFFS.tsv')
        members=read_tsv(bounded/'DLC_BOUNDED_FAMILY_MEMBER_AUDIT.tsv')
        cloth=read_tsv(bounded/'DLC_BOUNDED_CLOTH_STRUCTURE_AUDIT.tsv')
        shared=read_tsv(bounded/'DLC_BOUNDED_SHARED_MEMBER_BINDINGS.tsv')
        textures=read_tsv(external/'DLC_EXTERNAL_TEXTURE_BINDINGS.tsv')

        clean_dir(output_root)
        blocks=block_index(params)
        mapping=[]
        for key, brows in sorted(blocks.items()):
            content, role, part, side, bi=key
            if content!='costume_pc00_bkn' or side!='source': continue
            source_control={k[4]:v for k,v in blocks.items() if k[:4]==('costume_pc00_twl',role,part,'source')}
            target_control={k[4]:v for k,v in blocks.items() if k[:4]==('costume_pc00_twl',role,part,'target')}
            sm_status, smatches=match_blocks(brows,source_control)
            target_candidates=[]; target_status='unmapped_source_control'
            additions=[]
            if len(smatches)==1:
                srows=source_control[smatches[0]]
                target_status,target_candidates=match_blocks(srows,target_control,remove_target_blend=True)
                for ti in target_candidates:
                    additions.extend(sorted({r['parameter_name'] for r in target_control[ti] if r['parameter_name'].casefold()=='parameterformeshblend'}))
            transitive='unique_control_bridge' if sm_status=='exact_unique' and target_status=='exact_unique' else ('ambiguous_control_bridge' if smatches or target_candidates else 'unresolved_control_bridge')
            mapping.append({
                'content_id':content,'parent_role':role,'member_part':part,'candidate_block_index':bi,
                'source_control_match_status':sm_status,'source_control_candidate_blocks':smatches,
                'target_control_match_status':target_status,'target_control_candidate_blocks':target_candidates,
                'target_control_added_parameters':sorted(set(additions)),'transitive_mapping_status':transitive,
                'evidence_strength':'structural_metadata_only','profile_build_allowed':False,
            })

        diff_by_member=defaultdict(list)
        for r in diffs: diff_by_member[(r['content_id'],r['parent_role'],r['member_name'])].append(r)
        control=[]
        for r in members:
            if r['content_id']!='costume_pc00_twl': continue
            ds=diff_by_member.get((r['content_id'],r['parent_role'],r['member_name']),[])
            added=sorted({d['parameter_name'] for d in ds if d['classification']=='added_in_target'})
            if r['compatibility_status']=='present_identical': cls='source_format_accepted_unchanged_in_control'
            elif r['compatibility_status']=='target_only_nested_member': cls='target_only_placeholder_or_container_member'
            elif r['parent_role']=='wet_model_or_container' and r['member_name'].casefold().endswith('.swg'): cls='quartet_wet_cloth_structure_augmentation'
            elif r['parent_role']=='wet_model_or_container' and r['nested_role']=='model_and_material': cls='quartet_wet_g1m_schema_augmentation'
            else: cls='control_modified_without_semantic_assignment'
            control.append({
                'content_id':r['content_id'],'parent_role':r['parent_role'],'member_name':r['member_name'],'nested_role':r['nested_role'],
                'source_size':r['source_size'],'target_size':r['target_size'],'compatibility_status':r['compatibility_status'],
                'added_parameter_count':len(added),'added_parameters':added,'control_delta_class':cls,
                'semantics_proven':False,'raw_payload_exported':False,
            })

        exact_shared=set()
        for r in shared:
            if 'costume_pc00_bkn' in r.get('content_ids','') and 'costume_pc00_twl' in r.get('content_ids',''):
                exact_shared.add(r['payload_sha256'])
        control_by=( {(r['parent_role'],member_part(r['member_name']),r['nested_role']):r for r in members if r['content_id']=='costume_pc00_twl'} )
        transfer=[]
        for r in members:
            if r['content_id']!='costume_pc00_bkn': continue
            part=member_part(r['member_name']); analogue=control_by.get((r['parent_role'],part,r['nested_role']))
            analogue_status=analogue['compatibility_status'] if analogue else 'no_exact_role_analogue'
            if r['parent_role']=='dry_model_or_container':
                classification='missing_portable_from_br1'; rationale='dry positive-control members of the same role are accepted unchanged by Quartet'
            elif r['nested_role']=='auxiliary_descriptor' and analogue_status=='present_identical':
                classification='missing_portable_from_br1'; rationale='wet positive-control descriptor is accepted unchanged by Quartet'
            elif r['parent_role']=='wet_model_or_container':
                classification='missing_requires_conversion'; rationale='wet positive control shows Quartet-only structural augmentation for the corresponding member class'
            else:
                classification='unknown_dependency'; rationale='no sufficiently narrow positive-control analogue'
            if r['source_sha256'] in exact_shared:
                rationale += '; exact source payload also occurs in a target-present control family'
            transfer.append({
                'content_id':r['content_id'],'parent_role':r['parent_role'],'member_name':r['member_name'],'nested_role':r['nested_role'],
                'source_size':r['source_size'],'source_sha256':r['source_sha256'],'existing_status':r['compatibility_status'],
                'positive_control_analogue_status':analogue_status,'control_derived_classification':classification,
                'exact_cross_family_target_present_payload':r['source_sha256'] in exact_shared,
                'rationale':rationale,'owner_specific_runtime_proven':False,'profile_build_allowed':False,
            })
        for r in textures:
            if r['content_id']!='costume_pc00_bkn': continue
            classification='missing_portable_from_br1' if r['texture_role']=='dry_texture' else 'unknown_dependency'
            rationale='dry G1T is a documented BR1 fallback; exact G1M slot binding remains unresolved' if r['texture_role']=='dry_texture' else 'wet G1T exists as BR1 fallback, but wet Quartet schema conversion and exact slot binding remain unresolved'
            transfer.append({
                'content_id':r['content_id'],'parent_role':r['texture_role'],'member_name':Path(r['source_path']).name,'nested_role':'external_texture',
                'source_size':r['source_size'],'source_sha256':r['source_sha256'],'existing_status':r['compatibility_status'],
                'positive_control_analogue_status':'external_texture_control_not_byte-parsed','control_derived_classification':classification,
                'exact_cross_family_target_present_payload':False,'rationale':rationale,
                'owner_specific_runtime_proven':False,'profile_build_allowed':False,
            })

        probes=[
            {'probe_id':'bkn_dry_parent_local_repack','content_id':'costume_pc00_bkn','scope':'dry parent + dry G1T','readiness':'evidence_ready_for_read_only_local_repack_test','required_before_probe':'exact parent/member hashes already recorded; preserve table/UI/unlock blocks','profile_build_allowed':False},
            {'probe_id':'bkn_wet_schema_delta_locator','content_id':'costume_pc00_bkn','scope':'wet G1M/SWG structural envelope','readiness':'requires_byte_range_mapping_from_positive_control','required_before_probe':'map Quartet-only parameterForMeshBlend records and SWG +16-byte envelope without assigning physics semantics','profile_build_allowed':False},
            {'probe_id':'bkn_texture_slot_binding','content_id':'costume_pc00_bkn','scope':'G1M to external G1T binding','readiness':'blocked','required_before_probe':'parse stable texture/reference sections or prove KTID/index binding','profile_build_allowed':False},
        ]

        write_tsv(output_root/'DLC_CONTROL_MATERIAL_BLOCK_MAPPING.tsv',[
            'content_id','parent_role','member_part','candidate_block_index','source_control_match_status','source_control_candidate_blocks','target_control_match_status','target_control_candidate_blocks','target_control_added_parameters','transitive_mapping_status','evidence_strength','profile_build_allowed'],mapping)
        write_tsv(output_root/'DLC_POSITIVE_CONTROL_STRUCTURAL_DELTA.tsv',[
            'content_id','parent_role','member_name','nested_role','source_size','target_size','compatibility_status','added_parameter_count','added_parameters','control_delta_class','semantics_proven','raw_payload_exported'],control)
        write_tsv(output_root/'DLC_CANDIDATE_TRANSFER_CLASSIFICATION.tsv',[
            'content_id','parent_role','member_name','nested_role','source_size','source_sha256','existing_status','positive_control_analogue_status','control_derived_classification','exact_cross_family_target_present_payload','rationale','owner_specific_runtime_proven','profile_build_allowed'],transfer)
        write_tsv(output_root/'DLC_CONTROL_DERIVED_NEXT_PROBES.tsv',[
            'probe_id','content_id','scope','readiness','required_before_probe','profile_build_allowed'],probes)
        write_tsv(output_root/'DLC_CONTROL_DERIVED_GAPS.tsv',[
            'content_id','dependency_type','status','next_evidence_needed','profile_build_allowed'],[
            {'content_id':'costume_pc00_bkn','dependency_type':'exact_texture_slot_binding','status':'unresolved','next_evidence_needed':'stable G1M texture/KTID/index reference mapping','profile_build_allowed':False},
            {'content_id':'costume_pc00_bkn','dependency_type':'wet_schema_byte_ranges','status':'unresolved','next_evidence_needed':'byte-range map of control G1M additions and SWG envelope extension','profile_build_allowed':False},
            {'content_id':'costume_pc00_bkn','dependency_type':'ui_unlock_runtime','status':'unresolved','next_evidence_needed':'owner-specific UI, availability and later transactional runtime validation','profile_build_allowed':False},
        ])
        summary={
            'type':'br_quartet_legacy_dlc_control_compatibility_summary','format_version':FORMAT_VERSION,'tool_version':TOOL_VERSION,
            'status':'positive_control_compatibility_derivation_complete_metadata_only',
            'material_block_mapping_rows':len(mapping),'unique_control_bridge_rows':sum(r['transitive_mapping_status']=='unique_control_bridge' for r in mapping),
            'ambiguous_control_bridge_rows':sum(r['transitive_mapping_status']=='ambiguous_control_bridge' for r in mapping),
            'positive_control_delta_rows':len(control),'candidate_transfer_rows':len(transfer),
            'classification_counts':dict(sorted(Counter(r['control_derived_classification'] for r in transfer).items())),
            'next_probe_rows':len(probes),
            'findings':[
                'the dry TWL control is accepted unchanged by Quartet at the audited member level',
                'the wet TWL control adds parameterForMeshBlend records and extends the SWG envelope',
                'BKN dry members receive portability-supporting control evidence but remain owner-runtime unproven',
                'BKN wet G1M/SWG members are conservatively classified as requiring conversion evidence',
                'exact G1M-to-G1T slot bindings, UI, unlock semantics and runtime compatibility remain unresolved'],
            'policy':{'raw_assets_exported':False,'profiles_built':False,'profiles_activated':False,'game_modified':False,'git_modified':False,'text_seed_unchanged':True,'profile_build_allowed':False},
            'next_action':'run a read-only dry-parent repack test and a separate byte-range locator for the wet positive-control schema delta; do not build a complete DLC profile',
        }
        write_json(output_root/'SUMMARY.json',summary)
        manifest=[]
        for p in sorted(output_root.iterdir(), key=lambda x:x.name.casefold()):
            if not p.is_file() or p.name=='REPORT_MANIFEST.json': continue
            if set(s.casefold() for s in p.suffixes)&FORBIDDEN_SUFFIXES: raise ControlCompatibilityError(f"forbidden asset report file: {p}")
            manifest.append({'path':p.name,'size':p.stat().st_size,'sha256':sha256_file(p)})
        write_json(output_root/'REPORT_MANIFEST.json',{'type':'br_report_manifest','format_version':1,'files':manifest})
    archive=reports/REPORT_ARCHIVE_NAME
    make_archive(output_root,archive)
    return archive,summary

def validate(report_root: Path) -> dict[str,Any]:
    required=['DLC_CONTROL_MATERIAL_BLOCK_MAPPING.tsv','DLC_POSITIVE_CONTROL_STRUCTURAL_DELTA.tsv','DLC_CANDIDATE_TRANSFER_CLASSIFICATION.tsv','DLC_CONTROL_DERIVED_NEXT_PROBES.tsv','DLC_CONTROL_DERIVED_GAPS.tsv','SUMMARY.json','REPORT_MANIFEST.json']
    for n in required:
        if not (report_root/n).is_file(): raise ControlCompatibilityError(f"missing report file: {n}")
    s=json.loads((report_root/'SUMMARY.json').read_text(encoding='utf-8'))
    if s.get('tool_version')!=TOOL_VERSION: raise ControlCompatibilityError('tool version mismatch')
    if s.get('policy',{}).get('profile_build_allowed') is not False: raise ControlCompatibilityError('profile build authorization forbidden')
    rows=read_tsv(report_root/'DLC_CANDIDATE_TRANSFER_CLASSIFICATION.tsv')
    if any(r['profile_build_allowed']!='false' for r in rows): raise ControlCompatibilityError('candidate row authorizes profile build')
    if not any(r['control_derived_classification']=='missing_requires_conversion' for r in rows): raise ControlCompatibilityError('missing wet conversion evidence')
    return s

def main() -> int:
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('audit'); a.add_argument('--project-root',type=Path,default=PROJECT_ROOT_DEFAULT); a.add_argument('--output-root',type=Path)
    v=sub.add_parser('validate-report'); v.add_argument('--report-root',type=Path,required=True)
    b=sub.add_parser('bundle-report'); b.add_argument('--report-root',type=Path,required=True); b.add_argument('--output',type=Path,required=True)
    ns=ap.parse_args()
    if ns.cmd=='audit':
        project=ns.project_root.resolve(); out=ns.output_root or project/'.local/reports/quartet_legacy_dlc'/REPORT_DIR_NAME
        archive,summary=audit(project,out); print(f"Control-derived compatibility rows: {summary['candidate_transfer_rows']}"); print(f"Report: {archive}")
    elif ns.cmd=='validate-report': print(json.dumps(validate(ns.report_root),sort_keys=True))
    else: validate(ns.report_root); make_archive(ns.report_root,ns.output); print(ns.output)
    return 0
if __name__=='__main__': raise SystemExit(main())
