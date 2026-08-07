#!/usr/bin/env python3
"""Stage 161: build a no-install Hinako wet-school Fast Test profile.

The profile keeps the runtime-stable School_Wet geometry and runtime-supported
wet-surface G1T entry 23 from stage 158, then adds only a target-native BC3
entry-43 candidate: Quartet RGB/header/resolution with the scaled Original wet
alpha blocks established by stage 160.  Installed game files are never written.
"""
from __future__ import annotations
import argparse,csv,hashlib,importlib.util,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path,PurePosixPath
from typing import Any,Iterable,Mapping,Sequence

SCRIPT_DIR=Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT=SCRIPT_DIR.parent.parent
TOOL_VERSION="0.1.82"
PROFILE_ID="fast_test_pc00_scl_w_school_entry23_target_native_alpha43_568fc2f9a095"
TARGET_RELATIVE_PATH="Data/PACK10_02.PAK"
EXPECTED_BASELINE_SHA256="e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302"
EXPECTED_BASELINE_SIZE=11402829898
EXPECTED_STAGE157_PROFILE_SHA256="9b70d0cff0ef86666b223fdcfe105b54dff25d6db664a3c965d9e748d85fa9fc"
STAGE157_REPORT="BR_quartet_restoration_hinako_wet_school_entry23_fast_test_profile_evidence.tar.zst"
STAGE157_PROFILE_ID="fast_test_pc00_scl_w_school_wet_plus_entry23_cb35139a7e44"
STAGE157_PROFILE_RELATIVE=Path(".local/build/quartet_restoration/fast_test_lab/wet_school_entry23_pc00")/STAGE157_PROFILE_ID/"output/Data/PACK10_02.PAK"
STAGE157_SHA256="4d307dae7e56c7004a90135061727873662bc6262a0984d90c395e93ba34639c"
STAGE160_REPORT="BR_quartet_restoration_hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence.tar.zst"
STAGE160_SHA256="d7d97892d61c3b598eb48f69425376a50b154655c52eecb6731c618aa42b98d6"
STAGE158_ACTIVATION_SHA256="e792b19ebe128469db689b68059ddb4de5180dbc1c0765df1b4e1fb9a967084e"
STAGE158_ROLLBACK_SHA256="7789949d0e99d1f530ea92d6f5d2f90c6c94b89049061319f1f8ce0703340c6b"
EXPECTED_ENTRY23_PROFILE_RAW_SHA256="cb35139a7e4435710f6228141fc4e9468f109726c3f2770faf8f73b8454aa047"
EXPECTED_ENTRY43_SOURCE_PAYLOAD_SHA256="17b555e973afa9a3c69d4db703daa104a848477095d0ad1e13ae35a900a88a7b"
EXPECTED_ENTRY43_TARGET_PAYLOAD_SHA256="37b40e340476d9b7c6879aecace13a374854f011a838a7fe2b8bc54205fd0719"
EXPECTED_ENTRY43_CANDIDATE_PAYLOAD_SHA256="568fc2f9a095e28fb12fa3f15ad4157664842687ae49b8dcb5f619f3552f466f"
TARGET_PARENT_SUFFIX="data/b1/x64/character/pc00/pc00_scl_w.elixir.gz"
TARGET_G1T_SUFFIX="data/b1/x64/character/pc00/pc00_scl_w.g1t"
SOURCE_G1T_PATH="data/x64/character/pc00/pc00_scl_w.g1t"
ENTRY23=23; ENTRY43=43
REPORT_DIR="hinako_wet_school_entry23_entry43_alpha_fast_test_profile_evidence"
REPORT_NAME="BR_quartet_restoration_hinako_wet_school_entry23_entry43_alpha_fast_test_profile_evidence.tar.zst"
WORKSPACE_SUBDIR=Path("fast_test_lab/wet_school_entry23_entry43_alpha_pc00")
MANIFEST_SUBDIR=Path("core_profiles/fast_test_lab")
FORBIDDEN_REPORT_EXTENSIONS=(".pak",".g1m",".g1t",".g1s",".g1e",".g1em",".elixir",".elixir.gz",".ebd",".ebm",".kps",".dds",".png")

