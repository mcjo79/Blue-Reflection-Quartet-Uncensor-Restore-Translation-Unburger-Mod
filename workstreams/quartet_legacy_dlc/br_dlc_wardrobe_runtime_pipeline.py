#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile, time

CAPABILITY = "wardrobe_registry_append_v1"
PROFILE_REL = pathlib.Path("workstreams/core/runtime_profiles/quartet_wardrobe_registry_v1.json")
PATCHER_REL = pathlib.Path("Blue_Reflection_Patcher")
BUILD_REL = pathlib.Path(".local/build/quartet_legacy_dlc/wardrobe_runtime")
DEFAULT_PROFILE_TARGET = "blue_reflection_quartet_wardrobe_registry_v1"

class PipelineError(RuntimeError):
    pass

def sha256_file(p: pathlib.Path) -> str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def regular(p: pathlib.Path, what: str) -> pathlib.Path:
    p=p.resolve()
    if not p.is_file() or p.is_symlink():
        raise PipelineError(f"{what} missing or unsafe: {p}")
    return p

def load_json(p: pathlib.Path):
    with p.open("r",encoding="utf-8") as f: return json.load(f)

def run_json(cmd, *, cwd=None, env=None, what="command"):
    cp=subprocess.run(cmd,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if cp.returncode != 0:
        raise PipelineError(f"{what} failed ({cp.returncode}): {cp.stderr.strip() or cp.stdout.strip()}")
    try: data=json.loads(cp.stdout)
    except Exception as e: raise PipelineError(f"{what} did not emit JSON: {e}") from e
    return data, cp

def project_root_from_script() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[2]

def resolve_inputs(project: pathlib.Path, game_dir: pathlib.Path, records: pathlib.Path):
    project=project.resolve(); game_dir=game_dir.resolve()
    profile=regular(project/PROFILE_REL, "core target profile")
    module=regular(game_dir/"B1.dll", "Quartet B1.dll")
    records=regular(records, "DLC wardrobe record set")
    return profile,module,records

def build_companion(project: pathlib.Path, windows: bool):
    go=shutil.which("go")
    if not go: raise PipelineError("go is required to build br_wardrobe_runtime")
    patcher=(project/PATCHER_REL).resolve()
    if not patcher.is_dir(): raise PipelineError(f"Blue_Reflection_Patcher source tree missing: {patcher}")
    outdir=(project/BUILD_REL).resolve(); outdir.mkdir(parents=True,exist_ok=True)
    out=outdir/("br_wardrobe_runtime.exe" if windows else "br_wardrobe_runtime")
    env=os.environ.copy()
    if windows:
        env.update({"GOOS":"windows","GOARCH":"amd64","CGO_ENABLED":"0"})
    cmd=[go,"build","-trimpath","-o",str(out),"./cmd/br_wardrobe_runtime"]
    cp=subprocess.run(cmd,cwd=patcher,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    report={"command":["go","build","-trimpath","-o",out.name,"./cmd/br_wardrobe_runtime"],
            "windows":windows,"exit_code":cp.returncode,"stdout":cp.stdout,"stderr":cp.stderr}
    if cp.returncode != 0: raise PipelineError("build br_wardrobe_runtime failed: "+cp.stderr.strip())
    regular(out, "built companion")
    report["output_sha256"]=sha256_file(out); report["output_size"]=out.stat().st_size
    return out,report

def validate_record_manifest(records_path: pathlib.Path):
    d=load_json(records_path)
    if d.get("type")!="br_runtime_wardrobe_records" or d.get("format_version")!=1 or d.get("capability")!=CAPABILITY:
        raise PipelineError("unsupported wardrobe record manifest")
    recs=d.get("records")
    if not isinstance(recs,list) or not 1 <= len(recs) <= 8:
        raise PipelineError("record count must be 1..8")
    required={"label_id","character","field08","field0c","field10","field14","field18","field1c","field20","field24","field28","field2c","visible"}
    for i,r in enumerate(recs):
        if set(r)!=required: raise PipelineError(f"record {i} field set mismatch")
        if r["visible"] and r["field18"] != 0:
            raise PipelineError(f"record {i}: visible=true requires field18=0")
        for k in required-{"visible"}:
            v=r[k]
            if not isinstance(v,int) or isinstance(v,bool) or not 0 <= v <= 0xffffffff:
                raise PipelineError(f"record {i}: invalid {k}")
        if not isinstance(r["visible"],bool): raise PipelineError(f"record {i}: visible is not boolean")
    return d

def preflight_plan(project, game_dir, records_path, evidence_dir, native_companion=None, build_windows=True):
    project=pathlib.Path(project).resolve(); game_dir=pathlib.Path(game_dir).resolve()
    evidence=pathlib.Path(evidence_dir).resolve(); evidence.mkdir(parents=True,exist_ok=True)
    profile,module,records=resolve_inputs(project,game_dir,pathlib.Path(records_path))
    recdoc=validate_record_manifest(records)
    if native_companion:
        native=regular(pathlib.Path(native_companion),"native br_wardrobe_runtime")
        build_native={"provided":True,"sha256":sha256_file(native),"size":native.stat().st_size}
    else:
        native,build_native=build_companion(project,False)
    (evidence/"BUILD_NATIVE.json").write_text(json.dumps(build_native,indent=2)+"\n")

    caps,_=run_json([str(native),"capabilities"],what="capability discovery")
    (evidence/"CAPABILITIES.json").write_text(json.dumps(caps,indent=2)+"\n")
    if CAPABILITY not in caps.get("capabilities",[]):
        raise PipelineError(f"core capability {CAPABILITY} missing")
    cap=caps.get(CAPABILITY,{})
    required={"memory_only":True,"global_show_all":False,"on_disk_game_binary_patch":False,"save_mutation":False}
    for k,v in required.items():
        if cap.get(k) is not v: raise PipelineError(f"capability semantic mismatch: {k}")
    if int(cap.get("max_append_records",0)) < len(recdoc["records"]):
        raise PipelineError("core max_append_records is too small")

    validation,_=run_json([str(native),"validate-module","--module",str(module),"--profile",str(profile)],what="B1 module validation")
    (evidence/"MODULE_VALIDATION.json").write_text(json.dumps(validation,indent=2)+"\n")
    if validation.get("status")!="pass" or validation.get("read_only") is not True:
        raise PipelineError("B1 module validation did not pass")

    plan,_=run_json([str(native),"plan","--module",str(module),"--profile",str(profile),"--records",str(records)],what="runtime plan")
    (evidence/"RUNTIME_PLAN.json").write_text(json.dumps(plan,indent=2)+"\n")
    p=plan.get("plan",{})
    baseline=int(p.get("baseline_record_count",-1)); count=len(recdoc["records"])
    expected=list(range(baseline,baseline+count))
    if plan.get("status")!="pass" or p.get("status")!="pass":
        raise PipelineError("runtime plan did not pass")
    if p.get("logical_indices")!=expected:
        raise PipelineError("runtime plan logical indices mismatch")
    if p.get("existing_records_preserved") is not True or p.get("global_show_all") is not False or p.get("save_mutation_required") is not False:
        raise PipelineError("runtime plan violates bounded semantics")

    build_win=None
    if build_windows:
        _,build_win=build_companion(project,True)
        (evidence/"BUILD_WINDOWS.json").write_text(json.dumps(build_win,indent=2)+"\n")

    summary={
      "type":"br_quartet_legacy_dlc_wardrobe_runtime_plan",
      "format_version":1,"status":"pass","capability":CAPABILITY,
      "profile_target_id":validation.get("profile_target_id"),
      "module_sha256":sha256_file(module),"module_size":module.stat().st_size,
      "record_count":count,"logical_indices":expected,
      "final_record_count":p.get("final_record_count"),
      "patch_count":len(p.get("patches",[])),
      "existing_records_preserved":True,"global_show_all":False,
      "save_mutation_required":False,"runtime_attach_called":False,
      "game_modified":False,"on_disk_b1_modified":False,
      "windows_companion_built":bool(build_win)
    }
    (evidence/"SUMMARY.json").write_text(json.dumps(summary,indent=2)+"\n")
    shutil.copy2(records,evidence/"RECORDS.json")
    shutil.copy2(profile,evidence/"TARGET_PROFILE.json")
    return summary

def winepath(winepath_bin, wineprefix, p):
    env=os.environ.copy(); env["WINEPREFIX"]=str(pathlib.Path(wineprefix).resolve())
    cp=subprocess.run([winepath_bin,"-w",str(pathlib.Path(p).resolve())],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if cp.returncode!=0 or not cp.stdout.strip(): raise PipelineError("winepath failed: "+cp.stderr.strip())
    return cp.stdout.strip()

def attach(project, game_dir, records_path, wineprefix, process_name, output_json, wine_bin="wine", winepath_bin="winepath"):
    project=pathlib.Path(project).resolve(); game_dir=pathlib.Path(game_dir).resolve()
    profile,module,records=resolve_inputs(project,game_dir,pathlib.Path(records_path))
    validate_record_manifest(records)

    # Always run host-side signature/plan preflight immediately before live attach.
    tmp=pathlib.Path(tempfile.mkdtemp(prefix="br_wardrobe_attach_preflight_"))
    try:
        preflight_plan(project,game_dir,records,tmp,build_windows=False)
    finally:
        shutil.rmtree(tmp,ignore_errors=True)

    exe,_=build_companion(project,True)
    wine=shutil.which(wine_bin) if os.sep not in wine_bin else wine_bin
    wp=shutil.which(winepath_bin) if os.sep not in winepath_bin else winepath_bin
    if not wine or not wp: raise PipelineError("wine and winepath are required for live attach")
    env=os.environ.copy(); env["WINEPREFIX"]=str(pathlib.Path(wineprefix).resolve())
    wexe=winepath(wp,wineprefix,exe); wprof=winepath(wp,wineprefix,profile); wrec=winepath(wp,wineprefix,records)
    cmd=[wine,wexe,"attach","--process-name",process_name,"--profile",wprof,"--records",wrec]
    report,cp=run_json(cmd,env=env,what="live wardrobe attach")
    if report.get("status")!="applied": raise PipelineError("runtime attach status is not applied")
    count=len(load_json(records)["records"])
    expected=list(range(int(report.get("baseline_record_count",-1)),int(report.get("baseline_record_count",-1))+count))
    if report.get("synthetic_visible_indices")!=expected:
        raise PipelineError("runtime attach synthetic visibility set mismatch")
    if report.get("existing_costume_flags_touched") is not False or report.get("save_mutation_performed") is not False or report.get("on_disk_module_modified") is not False:
        raise PipelineError("runtime attach violated bounded semantics")
    pathlib.Path(output_json).write_text(json.dumps(report,indent=2)+"\n")
    return report

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("plan")
    p.add_argument("--project-root",default=str(project_root_from_script()))
    p.add_argument("--game-dir",required=True); p.add_argument("--records",required=True)
    p.add_argument("--evidence-dir",required=True); p.add_argument("--native-companion")
    p.add_argument("--skip-windows-build",action="store_true")
    a=sub.add_parser("attach")
    a.add_argument("--project-root",default=str(project_root_from_script()))
    a.add_argument("--game-dir",required=True); a.add_argument("--records",required=True)
    a.add_argument("--wine-prefix",required=True); a.add_argument("--process-name",required=True)
    a.add_argument("--output-json",required=True); a.add_argument("--wine-bin",default="wine"); a.add_argument("--winepath-bin",default="winepath")
    ns=ap.parse_args()
    try:
        if ns.cmd=="plan":
            s=preflight_plan(ns.project_root,ns.game_dir,ns.records,ns.evidence_dir,ns.native_companion,not ns.skip_windows_build)
            print(json.dumps(s,indent=2))
        else:
            r=attach(ns.project_root,ns.game_dir,ns.records,ns.wine_prefix,ns.process_name,ns.output_json,ns.wine_bin,ns.winepath_bin)
            print(json.dumps(r,indent=2))
    except PipelineError as e:
        print("ERROR: "+str(e),file=sys.stderr); return 2
    return 0

if __name__=="__main__":
    raise SystemExit(main())
