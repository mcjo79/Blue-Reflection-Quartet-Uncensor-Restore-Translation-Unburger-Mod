#!/usr/bin/env python3
"""Stage 137: bounded exact-parser queues from the complete stage-136 G1E/KPS sweep.

Consumes only metadata-only stage-136 evidence. It selects all recurrent G1E
structure families, high-recurrence dword transitions, and every KPS path/program
with executable, interface, inventory or target-addition differences. It does
not assign field/visual/censorship semantics and does not authorize writes.
"""
from __future__ import annotations

import argparse, csv, hashlib, json, os, shutil, subprocess, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION = "0.1.55"
REPORT_DIR = "effect_posteffect_bounded_exact_parser_queue_evidence"
REPORT_NAME = "BR_quartet_restoration_effect_posteffect_bounded_exact_parser_queue_evidence.tar.zst"
STAGE136_NAME = "BR_quartet_restoration_effect_posteffect_g1e_kps_structural_sweep_evidence.tar.zst"
STAGE136_SHA256 = "f1e44fbde4d19dc27bba548ca41c5b7154e85066740fc841a73174043b101fcc"
STAGE136_DIR = "effect_posteffect_g1e_kps_structural_sweep_evidence"
STAGE136_SUMMARY_SHA256 = "003799b23721ca11da0c116a227195f22f4f2da6452b0945f4b7f6e47d29c56c"
FORBIDDEN_EXTENSIONS = (".pak", ".g1e", ".g1em", ".g1t", ".g1s", ".kps", ".dxbc", ".elixir", ".elixir.gz", ".ebd", ".ebm")

class CollectorError(RuntimeError): pass

def require(c: bool, m: str) -> None:
    if not c: raise CollectorError(m)

def sha256_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def safe_relative(v: str, label: str) -> str:
    p=PurePosixPath(str(v).replace('\\','/'))
    require(bool(p.parts) and not p.is_absolute() and '..' not in p.parts, f"unsafe {label}: {v}")
    return p.as_posix()

def read_tsv(p: Path) -> list[dict[str,str]]:
    require(p.is_file(), f"missing TSV: {p}")
    with p.open(encoding='utf-8',newline='') as f: return [dict(r) for r in csv.DictReader(f,delimiter='\t')]

def write_tsv(p: Path, fields: Sequence[str], rows: Iterable[Mapping[str,Any]]) -> None:
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(fields),delimiter='\t',lineterminator='\n',extrasaction='ignore'); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,'') for k in fields})

def atomic_json(p: Path, obj: Mapping[str,Any]) -> None:
    q=p.with_name(p.name+'.tmp'); q.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n',encoding='utf-8'); os.replace(q,p)

def extract_report(a: Path, dest: Path) -> Path:
    listed=subprocess.run(['tar','--zstd','-tf',str(a)],text=True,capture_output=True)
    require(listed.returncode==0,listed.stderr.strip() or 'cannot list prerequisite')
    names=[safe_relative(x,'report member') for x in listed.stdout.splitlines() if x.strip()]
    require(names and {PurePosixPath(x).parts[0] for x in names}=={STAGE136_DIR},'unexpected prerequisite root')
    dest.mkdir(parents=True,exist_ok=True)
    c=subprocess.run(['tar','--zstd','-xf',str(a),'-C',str(dest)],text=True,capture_output=True)
    require(c.returncode==0,c.stderr.strip() or 'cannot extract prerequisite')
    return dest/STAGE136_DIR

def make_archive(src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True,exist_ok=True); tmp=out.with_name(out.name+'.tmp'); tmp.unlink(missing_ok=True)
    c=subprocess.run(['tar','--zstd','-cf',str(tmp),'-C',str(src.parent),src.name],text=True,capture_output=True)
    require(c.returncode==0,c.stderr.strip() or 'archive creation failed'); os.replace(tmp,out)

def bool_text(v: object) -> bool: return str(v).strip().casefold() in {'1','true','yes'}

def recurrence_tier(n: int) -> str:
    if n>=10:return 'broad_ge_10_members'
    if n>=5:return 'medium_5_9_members'
    return 'small_2_4_members'

def family_queue_kind(disposition: str) -> str:
    if disposition=='same_size_replacement_only': return 'fixed_size_record_layout_parser_queue'
    if disposition=='mixed_structural_delta': return 'mixed_alignment_record_layout_parser_queue'
    return 'other_structural_layout_parser_queue'