class Stage161Error(RuntimeError): pass
def require(c:bool,m:str)->None:
    if not c: raise Stage161Error(m)
def progress(m:str)->None: print(f"[stage161] {m}",flush=True)
def sha256_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(8*1024*1024),b""): h.update(b)
    return h.hexdigest()
def sha256_bytes(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def load_module(path:Path,name:str)->Any:
    spec=importlib.util.spec_from_file_location(name,path); require(spec is not None and spec.loader is not None,f"cannot load {path}")
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m
def safe_relative(v:str,label:str)->str:
    p=PurePosixPath(str(v).replace("\\","/"));require(p.parts and not p.is_absolute() and ".." not in p.parts,f"unsafe {label}: {v}");return p.as_posix()
def write_tsv(path:Path,fields:Sequence[str],rows:Iterable[Mapping[str,Any]])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(fields),delimiter="\t",lineterminator="\n",extrasaction="ignore");w.writeheader()
        for r in rows:w.writerow({k:r.get(k,"") for k in fields})
def atomic_json(path:Path,v:Mapping[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True);t=path.with_name(path.name+".tmp");t.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(t,path)
def make_archive(src:Path,out:Path)->None:
    out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_name(out.name+".tmp");tmp.unlink(missing_ok=True)
    cp=subprocess.run(["tar","--zstd","-cf",str(tmp),"-C",str(src.parent),src.name],capture_output=True,text=True);require(cp.returncode==0,cp.stderr.strip() or "archive creation failed");os.replace(tmp,out)

def verify_report(report_root:Path,name:str,expected_sha:str,expected_type:str)->dict[str,Any]:
    p=report_root/name;require(p.is_file(),f"missing prerequisite evidence: {p}");actual=sha256_file(p);require(actual==expected_sha,f"prerequisite SHA drift {name}: {actual}")
    with tempfile.TemporaryDirectory(prefix="stage161-prereq-") as td:
        ls=subprocess.run(["tar","--zstd","-tf",str(p)],capture_output=True,text=True);require(ls.returncode==0,ls.stderr.strip() or "cannot list report")
        names=[safe_relative(x.strip(),"report member") for x in ls.stdout.splitlines() if x.strip()];require(names,"empty report")
        require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names),"payload in metadata evidence")
        cp=subprocess.run(["tar","--zstd","-xf",str(p),"-C",td],check=False);require(cp.returncode==0,"cannot extract report")
        roots=list(Path(td).iterdir());require(len(roots)==1,"unexpected report root")
        s=json.loads((roots[0]/"SUMMARY.json").read_text(encoding="utf-8"));require(s.get("type")==expected_type,"prerequisite type drift");return s

def find_member(members:Mapping[str,Mapping[str,Any]],suffix:str,label:str):
    ms=[(k,r) for k,r in members.items() if str(r.get("name","")).replace("\\","/").casefold().endswith(suffix.casefold())]
    require(len(ms)==1,f"expected one {label}, found {len(ms)}");return ms[0]

def g1t_change_rows(stage155:Any,stage156:Any,baseline:bytes,candidate:bytes)->list[dict[str,Any]]:
    b=stage155.parse_g1t(baseline,"stage161-baseline-g1t");c=stage155.parse_g1t(candidate,"stage161-candidate-g1t");require(b["texture_count"]==c["texture_count"],"texture count changed")
    rows=[]
    for i in range(int(b["texture_count"])):
        rb=stage156.raw_entry(baseline,b,i);rc=stage156.raw_entry(candidate,c,i);changed=rb!=rc
        rows.append({"texture_index":i,"changed":changed,"expected_changed":i in {ENTRY23,ENTRY43},"baseline_raw_sha256":sha256_bytes(rb),"candidate_raw_sha256":sha256_bytes(rc),"verified":changed==(i in {ENTRY23,ENTRY43})})
    require([r["texture_index"] for r in rows if r["changed"]]==[ENTRY23,ENTRY43],"G1T did not change exactly entries 23 and 43")
    return rows

