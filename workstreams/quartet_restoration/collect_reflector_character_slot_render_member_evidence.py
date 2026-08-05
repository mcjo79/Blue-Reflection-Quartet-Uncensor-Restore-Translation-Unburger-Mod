#!/usr/bin/env python3
"""Audit character-slot render members for every Reflector heroine.

Stage 78 showed only Yuzuki rfl_50 differs at EBD level. This stage therefore
moves outside EBD and inventories changed character-slot render members from the
existing stage-7/8 evidence, grouping PCxx families without assigning heroine
names unless a strict binding already exists. No payload is written.
"""
from __future__ import annotations
import argparse, csv, json, os, re, subprocess, sys, tempfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

TOOL_VERSION="0.0.92"
REPORT_NAME="BR_quartet_restoration_reflector_character_slot_render_member_evidence.tar.zst"
REPORT_DIR="reflector_character_slot_render_member_evidence"
STAGE78_DIR="all_reflector_transformation_family_evidence"
STAGE78_ARCHIVE="BR_quartet_restoration_all_reflector_transformation_family_evidence.tar.zst"
STAGE76_DIR="transformation_brightness_evidence"
STAGE76_ARCHIVE="BR_quartet_restoration_transformation_brightness_evidence.tar.zst"
SLOT_RE=re.compile(r"(?i)(?:^|[^a-z0-9])pc(\d{2})(?:[^a-z0-9]|$)")
SLOT_INLINE_RE=re.compile(r"(?i)pc(\d{2})")
ROLE_PATTERNS=(
 ("ringlight", re.compile(r"ringlight",re.I)),
 ("eyelight", re.compile(r"eyelight",re.I)),
 ("light_loop", re.compile(r"light[_-]?loop",re.I)),
 ("lightpillar", re.compile(r"light[_-]?pillar",re.I)),
 ("reflector_character_container", re.compile(r"/character/pc\d{2}/pc\d{2}_rfl",re.I)),
 ("character_effect_container", re.compile(r"/effect/\d+_pc\d{2}",re.I)),
)
class Stage79Error(RuntimeError): pass
def require(c:bool,m:str)->None:
 if not c: raise Stage79Error(m)
def progress(m:str)->None: print(f"[stage79] {m}",file=sys.stderr,flush=True)
def parse_int(v:Any,d:int=0)->int:
 try:return int(str(v).strip())
 except:return d
def read_tsv(p:Path,required:bool=True)->list[dict[str,str]]:
 if not p.is_file():
  if required: raise Stage79Error(f"missing required TSV: {p}")
  return []
 with p.open(encoding='utf-8',newline='') as f:return [dict(r) for r in csv.DictReader(f,delimiter='\t')]
def write_tsv(p:Path,fields:Sequence[str],rows:Iterable[Mapping[str,Any]])->None:
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(fields),delimiter='\t',lineterminator='\n',extrasaction='ignore');w.writeheader()
  for r in rows:w.writerow({k:r.get(k,'') for k in fields})
def load_json(p:Path)->dict[str,Any]:
 require(p.is_file(),f"missing required JSON: {p}")
 d=json.loads(p.read_text(encoding='utf-8'));require(isinstance(d,dict),f"JSON root must be object: {p}");return d
def safe_name(s:str)->str:
 p=PurePosixPath(s);require(not p.is_absolute() and '..' not in p.parts and p.parts,f"unsafe archive member: {s}");return p.as_posix()
def extract_archive(a:Path,d:Path)->Path:
 require(a.is_file(),f"missing prerequisite report: {a}")
 q=subprocess.run(['tar','--zstd','-tf',str(a)],text=True,capture_output=True);require(q.returncode==0,q.stderr.strip())
 roots={PurePosixPath(safe_name(x.strip())).parts[0] for x in q.stdout.splitlines() if x.strip()};require(len(roots)==1,f"expected one root in {a}")
 d.mkdir(parents=True,exist_ok=True);q=subprocess.run(['tar','--zstd','-xf',str(a),'-C',str(d)],text=True,capture_output=True);require(q.returncode==0,q.stderr.strip());return d/next(iter(roots))
def locate(root:Path,direct:str,archive:str,temp:Path)->Path:
 p=root/direct
 return p if p.is_dir() else extract_archive(root/archive,temp)
def role_for(path:str,member:str)->str:
 text=f"{path} {member}"
 for role,pat in ROLE_PATTERNS:
  if pat.search(text):return role
 return "other_character_slot_render_member"
