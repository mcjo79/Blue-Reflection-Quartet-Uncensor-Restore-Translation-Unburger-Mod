#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile

EXPECTED_MEMBERS=[f"costume_pc{i:02d}_bkn" for i in range(8)]
EXPECTED_TARGETS=["Data/PACK10_02.PAK","Data/PACK12.PAK"]
EXPECTED_CANDIDATES={
 "Data/PACK10_02.PAK":("a5b48d585673f4cdfb64baff4a3b1b9ce48319fa0bdb7865199a025223942f0a",11537018569),
 "Data/PACK12.PAK":("5e215fed1e0c56843d2e49831142e6a996bb2158f0683aafc40420d204e49616",26126129),
}
EXPECTED_BASELINES={
 "Data/PACK10_02.PAK":("e798f39c3bcdbb11381197bddf9bd3ad8de6ccf5d7c0c78b22613046d47f5302",11402829898),
 "Data/PACK12.PAK":("a108a22dd59116e79cf0fabcffd5d0427f72e13de267318869431d28717404f4",26124649),
}
RESULTS={"pass","not-visible","broken","crash","attach-failed"}
class E(RuntimeError): pass

def now(): return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
def load(p):
 with open(p,'r',encoding='utf-8') as f:return json.load(f)
def save(p,o):
 p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def digest(p):
 h=hashlib.sha256();
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def root_from_script():return pathlib.Path(__file__).resolve().parents[2]
def ws(project):return project/'workstreams/quartet_legacy_dlc'
def sessions(project):return project/'.local/reports/quartet_legacy_dlc/runtime_tests/generation10'
def marker(project):return sessions(project)/'ACTIVE_SESSION.json'
def rf(p,label):
 p=pathlib.Path(p).resolve()
 if not p.is_file() or p.is_symlink():raise E(f'{label} missing or unsafe: {p}')
 return p
def rd(p,label):
 p=pathlib.Path(p).resolve()
 if not p.is_dir() or p.is_symlink():raise E(f'{label} missing or unsafe: {p}')
 return p