def make_entry43_candidate(stage155:Any,stage156:Any,stage160:Any,source_g1t:bytes,target_g1t:bytes)->tuple[bytes,dict[str,Any]]:
    sp=stage155.parse_g1t(source_g1t,"stage161-source-scl_w");tp=stage155.parse_g1t(target_g1t,"stage161-target-scl_w")
    sr=sp["entries"][ENTRY43];tr=tp["entries"][ENTRY43]
    require(sr["payload_sha256"]==EXPECTED_ENTRY43_SOURCE_PAYLOAD_SHA256,"source entry43 payload drift");require(tr["payload_sha256"]==EXPECTED_ENTRY43_TARGET_PAYLOAD_SHA256,"target entry43 payload drift")
    source_payload=stage160._payload(source_g1t,sp,ENTRY43);target_payload=stage160._payload(target_g1t,tp,ENTRY43)
    cand_payload,mips=stage160.inject_scaled_bc3_alpha(source_payload,int(sr["width"]),int(sr["height"]),int(sr["mipmaps"]),target_payload,int(tr["width"]),int(tr["height"]),int(tr["mipmaps"]))
    require(sha256_bytes(cand_payload)==EXPECTED_ENTRY43_CANDIDATE_PAYLOAD_SHA256,"candidate entry43 payload drift")
    target_raw=stage160._raw_entry(target_g1t,tp,ENTRY43);po=int(tr["payload_offset_in_entry"]);cand_raw=target_raw[:po]+cand_payload
    require(len(cand_raw)==len(target_raw) and cand_raw[:po]==target_raw[:po],"entry43 target header/size drift")
    return cand_raw,{"source_width":sr["width"],"target_width":tr["width"],"mip_levels":sr["mipmaps"],"block_scale":mips[0]["block_scale"],"candidate_payload_sha256":sha256_bytes(cand_payload)}