def slot_for(path:str,member:str)->str:
 m=SLOT_INLINE_RE.search(f"{member} {path}");return f"PC{m.group(1)}" if m else ""
def normalized_family(role:str,member:str,path:str)->str:
 base=member or PurePosixPath(path).name
 return f"{role}:{SLOT_INLINE_RE.sub('PCXX',base.casefold())}"
def validate78(root:Path)->dict[str,Any]:
 s=load_json(root/'SUMMARY.json');require(s.get('type')=='br_quartet_restoration_all_reflector_transformation_family_evidence_summary','stage78 type mismatch');require(s.get('tool_version')=='0.0.91','stage78 must be 0.0.91');require(parse_int(s.get('changed_event_rows'),-1)==1,'stage78 changed event count must be 1');require(parse_int(s.get('other_than_stage77_yuzuki_changed_event_rows'),-1)==0,'unexpected other changed heroine EBD');return s
def validate76(root:Path)->dict[str,Any]:
 s=load_json(root/'SUMMARY.json');require(s.get('type')=='br_quartet_restoration_transformation_brightness_evidence_summary','stage76 type mismatch');require(s.get('tool_version')=='0.0.88','stage76 must be 0.0.88');return s
def build_report(project_root:Path,create_archive:bool=True)->tuple[Path,Path|None,dict[str,Any]]:
 project_root=project_root.resolve(); rr=project_root/'.local/reports/quartet_restoration';require(rr.is_dir(),f"missing report root: {rr}")
 progress('validating stage 76 and stage 78 reports')
 with tempfile.TemporaryDirectory(prefix='br-stage79-') as td:
  t=Path(td);r78=locate(rr,STAGE78_DIR,STAGE78_ARCHIVE,t/'78');r76=locate(rr,STAGE76_DIR,STAGE76_ARCHIVE,t/'76');s78=validate78(r78);s76=validate76(r76)
  rows=read_tsv(r76/'TRANSFORMATION_BRIGHTNESS_EXISTING_EVIDENCE.tsv')
  progress(f'loaded {len(rows)} existing render-evidence rows')
  dedup={}
  for r in rows:
   path=str(r.get('normalized_path',''));member=str(r.get('member_name',''));slot=slot_for(path,member)
   if not slot: continue
   role=role_for(path,member)
   if role=='other_character_slot_render_member' and not any(x in (path+' '+member).casefold() for x in ('rfl','reflector','light','bright','glare','bloom','emiss')):continue
   key=(path.casefold(),member.casefold(),role)
   row={
    'character_slot':slot,'asset_role':role,'family_key':normalized_family(role,member,path),'normalized_path':path,'member_name':member,'member_key':r.get('member_key',''),'candidate_id':r.get('candidate_id',''),'domain':r.get('domain',''),'priority':r.get('priority',''),'change_classification':r.get('change_classification',''),'evidence_sources':r.get('evidence_source',''),'lead_classification':r.get('lead_classification',''),'review_status':'slot_render_member_changed_static_binding_to_heroine_name_unresolved'
   }
   if key in dedup:
    src=set(dedup[key]['evidence_sources'].split(';'));src.add(str(r.get('evidence_source','')));dedup[key]['evidence_sources']=';'.join(sorted(x for x in src if x))
   else:dedup[key]=row
  member_rows=sorted(dedup.values(),key=lambda x:(x['character_slot'],x['asset_role'],x['normalized_path'],x['member_name'].casefold()))
  progress(f'identified {len(member_rows)} unique character-slot render members')
  fam=defaultdict(list)
  for r in member_rows:fam[r['family_key']].append(r)
  family_rows=[]
  for k,vals in sorted(fam.items()):
   slots=sorted({v['character_slot'] for v in vals});classes=Counter(v['change_classification'] or 'unknown' for v in vals)
   if len(slots)>=3 and len(classes)==1 and next(iter(classes))=='changed': cls='uniform_changed_across_slots'
   elif len(slots)>=2 and len(classes)==1: cls='uniform_cross_slot_classification'
   else: cls='mixed_or_slot_selective'
   family_rows.append({'family_key':k,'asset_role':vals[0]['asset_role'],'slot_count':len(slots),'slots':';'.join(slots),'member_rows':len(vals),'change_classifications':';'.join(f'{a}:{b}' for a,b in sorted(classes.items())),'family_classification':cls,'review_status':'binary_family_audit_required_before_any_restore'})
  slot_rows=[]
  byslot=defaultdict(list)
  for r in member_rows:byslot[r['character_slot']].append(r)
  for slot,vals in sorted(byslot.items()):
   roles=Counter(v['asset_role'] for v in vals)
   slot_rows.append({'character_slot':slot,'member_rows':len(vals),'changed_member_rows':sum(1 for v in vals if v['change_classification']=='changed'),'roles':';'.join(f'{a}:{b}' for a,b in sorted(roles.items())),'heroine_name_binding':'unresolved','event_family_binding':'','review_status':'do_not_assign_name_from_slot_number_without_strict_binding'})
  out=rr/REPORT_DIR
  if out.exists():
   import shutil;shutil.rmtree(out)
  out.mkdir(parents=True)
  write_tsv(out/'REFLECTOR_CHARACTER_SLOT_INVENTORY.tsv',['character_slot','member_rows','changed_member_rows','roles','heroine_name_binding','event_family_binding','review_status'],slot_rows)
  write_tsv(out/'REFLECTOR_SLOT_RENDER_MEMBERS.tsv',['character_slot','asset_role','family_key','normalized_path','member_name','member_key','candidate_id','domain','priority','change_classification','evidence_sources','lead_classification','review_status'],member_rows)
  write_tsv(out/'REFLECTOR_RENDER_MEMBER_FAMILIES.tsv',['family_key','asset_role','slot_count','slots','member_rows','change_classifications','family_classification','review_status'],family_rows)
  mapping=[{'event_family_id':x,'changed_event_rows':'1' if x=='party:yuzuki' else '0','candidate_character_slot':'','binding_status':'unresolved','review_status':'event_family_to_PC_slot_binding_not_present_in_static_evidence'} for x in ('party:yuzuki','party:raimu')]
  write_tsv(out/'REFLECTOR_EVENT_FAMILY_SLOT_BINDING.tsv',['event_family_id','changed_event_rows','candidate_character_slot','binding_status','review_status'],mapping)
  summary={'type':'br_quartet_restoration_reflector_character_slot_render_member_evidence_summary','format_version':1,'tool_version':TOOL_VERSION,'source_stage78_tool_version':s78.get('tool_version'),'source_stage76_tool_version':s76.get('tool_version'),'status':'all_character_slot_render_member_families_inventoried_heroine_slot_binding_and_brightness_semantics_unresolved','character_slot_rows':len(slot_rows),'slot_member_rows':len(member_rows),'render_member_family_rows':len(family_rows),'uniform_changed_family_rows':sum(1 for x in family_rows if x['family_classification']=='uniform_changed_across_slots'),'ringlight_family_rows':sum(1 for x in family_rows if x['asset_role']=='ringlight'),'eyelight_family_rows':sum(1 for x in family_rows if x['asset_role']=='eyelight'),'event_family_slot_binding_rows':len(mapping),'resolved_event_family_slot_binding_rows':0,'policy':{'installed_game_modified':False,'render_payload_written':False,'global_bloom_hdr_gamma_or_exposure_restore_attempted':False,'pak_repacked':False,'core_registry_modified':False,'profile_activated':False,'runtime_validation_inferred':False,'censorship_semantics_inferred':False,'heroine_names_inferred_from_slot_numbers':False,'canary_track_modified':False},'next_action':'Upload this report. Deep-audit uniform and slot-selective ringlight/eyelight families by rehydrating exact Original/Quartet members, comparing cross-slot delta shapes, and resolving PC slot names only from strict technical bindings. Do not restore global brightness or all PC slots as a group without reversible member-level evidence.'}
  (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
  archive=None
  if create_archive:
   archive=rr/REPORT_NAME;tmp=archive.with_suffix(archive.suffix+'.tmp');tmp.unlink(missing_ok=True);q=subprocess.run(['tar','--zstd','-cf',str(tmp),'-C',str(out.parent),out.name],text=True,capture_output=True);require(q.returncode==0,q.stderr.strip());os.replace(tmp,archive)
  progress('completed')
  return out,archive,summary

def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,required=True);p.add_argument('--no-report-archive',action='store_true');a=p.parse_args()
 try:
  out,arc,s=build_report(a.project_root,not a.no_report_archive);print(f"Report directory: {out}");print(f"Character slots: {s['character_slot_rows']}; render families: {s['render_member_family_rows']}");
  if arc:print(f"Report: {arc}")
  return 0
 except Stage79Error as e: print(f"ERROR: {e}",file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