def build_report(project_root: Path, *, report_root: Path|None=None, output_report_root: Path|None=None, create_archive: bool=True):
    project_root=project_root.resolve()
    report_root=(report_root or project_root/'.local/reports/quartet_restoration').resolve()
    output_report_root=(output_report_root or report_root).resolve()
    version=(project_root/'workstreams/quartet_restoration/VERSION').read_text().strip()
    require(tuple(map(int,version.split('.'))) >= (0,1,55), f"stage 137 requires version >= 0.1.55, got {version}")
    archive=report_root/STAGE136_NAME
    require(archive.is_file(),f"missing prerequisite: {archive}")
    ah=sha256_file(archive); require(ah==STAGE136_SHA256,f"unexpected stage136 SHA-256: {ah}")
    temp=output_report_root/'.stage137_prereq_tmp'; shutil.rmtree(temp,ignore_errors=True)
    root=report_root/STAGE136_DIR
    if not root.is_dir(): root=extract_report(archive,temp)
    sh=sha256_file(root/'SUMMARY.json'); require(sh==STAGE136_SUMMARY_SHA256,f"unexpected stage136 summary SHA-256: {sh}")
    summary136=json.loads((root/'SUMMARY.json').read_text())
    require(summary136['g1e_member_rows']==621 and summary136['kps_member_rows']==27,'unexpected stage136 member counts')
    require(summary136['g1e_structure_family_rows']==126 and summary136['g1e_recurrent_structure_family_rows']==83,'unexpected stage136 family counts')
    require(summary136['skipped_rows']==0,'stage136 has skipped rows')

    members=read_tsv(root/'G1E_STRUCTURAL_PAIR_AUDIT.tsv')
    families=read_tsv(root/'G1E_STRUCTURE_FAMILIES.tsv')
    transitions=read_tsv(root/'G1E_DWORD_TRANSITION_AUDIT.tsv')
    kps_paths=read_tsv(root/'KPS_PATH_CLASSIFICATION.tsv')
    kps_programs=read_tsv(root/'KPS_DXBC_PROGRAM_CLASSIFICATION.tsv')
    carry=read_tsv(root/'UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv')
    require(len(members)==621 and len(families)==126 and len(kps_paths)==27 and len(carry)==25,'stage136 table cardinality drift')

    member_by_key={(r['normalized_path'],r['member_key']):r for r in members}
    family_members=defaultdict(list)
    for r in members: family_members[r['structure_family_id']].append(r)
    family_queue=[]
    for f in families:
        if not bool_text(f['recurrent_family']): continue
        rows=family_members[f['structure_family_id']]
        require(len(rows)==int(f['member_rows']),'family member count drift')
        family_queue.append({
            'structure_family_id':f['structure_family_id'], 'g1e_structure_disposition':f['g1e_structure_disposition'],
            'parser_queue_kind':family_queue_kind(f['g1e_structure_disposition']), 'recurrence_tier':recurrence_tier(len(rows)),
            'member_rows':len(rows), 'container_path_rows':len({r['normalized_path'] for r in rows}),
            'normalized_role_rows':len({r['normalized_member_role'] for r in rows}), 'delta_shapes':f['delta_shapes'],
            'match_run_rows':sum(int(r['match_run_rows']) for r in rows),
            'alignment_segment_rows':sum(int(r['alignment_segment_rows']) for r in rows),
            'target_insertion_segment_rows':sum(int(r['target_insertion_segment_rows']) for r in rows),
            'target_deletion_segment_rows':sum(int(r['target_deletion_segment_rows']) for r in rows),
            'same_size_replacement_segment_rows':sum(int(r['same_size_replacement_segment_rows']) for r in rows),
            'size_changing_replacement_segment_rows':sum(int(r['size_changing_replacement_segment_rows']) for r in rows),
            'changed_word_rows':sum(int(r['changed_word_rows']) for r in rows),
            'member_examples':f['member_examples'], 'field_semantics_confirmed':False,
            'visual_or_censorship_semantics_confirmed':False,'runtime_confirmed':False,'write_authorized':False,
        })
    family_queue.sort(key=lambda r:(-int(r['member_rows']),r['structure_family_id']))
    require(len(family_queue)==83,'expected 83 recurrent G1E families')

    tg=defaultdict(lambda:{'rows':0,'members':set(),'families':set(),'paths':set(),'roles':set(),'classes':set(),'src':set(),'dst':set()})
    for r in transitions:
        key=(r['normalized_path'],r['member_key']); require(key in member_by_key,'transition member missing')
        m=member_by_key[key]; x=tg[r['transition_id']]; x['rows']+=1; x['members'].add(key); x['families'].add(m['structure_family_id']); x['paths'].add(r['normalized_path']); x['roles'].add(m['normalized_member_role']); x['classes'].add(r['transition_classification']); x['src'].add(r['source_u32_hex']); x['dst'].add(r['target_u32_hex'])
    transition_queue=[]
    for tid,x in tg.items():
        if len(x['members'])<10 or len(x['families'])<3: continue
        classes=sorted(x['classes'])
        if 'possible_relative_offset_or_length_rebase' in x['classes']: kind='offset_or_length_rebase_exact_parser_queue'
        elif 'finite_float_transition_unresolved' in x['classes']: kind='float_looking_leaf_exact_parser_queue_unresolved'
        elif 'small_integer_or_flag_transition' in x['classes']: kind='small_integer_or_flag_exact_parser_queue'
        else: kind='opaque_high_recurrence_exact_parser_queue'
        transition_queue.append({'transition_id':tid,'parser_queue_kind':kind,'transition_classifications':' || '.join(classes),
            'source_u32_values':' || '.join(sorted(x['src'])),'target_u32_values':' || '.join(sorted(x['dst'])),
            'transition_rows':x['rows'],'member_rows':len(x['members']),'structure_family_rows':len(x['families']),
            'container_path_rows':len(x['paths']),'normalized_role_rows':len(x['roles']),
            'field_semantics_confirmed':False,'visual_or_censorship_semantics_confirmed':False,'runtime_confirmed':False,'write_authorized':False})
    transition_queue.sort(key=lambda r:(-int(r['member_rows']),-int(r['structure_family_rows']),r['transition_id']))
    require(len(transition_queue)==646,'expected 646 high-recurrence G1E transitions')

    metadata_disp='nonexecutive_metadata_or_compiler_delta'
    kps_path_queue=[]; kps_controls=[]
    for r in kps_paths:
        out=dict(r); out['field_semantics_confirmed']=False; out['visual_or_censorship_semantics_confirmed']=False; out['runtime_confirmed']=False; out['write_authorized']=False
        if r['kps_path_disposition']==metadata_disp: kps_controls.append(out)
        else:
            out['parser_queue_kind']={
                'executable_code_delta_interface_stable':'instruction_delta_stable_interface_parser_queue',
                'executable_code_delta_with_interface_delta':'instruction_and_interface_delta_parser_queue',
                'dxbc_program_inventory_delta':'program_inventory_and_pairing_parser_queue',
                'target_added_kps':'target_added_program_inventory_parser_queue',
            }.get(r['kps_path_disposition'],'other_kps_parser_queue')
            kps_path_queue.append(out)
    kps_path_queue.sort(key=lambda r:(r['kps_path_disposition'],r['member_name']))
    kps_controls.sort(key=lambda r:r['member_name'])
    require(len(kps_path_queue)==6 and len(kps_controls)==21,'unexpected KPS path partition')

    kps_program_queue=[]
    for r in kps_programs:
        if r['classification']==metadata_disp: continue
        out=dict(r); out['field_semantics_confirmed']=False; out['visual_or_censorship_semantics_confirmed']=False; out['runtime_confirmed']=False; out['write_authorized']=False
        kps_program_queue.append(out)
    require(len(kps_program_queue)==43,'expected 43 non-metadata KPS program rows')

    out=output_report_root/REPORT_DIR; shutil.rmtree(out,ignore_errors=True); out.mkdir(parents=True)
    write_tsv(out/'INPUT_HASHES.tsv',['input_id','relative_path','sha256','verified'],[
        {'input_id':STAGE136_DIR,'relative_path':STAGE136_NAME,'sha256':ah,'verified':True},
        {'input_id':f'{STAGE136_DIR}_summary','relative_path':f'{STAGE136_DIR}/SUMMARY.json','sha256':sh,'verified':True},])
    write_tsv(out/'G1E_RECURRENT_STRUCTURE_FAMILY_PARSER_QUEUE.tsv',list(family_queue[0]),family_queue)
    write_tsv(out/'G1E_HIGH_RECURRENCE_TRANSITION_PARSER_QUEUE.tsv',list(transition_queue[0]),transition_queue)
    write_tsv(out/'KPS_EXACT_PARSER_PATH_QUEUE.tsv',list(kps_path_queue[0]),kps_path_queue)
    write_tsv(out/'KPS_EXACT_PARSER_PROGRAM_QUEUE.tsv',list(kps_program_queue[0]),kps_program_queue)
    write_tsv(out/'KPS_METADATA_ONLY_CONTROL_PATHS.tsv',list(kps_controls[0]),kps_controls)
    write_tsv(out/'UNRESOLVED_G1EM_G1T_SHADER_CARRY_FORWARD.tsv',list(carry[0]),carry)
    write_tsv(out/'PARSER_QUEUE_SKIPPED.tsv',['scope','identity','reason'],[])

    fam_tiers=Counter(r['recurrence_tier'] for r in family_queue); fam_kinds=Counter(r['parser_queue_kind'] for r in family_queue)
    trans_kinds=Counter(r['parser_queue_kind'] for r in transition_queue); kps_disps=Counter(r['kps_path_disposition'] for r in kps_path_queue)
    summary={
      'type':'br_quartet_restoration_effect_posteffect_bounded_exact_parser_queue_evidence_summary','format_version':1,'tool_version':TOOL_VERSION,
      'status':'recurrent_g1e_and_nonmetadata_kps_exact_parser_queues_bounded_semantics_unresolved_no_write',
      'stage136_report_sha256':ah,'stage136_summary_sha256':sh,
      'g1e_structure_family_rows':126,'g1e_recurrent_structure_family_queue_rows':len(family_queue),'g1e_nonrecurrent_control_family_rows':43,
      'g1e_recurrent_family_tiers':dict(sorted(fam_tiers.items())),'g1e_recurrent_family_queue_kinds':dict(sorted(fam_kinds.items())),
      'g1e_high_recurrence_transition_queue_rows':len(transition_queue),'g1e_high_recurrence_transition_queue_kinds':dict(sorted(trans_kinds.items())),
      'g1e_offset_or_length_candidate_rows':sum('possible_relative_offset_or_length_rebase' in r['transition_classifications'] for r in transition_queue),
      'g1e_float_looking_candidate_rows':sum('finite_float_transition_unresolved' in r['transition_classifications'] for r in transition_queue),
      'kps_exact_parser_path_queue_rows':len(kps_path_queue),'kps_exact_parser_path_dispositions':dict(sorted(kps_disps.items())),
      'kps_exact_parser_program_queue_rows':len(kps_program_queue),'kps_metadata_only_control_path_rows':len(kps_controls),
      'unresolved_g1em_g1t_shader_rows':len(carry),'skipped_rows':0,'field_semantics_confirmed_rows':0,
      'visual_or_censorship_semantics_confirmed_rows':0,'runtime_confirmed_rows':0,'write_authorized_rows':0,
      'policy':{'existing_evidence_only':True,'local_proprietary_payloads_read':False,'proprietary_payloads_in_report':False,
        'recurrence_alignment_dword_float_or_dxbc_delta_treated_as_semantic_proof':False,'runtime_or_save_required':False,
        'pak_built_or_repacked':False,'installed_game_modified':False,'profile_or_registry_modified':False,'core_modified':False,
        'translation_modified':False,'legacy_dlc_modified':False,'git_modified':False},
      'next_action':'Implement exact record-layout parsing first against the seven broad recurrent G1E families, using the complete 83-family and 646-transition queues only as calibration. Independently parse the six non-metadata KPS paths and 43 program rows. Keep all leaf meaning, G1EM/G1T and fifteen shaders unresolved; do not require saves or authorize writes.'}
    atomic_json(out/'SUMMARY.json',summary)
    report_archive=output_report_root/REPORT_NAME
    if create_archive: make_archive(out,report_archive)
    shutil.rmtree(temp,ignore_errors=True)
    return (report_archive if create_archive else None),summary

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[2]); ap.add_argument('--report-root',type=Path); ap.add_argument('--output-report-root',type=Path); ap.add_argument('--no-archive',action='store_true'); a=ap.parse_args()
    arch,s=build_report(a.project_root,report_root=a.report_root,output_report_root=a.output_report_root,create_archive=not a.no_archive)
    print(json.dumps(s,indent=2,sort_keys=True));
    if arch: print(f"[bounded-parser-queue] report archive: {arch}")
    return 0
if __name__=='__main__': raise SystemExit(main())