def build_profile_from_inputs(project_root:Path,*,baseline_archive:Path,stage157_profile_archive:Path,source_g1t:bytes,gust_pak:Path,workspace_root:Path,manifest_root:Path,timeout_seconds:int=7200):
    s157=load_module(SCRIPT_DIR/"157_prepare_hinako_wet_school_entry23_fast_test_profile.py","stage161_s157");s155=load_module(SCRIPT_DIR/"155_collect_hinako_wet_texture_entry_differential_evidence.py","stage161_s155");s156=load_module(SCRIPT_DIR/"156_collect_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.py","stage161_s156");s160=load_module(SCRIPT_DIR/"160_collect_hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence.py","stage161_s160");br=load_module(project_root/"Blue_Reflection_Text_Tool/br_restoration_tool.py","stage161_br")
    baseline_sha=sha256_file(baseline_archive);require(baseline_sha==EXPECTED_BASELINE_SHA256,"PACK10_02 baseline hash drift");require(sha256_file(stage157_profile_archive)==EXPECTED_STAGE157_PROFILE_SHA256,"stage157 profile hash drift")
    workspace_root.mkdir(parents=True,exist_ok=True)
    free=shutil.disk_usage(workspace_root).free;need=baseline_archive.stat().st_size*2+2*1024**3;require(free>=need,f"insufficient free space: {free} < {need}")
    root=workspace_root/WORKSPACE_SUBDIR/PROFILE_ID
    if root.exists(): shutil.rmtree(root)
    base_dir=root/"baseline";work_dir=root/"work";verify_dir=root/"verify";out_dir=root/"output/Data";out_dir.mkdir(parents=True)
    saved_baseline_g1t=root/"baseline_pc00_scl_w.g1t"
    try:
        progress("extracting exact baseline PACK10_02")
        bmp,bm=br._extract_pak_for_repack_test(archive=baseline_archive,destination=base_dir,gust_pak=gust_pak,timeout_seconds=timeout_seconds,log_name="baseline.log");bmembers=br._manifest_member_hashes(base_dir,bm);bsig=br._gust_manifest_semantic_signature(bm)
        pkey,prow=find_member(bmembers,TARGET_PARENT_SUFFIX,"parent");gkey,grow=find_member(bmembers,TARGET_G1T_SUFFIX,"g1t");shutil.copy2(base_dir/Path(str(grow["name"])),saved_baseline_g1t);shutil.rmtree(base_dir)
        progress("extracting runtime-supported stage157 profile")
        wmp,wm=br._extract_pak_for_repack_test(archive=stage157_profile_archive,destination=work_dir,gust_pak=gust_pak,timeout_seconds=timeout_seconds,log_name="stage157.log");wmembers=br._manifest_member_hashes(work_dir,wm);wsig=br._gust_manifest_semantic_signature(wm);require(set(wmembers)==set(bmembers),"stage157 member set drift");require(wsig==bsig,"stage157 manifest semantics drift")
        changed=[k for k in bmembers if bmembers[k].get("sha256")!=wmembers[k].get("sha256")];require(set(changed)=={pkey,gkey},f"stage157 changed unexpected PACK members: {changed}")
        target_g1t_path=work_dir/Path(str(wmembers[gkey]["name"]));stage157_g1t=target_g1t_path.read_bytes();p157=s155.parse_g1t(stage157_g1t,"stage161-stage157-g1t");require(sha256_bytes(s156.raw_entry(stage157_g1t,p157,ENTRY23))==EXPECTED_ENTRY23_PROFILE_RAW_SHA256,"stage157 entry23 drift")
        cand43,meta43=make_entry43_candidate(s155,s156,s160,source_g1t,stage157_g1t);candidate_g1t=s156.rebuild_one_entry(stage157_g1t,s155,ENTRY43,cand43);baseline_g1t=saved_baseline_g1t.read_bytes();rows=g1t_change_rows(s155,s156,baseline_g1t,candidate_g1t);target_g1t_path.write_bytes(candidate_g1t)
        gust_g1t=project_root/".local/vendor/gust_tools/gust_g1t";gs,gc=s156.gust_list(gust_g1t,target_g1t_path,timeout=timeout_seconds);require(gs=="ok" and gc==p157["texture_count"],f"gust_g1t validation failed {gs}/{gc}")
        stage_manifest=br._load_gust_pak_manifest(wmp);output_name=str(stage_manifest["safe_output_name"]);progress("repacking no-install PACK10_02 profile")
        br._run_gust_pak(gust_pak=gust_pak,argument_name=wmp.name,cwd=work_dir,log_path=root/"repack.log",timeout_seconds=timeout_seconds);generated=work_dir/output_name;require(generated.is_file(),"gust_pak output missing");final=out_dir/"PACK10_02.PAK";os.replace(generated,final);profile_sha=sha256_file(final);profile_size=final.stat().st_size;shutil.rmtree(work_dir)
        progress("full re-extract verification")
        _vmp,vm=br._extract_pak_for_repack_test(archive=final,destination=verify_dir,gust_pak=gust_pak,timeout_seconds=timeout_seconds,log_name="verify.log");vmembers=br._manifest_member_hashes(verify_dir,vm);vsig=br._gust_manifest_semantic_signature(vm);require(set(vmembers)==set(bmembers) and vsig==bsig,"final PACK manifest drift")
        final_changed=[k for k in bmembers if bmembers[k].get("sha256")!=vmembers[k].get("sha256")];require(set(final_changed)=={pkey,gkey},f"final changed unexpected PACK members: {final_changed}")
        # Parent must remain exactly the runtime-supported stage157 parent.
        require(vmembers[pkey].get("sha256")==wmembers[pkey].get("sha256"),"School_Wet parent changed after stage157")
        vg=(verify_dir/Path(str(vmembers[gkey]["name"]))).read_bytes();vrows=g1t_change_rows(s155,s156,baseline_g1t,vg);require(all(r["verified"] for r in vrows),"final G1T verification failed")
        require(sha256_file(baseline_archive)==baseline_sha,"installed PACK10_02 changed during no-install build")
        manifest_root.mkdir(parents=True,exist_ok=True);manifest_path=manifest_root/f"{PROFILE_ID}.json";profile={"schema_version":1,"profile_id":PROFILE_ID,"target_relative_path":TARGET_RELATIVE_PATH,"baseline_sha256":baseline_sha,"baseline_size":baseline_archive.stat().st_size,"profile_sha256":profile_sha,"profile_size":profile_size,"local_profile_path":final.relative_to(project_root).as_posix(),"changed_member_count":2,"changed_members":[str(prow["name"]).replace("\\","/"),str(grow["name"]).replace("\\","/")],"retained_runtime_supported_entry23":True,"target_native_alpha_entry43":True,"runtime_validated":False,"production_eligible":False,"fast_test_only":True};atomic_json(manifest_path,profile)
        pak_rows=[{"member_key":k,"member_name":bmembers[k].get("name",""),"baseline_sha256":bmembers[k].get("sha256",""),"profile_sha256":vmembers[k].get("sha256",""),"changed":k in final_changed,"verified": (k in final_changed)==(bmembers[k].get("sha256")!=vmembers[k].get("sha256"))} for k in sorted(bmembers,key=str.casefold)]
        validations={"pack_changed_exactly_parent_and_g1t":set(final_changed)=={pkey,gkey},"g1t_changed_exactly_entries_23_43":[r["texture_index"] for r in vrows if r["changed"]]==[23,43],"stage157_parent_preserved":vmembers[pkey].get("sha256")==wmembers[pkey].get("sha256"),"gust_g1t_texture_count_preserved":gs=="ok" and gc==p157["texture_count"],"installed_baseline_unchanged":sha256_file(baseline_archive)==baseline_sha,"runtime_unvalidated":profile["runtime_validated"] is False,"nonproduction":profile["production_eligible"] is False};require(all(validations.values()),"stage161 validation failed")
        return profile,rows,pak_rows,[{"check_name":k,"passed":v} for k,v in validations.items()],meta43
    finally:
        for d in (base_dir,work_dir,verify_dir): shutil.rmtree(d,ignore_errors=True)