def run(cmd,*,cwd=None,env=None,visible=False,check=True):
 cp=subprocess.run(cmd,cwd=cwd,env=env) if visible else subprocess.run(cmd,cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if check and cp.returncode: raise E(f'command failed ({cp.returncode}): {cmd}')
 return cp

def validate_active(project,session):
 p=rf(project/'.local/reports/quartet_legacy_dlc/validated_payloads/ACTIVE.json','Generation 9 ACTIVE.json');d=load(p)
 if d.get('type')!='validated_quartet_legacy_dlc_payload' or d.get('family_id')!='bkn_dry' or d.get('generation')!=9:raise E('ACTIVE.json is not BKN dry Generation 9')
 if d.get('members')!=EXPECTED_MEMBERS:raise E('Generation 9 member set mismatch')
 arts={a.get('target_path'):a for a in d.get('artifacts',[])}
 if sorted(arts)!=sorted(EXPECTED_TARGETS):raise E('Generation 9 must have exactly two target PAKs')
 for target in EXPECTED_TARGETS:
  a=arts[target]; ch,cs=EXPECTED_CANDIDATES[target]; bh,bs=EXPECTED_BASELINES[target]
  if a.get('operation')!='replace' or a.get('candidate_sha256')!=ch or int(a.get('candidate_size',-1))!=cs:raise E(f'{target}: candidate contract mismatch')
  if a.get('baseline_sha256')!=bh or int(a.get('baseline_size',-1))!=bs:raise E(f'{target}: baseline contract mismatch')
  cp=rf(project/a['candidate_relative_path'],f'{target} candidate')
  if cp.stat().st_size!=cs:raise E(f'{target}: candidate file size mismatch')
 shutil.copy2(p,session/'ACTIVE_GENERATION9.json')
 return d

def validate_baseline_sizes(game,session):
 rows={}
 for target,(h,s) in EXPECTED_BASELINES.items():
  p=rf(game/target,target); rows[target]={'size':p.stat().st_size,'expected_size':s,'size_match':p.stat().st_size==s,'expected_sha256':h}
  if p.stat().st_size!=s:raise E(f'{target}: installed file is not controlled-test baseline size')
 save(session/'BASELINE_FAST_GATE.json',rows)

def exe_candidates(game):
 rows=[]
 for p in game.rglob('*.exe'):
  try:
   if p.is_symlink() or p.stat().st_size>512*1024*1024:continue
   data=p.read_bytes()
  except OSError:continue
  if b'b1.dll' in data.lower():rows.append({'name':p.name,'relative_path':p.relative_to(game).as_posix(),'size':len(data)})
 seen=set();out=[]
 for r in rows:
  k=r['name'].lower()
  if k not in seen:seen.add(k);out.append(r)
 return out

def proc_hits(names):
 names=[x.lower() for x in names];out=[];proc=pathlib.Path('/proc')
 if not proc.is_dir():return out
 for d in proc.iterdir():
  if not d.name.isdigit():continue
  try:cmd=(d/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace');comm=(d/'comm').read_text(errors='replace').strip()
  except OSError:continue
  low=(cmd+' '+comm).lower()
  if any(n in low for n in names):out.append({'pid':int(d.name),'comm':comm,'cmdline':cmd[:1000]})
 return out

def require_game_closed(cands,session,phase):
 names=[r['name'] if isinstance(r,dict) else r for r in cands];hits=proc_hits(names);save(session/f'PROCESS_SCAN_{phase}.json',{'candidate_names':names,'hits':hits,'status':'clear' if not hits else 'running'})
 if hits:raise E(f'game appears to be running; close it before {phase}')

def build_patcher(project,session):
 go=shutil.which('go');src=project/'Blue_Reflection_Patcher'
 if not go or not src.is_dir():raise E('go or Blue_Reflection_Patcher source missing')
 out=project/'.local/build/quartet_legacy_dlc/generation10_runtime_test/blue-reflection-patcher-linux-x86_64';out.parent.mkdir(parents=True,exist_ok=True)
 cp=run([go,'build','-trimpath','-o',str(out),'./cmd/brpatcher'],cwd=src)
 save(session/'PATCHER_BUILD.json',{'sha256':digest(out),'size':out.stat().st_size,'stdout':cp.stdout,'stderr':cp.stderr})
 hp=run([str(out),'--help'],check=False);txt=hp.stdout+'\n'+hp.stderr
 for x in ('transaction-prepare','transaction-commit','transaction-rollback','installation-status'):
  if x not in txt:raise E(f'current patcher lacks {x}')
 return out

def installation_status(patcher,game,path):
 cp=run([str(patcher),'installation-status','--game-dir',str(game),'--json',str(path)],check=False);(path.parent/(path.stem+'.stdout.txt')).write_text(cp.stdout);(path.parent/(path.stem+'.stderr.txt')).write_text(cp.stderr)
 if cp.returncode:raise E('installation-status failed')
 return load(path)

def session_load(project):
 m=rf(marker(project),'active Generation 10 runtime-test session');st=load(m);sd=rd(st['session_dir'],'runtime-test session');return st,sd

def setup(ns):
 project=rd(ns.project_root or root_from_script(),'project root');game=rd(ns.game_dir,'Quartet game directory');prefix=rd(ns.wine_prefix,'Wine prefix');out=pathlib.Path(ns.output_dir).expanduser().resolve();out.mkdir(parents=True,exist_ok=True)
 sessions(project).mkdir(parents=True,exist_ok=True)
 if marker(project).exists():raise E(f'active Generation 10 session already exists: {marker(project)}')
 sd=(sessions(project)/f'g10-{now()}-{os.getpid():x}').resolve();sd.mkdir();save(sd/'INPUTS.json',{'project_root':str(project),'game_dir':str(game),'wine_prefix':str(prefix),'output_dir':str(out)})
 validate_active(project,sd);validate_baseline_sizes(game,sd);cands=exe_candidates(game)
 if not cands:raise E('could not identify a game executable importing B1.dll')
 save(sd/'PROCESS_CANDIDATES.json',{'candidates':cands});require_game_closed(cands,sd,'BEFORE_SETUP')
 # exact Stage 104 plan again
 records=rf(ws(project)/'runtime_payloads/bkn_dry_generation10/wardrobe_records.json','Generation 10 records');pipe=rf(ws(project)/'br_dlc_wardrobe_runtime_pipeline.py','runtime pipeline')
 run([sys.executable,str(pipe),'plan','--project-root',str(project),'--game-dir',str(game),'--records',str(records),'--evidence-dir',str(sd/'RUNTIME_PREFLIGHT'),'--skip-windows-build'],visible=True)
 patcher=build_patcher(project,sd);inst=installation_status(patcher,game,sd/'INSTALLATION_STATUS_BEFORE.json')
 if 'active_changed_unclassified' in json.dumps(inst).lower():raise E('patcher state is active_changed_unclassified')
 prep=sd/'TRANSACTION_PREPARE.json';run([str(patcher),'transaction-prepare','--game-dir',str(game),'--modules','quartet_legacy_dlc','--no-prompt','--project-root',str(project),'--json',str(prep)],visible=True)
 pr=load(prep)
 if pr.get('status')!='prepared' or int(pr.get('prepared_change_count',-1))!=2:raise E('prepare did not stage exactly two changes')
 journal=rf(pr.get('journal_path'),'prepared journal');shutil.copy2(journal,sd/'JOURNAL_AFTER_PREPARE.json')
 st={'type':'br_quartet_dlc_generation10_runtime_test_session','format_version':1,'status':'prepared_waiting_for_commit','session_dir':str(sd),'game_dir':str(game),'wine_prefix':str(prefix),'output_dir':str(out),'journal_path':str(journal),'patcher_path':str(patcher),'records_path':str(records),'process_candidates':[r['name'] for r in cands],'runtime_attach_applied':False}
 save(marker(project),st);save(sd/'SESSION.json',st)
 commit=sd/'TRANSACTION_COMMIT.json';run([str(patcher),'transaction-commit','--journal',str(journal),'--yes','--json',str(commit)],visible=True)
 cr=load(commit);jr=load(journal)
 if cr.get('status') not in ('installed','committed','already_committed') or jr.get('status')!='committed':raise E('commit did not reach committed journal state')
 shutil.copy2(journal,sd/'JOURNAL_AFTER_COMMIT.json')
 st['status']='committed_waiting_for_game_attach';save(marker(project),st);save(sd/'SESSION.json',st)
 print('\nSETUP COMPLETE\nLaunch Quartet normally. Once BLUE REFLECTION is running at a safe menu, run phase: attach')

def attach(ns):
 project=rd(ns.project_root or root_from_script(),'project root');st,sd=session_load(project)
 if st.get('runtime_attach_applied'):print('Runtime attach already applied.');return
 game=rd(st['game_dir'],'game directory');prefix=rd(ns.wine_prefix or st['wine_prefix'],'Wine prefix');records=rf(st['records_path'],'records');pipe=rf(ws(project)/'br_dlc_wardrobe_runtime_pipeline.py','runtime pipeline')
 names=[ns.process_name] if ns.process_name else st.get('process_candidates',[])
 if not names:raise E('no process candidates')
 attempts=[];success=None
 for i,name in enumerate(names):
  report=sd/f'RUNTIME_ATTACH_{i:02d}.json';cp=run([sys.executable,str(pipe),'attach','--project-root',str(project),'--game-dir',str(game),'--records',str(records),'--wine-prefix',str(prefix),'--process-name',name,'--output-json',str(report)],check=False)
  (sd/f'RUNTIME_ATTACH_{i:02d}.stdout.txt').write_text(cp.stdout);(sd/f'RUNTIME_ATTACH_{i:02d}.stderr.txt').write_text(cp.stderr);attempts.append({'process_name':name,'exit_code':cp.returncode})
  if cp.returncode==0 and report.exists() and load(report).get('status')=='applied':success=(name,report,load(report));break
 save(sd/'RUNTIME_ATTACH_ATTEMPTS.json',{'attempts':attempts})
 if not success:raise E('attach failed for all discovered executable names; verify Wine prefix or pass --process-name')
 name,report,r=success
 if r.get('synthetic_visible_indices')!=list(range(56,64)) or r.get('existing_costume_flags_touched') is not False or r.get('save_mutation_performed') is not False or r.get('on_disk_module_modified') is not False:raise E('attach report violates bounded contract')
 st.update({'status':'runtime_attached_waiting_for_observation','runtime_attach_applied':True,'attached_process_name':name,'attach_report':str(report)});save(marker(project),st);save(sd/'SESSION.json',st)
 print('\nATTACH COMPLETE\nCheck Hinako Dressing Room: Bikini must be additional, old four entries must remain, and dry BKN must equip/render. Then EXIT THE GAME COMPLETELY and run finish.')

def bundle(sd,out):
 for p in sd.rglob('*'):
  if p.is_file() and p.suffix.lower() in ('.pak','.dll','.exe'):raise E(f'refusing binary payload in evidence: {p}')
 sums=[]
 for p in sorted(sd.rglob('*')):
  if p.is_file() and p.name!='SHA256SUMS':sums.append(f'{digest(p)}  {p.relative_to(sd).as_posix()}')
 (sd/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
 name='BR_QUARTET_DLC_GENERATION10_RUNTIME_TEST_'+now();tmp=pathlib.Path(tempfile.mkdtemp(prefix='g10ev_'))
 try:
  shutil.copytree(sd,tmp/name);archive=out/(name+'.tar.zst');subprocess.run(['tar','--zstd','-cf',str(archive),'-C',str(tmp),name],check=True);side=pathlib.Path(str(archive)+'.sha256');side.write_text(f'{digest(archive)}  {archive.name}\n');return archive,side
 finally:shutil.rmtree(tmp,ignore_errors=True)

def finish(ns):
 project=rd(ns.project_root or root_from_script(),'project root');st,sd=session_load(project);game=rd(st['game_dir'],'game directory');require_game_closed(st.get('process_candidates',[]),sd,'BEFORE_ROLLBACK')
 observation={'type':'br_quartet_dlc_generation10_runtime_observation','format_version':1,'result':ns.result,'note':ns.note or '','runtime_attach_applied':bool(st.get('runtime_attach_applied')),'attached_process_name':st.get('attached_process_name'),'observed_utc':dt.datetime.now(dt.timezone.utc).isoformat()};save(sd/'RUNTIME_OBSERVATION.json',observation)
 journal=rf(st['journal_path'],'journal');patcher=rf(st['patcher_path'],'patcher');jr_before=load(journal)
 cleanup_mode='rollback'
 if jr_before.get('status')=='prepared':
  cleanup_mode='discard';rb=sd/'TRANSACTION_DISCARD.json';run([str(patcher),'transaction-discard','--journal',str(journal),'--yes','--json',str(rb)],visible=True);jr=load(journal)
  if jr.get('status')!='discarded':raise E('prepared transaction discard did not reach discarded state')
  shutil.copy2(journal,sd/'JOURNAL_AFTER_DISCARD.json')
 else:
  rb=sd/'TRANSACTION_ROLLBACK.json';run([str(patcher),'transaction-rollback','--journal',str(journal),'--yes','--json',str(rb)],visible=True);rr=load(rb);jr=load(journal)
  if rr.get('status') not in ('rolled_back','already_rolled_back') or jr.get('status')!='rolled_back':raise E('rollback did not reach rolled_back state')
  shutil.copy2(journal,sd/'JOURNAL_AFTER_ROLLBACK.json')
 installation_status(patcher,game,sd/'INSTALLATION_STATUS_AFTER_ROLLBACK.json')
 active=(journal.parents[2]/'active_state.json').exists();classification={'pass':'generation10_bkn_dry_visibility_and_equip_pass','not-visible':'generation10_runtime_registry_attached_but_bkn_not_visible','broken':'generation10_bkn_visible_but_runtime_behavior_broken','crash':'generation10_runtime_test_crash','attach-failed':'generation10_runtime_attach_failed'}[ns.result]
 restored=(jr.get('status') in ('rolled_back','discarded'))
 result={'type':'br_quartet_dlc_generation10_runtime_test_result','format_version':1,'generation':10,'pak_payload_generation':9,'result':ns.result,'classification':classification,'runtime_validated':ns.result=='pass' and not active and cleanup_mode=='rollback','runtime_attach_applied':bool(st.get('runtime_attach_applied')),'logical_indices':list(range(56,64)),'existing_record_replacement':False,'global_show_all':False,'pc08_in_scope':False,'wet_bkn_in_scope':False,'save_modified_by_runtime_capability':False,'on_disk_b1_modified':False,'transaction_id':jr.get('transaction_id'),'transaction_status_after':jr.get('status'),'cleanup_mode':cleanup_mode,'pak_baseline_restored_by_core_cleanup':restored,'active_state_after_cleanup':active,'observation':observation};save(sd/'RESULT.json',result)
 out=pathlib.Path(ns.output_dir or st['output_dir']).expanduser().resolve();out.mkdir(parents=True,exist_ok=True);a,s=bundle(sd,out);marker(project).unlink(missing_ok=True);st['status']='finished_rolled_back';save(sd/'SESSION.json',st);print('\nROLLBACK COMPLETE\nEvidence:',a,'\nSidecar:',s)

def status(ns):
 project=rd(ns.project_root or root_from_script(),'project root');m=marker(project);print(json.dumps(load(m),indent=2) if m.exists() else json.dumps({'status':'no_active_generation10_runtime_test'},indent=2))
def selftest():
 assert EXPECTED_MEMBERS[0]=='costume_pc00_bkn' and EXPECTED_MEMBERS[-1]=='costume_pc07_bkn';assert set(EXPECTED_TARGETS)==set(EXPECTED_CANDIDATES)==set(EXPECTED_BASELINES);assert RESULTS=={'pass','not-visible','broken','crash','attach-failed'};print('self-test: OK')
def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='phase',required=True)
 s=sub.add_parser('setup');s.add_argument('--project-root');s.add_argument('--game-dir',required=True);s.add_argument('--wine-prefix',required=True);s.add_argument('--output-dir',required=True)
 a=sub.add_parser('attach');a.add_argument('--project-root');a.add_argument('--wine-prefix');a.add_argument('--process-name')
 f=sub.add_parser('finish');f.add_argument('--project-root');f.add_argument('--result',required=True,choices=sorted(RESULTS));f.add_argument('--note');f.add_argument('--output-dir')
 q=sub.add_parser('status');q.add_argument('--project-root');sub.add_parser('self-test')
 ns=ap.parse_args()
 try:
  {'setup':setup,'attach':attach,'finish':finish,'status':status,'self-test':lambda x:selftest()}[ns.phase](ns)
 except E as e:print('ERROR:',e,file=sys.stderr);return 2
 return 0
if __name__=='__main__':raise SystemExit(main())