def resolve_source_g1t(project_root:Path,original_root:Path,quartet_root:Path,gust_pak:Path,workspace_root:Path,timeout:int)->bytes:
    s125=load_module(SCRIPT_DIR/"125_collect_character_state_exact_rehydration_evidence.py","stage161_s125");br=load_module(project_root/"Blue_Reflection_Text_Tool/br_restoration_tool.py","stage161_br_source");inv=s125.load_asset_inventories(project_root);s125.ensure_extraction_cache(project_root=project_root,workspace_root=workspace_root,inventories=inv,required_paths=[SOURCE_G1T_PATH],original_root=original_root,quartet_root=quartet_root,gust_pak_path=gust_pak,br=br,timeout_seconds=timeout);pair,row=inv[("source",SOURCE_G1T_PATH.casefold())];p=br.inventory_workspace_file(workspace_root,"source",pair,str(row["archive"]),str(row["path"]));require(p.is_file(),f"source G1T missing: {p}");return p.read_bytes()

def build_report(project_root:Path,*,quartet_root:Path,original_root:Path,gust_pak:Path,report_root:Path|None=None,output_report_root:Path|None=None,workspace_root:Path|None=None,extraction_workspace_root:Path|None=None,manifest_root:Path|None=None,timeout_seconds:int=7200,create_archive:bool=True):
    project_root=project_root.resolve();version=(project_root/"workstreams/quartet_restoration/VERSION").read_text().strip();require(tuple(map(int,version.split(".")))>=tuple(map(int,TOOL_VERSION.split("."))),f"expected {TOOL_VERSION} or newer, found {version}")
    report_root=(report_root or project_root/".local/reports/quartet_restoration").resolve();output_report_root=(output_report_root or report_root).resolve();workspace_root=(workspace_root or project_root/".local/build/quartet_restoration").resolve();extraction_workspace_root=(extraction_workspace_root or project_root/".local/workspaces/quartet_restoration/hinako_wet_texture_entry_differential").resolve();manifest_root=(manifest_root or workspace_root/MANIFEST_SUBDIR).resolve();out=output_report_root/REPORT_DIR;arc=output_report_root/REPORT_NAME
    if out.exists():shutil.rmtree(out)
    out.mkdir(parents=True)
    s157=verify_report(report_root,STAGE157_REPORT,STAGE157_SHA256,"br_quartet_restoration_hinako_wet_school_entry23_fast_test_profile_evidence_summary");require(s157.get("profile_sha256")==EXPECTED_STAGE157_PROFILE_SHA256,"stage157 profile provenance drift")
    s160=verify_report(report_root,STAGE160_REPORT,STAGE160_SHA256,"br_quartet_restoration_hinako_wet_school_bc3_target_native_alpha_injection_feasibility_evidence_summary");require(s160.get("candidate_entry43_payload_sha256")==EXPECTED_ENTRY43_CANDIDATE_PAYLOAD_SHA256 and s160.get("validation_failures")==0,"stage160 candidate drift")
    # Canonical runtime registry must retain the partial-positive entry23 result.
    reg=json.loads((project_root/"workstreams/quartet_restoration/RUNTIME_VALIDATION_REGISTRY.json").read_text(encoding="utf-8"));hits=[v for v in (reg.get("fast_test_results") or {}).values() if isinstance(v,dict) and v.get("profile_sha256")==EXPECTED_STAGE157_PROFILE_SHA256];require(len(hits)==1,"missing canonical stage158 runtime observation");obs=hits[0];require(obs.get("runtime_stable") is True and obs.get("runtime_validated") is False and (obs.get("entry23_interpretation") or {}).get("runtime_supported_as_wet_surface_or_droplet_component") is True,"stage158 runtime observation drift")
    stage157_path=project_root/STAGE157_PROFILE_RELATIVE
    if not stage157_path.is_file():
        # Recover it using the frozen stage157 builder rather than embedding payloads.
        progress("stage157 local profile missing; rebuilding it from canonical local inputs")
        mod=load_module(SCRIPT_DIR/"157_prepare_hinako_wet_school_entry23_fast_test_profile.py","stage161_rebuild157");mod.build_report(project_root,quartet_root=quartet_root,original_root=original_root,gust_pak=gust_pak,timeout_seconds=timeout_seconds)
        stage157_path=project_root/STAGE157_PROFILE_RELATIVE
    require(stage157_path.is_file(),f"stage157 profile missing after recovery: {stage157_path}")
    source_g1t=resolve_source_g1t(project_root,original_root,quartet_root,gust_pak,extraction_workspace_root,timeout_seconds);baseline=quartet_root/TARGET_RELATIVE_PATH
    profile,grows,prows,vrows,meta43=build_profile_from_inputs(project_root,baseline_archive=baseline,stage157_profile_archive=stage157_path,source_g1t=source_g1t,gust_pak=gust_pak,workspace_root=workspace_root,manifest_root=manifest_root,timeout_seconds=timeout_seconds)
    write_tsv(out/"G1T_ENTRY_VERIFICATION.tsv",list(grows[0]),grows);write_tsv(out/"PACK10_02_MEMBER_VERIFICATION.tsv",list(prows[0]),prows);write_tsv(out/"VALIDATIONS.tsv",["check_name","passed"],vrows);write_tsv(out/"ENTRY43_ALPHA_CANDIDATE.tsv",list(meta43),[meta43]);write_tsv(out/"PROFILE.tsv",list(profile),[profile])
    summary={"type":"br_quartet_restoration_hinako_wet_school_entry23_entry43_alpha_fast_test_profile_evidence_summary","format_version":1,"tool_version":TOOL_VERSION,"status":"no_install_profile_built_runtime_supported_entry23_plus_target_native_alpha43","stage157_evidence_sha256":STAGE157_SHA256,"stage158_activation_evidence_sha256":STAGE158_ACTIVATION_SHA256,"stage158_rollback_evidence_sha256":STAGE158_ROLLBACK_SHA256,"stage160_evidence_sha256":STAGE160_SHA256,"profile_id":PROFILE_ID,"baseline_sha256":profile["baseline_sha256"],"profile_sha256":profile["profile_sha256"],"profile_size":profile["profile_size"],"pak_changed_member_rows":sum(bool(r["changed"]) for r in prows),"g1t_changed_texture_entry_indices":[r["texture_index"] for r in grows if r["changed"]],"g1t_changed_texture_entry_rows":sum(bool(r["changed"]) for r in grows),"entry23_runtime_supported_wet_surface_or_droplet_component":True,"entry23_transparency_negative":True,"entry43_target_native_alpha_candidate":True,"entry43_transparency_semantics_confirmed":False,"runtime_validated":False,"production_eligible":False,"fast_test_only":True,"validation_failures":sum(not bool(r["passed"]) for r in vrows),"policy":{"whole_g1t_transplant":False,"whole_g1mm_or_g1mg_transplant":False,"stage157_runtime_supported_parent_and_entry23_retained":True,"only_additional_g1t_entry43_changed":True,"target_entry43_rgb_preserved":True,"installed_game_modified":False,"runtime_activation_performed":False,"core_modified":False,"translation_modified":False,"legacy_dlc_modified":False,"git_modified":False,"proprietary_payloads_in_evidence":False},"next_action":"Upload this metadata-only profile evidence. If it confirms exactly two changed PACK10_02 members and exactly G1T entries 23 and 43, prepare a separately authorized isolated runtime activation with exact PACK10_02 rollback. Evaluate model integrity, collar geometry, droplets and wet-shirt transparency independently."};atomic_json(out/"SUMMARY.json",summary);require(not [p for p in out.rglob("*") if p.is_file() and p.name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS)],"payload in evidence")
    if create_archive:make_archive(out,arc);return arc,summary
    return None,summary

def parse_args(argv:Sequence[str]|None=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--project-root",type=Path,default=PROJECT_ROOT_DEFAULT);p.add_argument("--quartet-root",type=Path,default=Path(os.environ["BR1_QUARTET_ROOT"]) if os.environ.get("BR1_QUARTET_ROOT") else None);p.add_argument("--original-root",type=Path,default=Path(os.environ["BR1_ORIGINAL_ROOT"]) if os.environ.get("BR1_ORIGINAL_ROOT") else None);p.add_argument("--gust-pak",type=Path);p.add_argument("--timeout-seconds",type=int,default=7200);return p.parse_args(argv)
def main(argv:Sequence[str]|None=None)->int:
    a=parse_args(argv);pr=a.project_root.expanduser().resolve();require(a.quartet_root is not None,"Quartet root required");require(a.original_root is not None,"Original root required");gust=(a.gust_pak or pr/".local/vendor/gust_tools/gust_pak").resolve();arc,s=build_report(pr,quartet_root=a.quartet_root.resolve(),original_root=a.original_root.resolve(),gust_pak=gust,timeout_seconds=a.timeout_seconds);print(json.dumps(s,indent=2,sort_keys=True));print(f"[stage161] report archive: {arc}");return 0
if __name__=="__main__":
    try:raise SystemExit(main())
    except Stage161Error as e:print(f"ERROR: {e}",file=sys.stderr);raise SystemExit(2)
