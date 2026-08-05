#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, shutil, tempfile, time
from pathlib import Path
from typing import Any

class TestInstallError(RuntimeError): pass
TARGET_ARCHIVES={
 'blue_reflection_original':{
  'required':('DATA/PACK01.PAK','DATA/PACK02_1.PAK'),
  'optional':('DATA/PACK02_3.PAK','DATA/PACK00_01.PAK','DATA/PACK00_04_1.PAK'),
 },
 'blue_reflection_quartet':{
  'required':('Data/PACK11.PAK','Data/PACK12.PAK'),
  'optional':(
   'Data/PACK10_01.PAK',
   'Data/PACK00_01.PAK',
   'Data/PACK00_04_01.PAK',
  ),
 },
 'second_light_original':{
  'required':('Data/PACK01.PAK','Data/PACK02.PAK'),
  'optional':('Data/PACK00_04_01.PAK',),
 },
}

def sha256_file(path:Path)->str:
 d=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''): d.update(chunk)
 return d.hexdigest()

def fsync_dir(path:Path)->None:
 flags=os.O_RDONLY|getattr(os,'O_DIRECTORY',0); fd=os.open(path,flags)
 try: os.fsync(fd)
 finally: os.close(fd)

def atomic_json(path:Path,data:dict[str,Any])->None:
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:
   f.write((json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()); f.flush(); os.fsync(f.fileno())
  os.replace(tmp,path); fsync_dir(path.parent)
 except Exception:
  try: os.unlink(tmp)
  except FileNotFoundError: pass
  raise

def atomic_copy(src:Path,dst:Path,expected:str)->None:
 dst.parent.mkdir(parents=True,exist_ok=True)
 tmp=dst.with_name(f'.{dst.name}.brtest.{os.getpid()}.tmp'); tmp.unlink(missing_ok=True)
 try:
  shutil.copy2(src,tmp)
  got=sha256_file(tmp)
  if got!=expected: raise TestInstallError(f'Temporary copy checksum mismatch: {dst}: {got} != {expected}')
  with tmp.open('rb') as f: os.fsync(f.fileno())
  os.replace(tmp,dst); fsync_dir(dst.parent)
 finally: tmp.unlink(missing_ok=True)

def load_json(path:Path,typ:str|None=None)->dict[str,Any]:
 try: data=json.loads(path.read_text(encoding='utf-8'))
 except FileNotFoundError as e: raise TestInstallError(f'Required file is missing: {path}') from e
 except json.JSONDecodeError as e: raise TestInstallError(f'Invalid JSON {path}: {e}') from e
 if not isinstance(data,dict) or (typ and data.get('type')!=typ): raise TestInstallError(f'Unexpected JSON structure: {path}')
 return data

def state_path(root:Path,target:str)->Path: return root/'.local/state/translation_game_test'/f'{target}.json'
def latest_report(root:Path)->Path: return root/'.local/reports/translation/BR_TRANSLATION_GAME_TEST_REPORT.json'
def transaction_id()->str: return time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())

def running_processes(game_root:Path)->list[str]:
 proc=Path('/proc')
 if not proc.is_dir(): return []
 ignored={os.getpid(),os.getppid()}; needle=str(game_root.resolve()).casefold(); out=[]
 for p in proc.iterdir():
  if not p.name.isdigit() or int(p.name) in ignored: continue
  try: cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace').strip()
  except OSError: continue
  if needle in cmd.casefold(): out.append(f'pid={p.name}: {cmd[:240]}')
 return out

def target_entries(root:Path,target:str)->list[dict[str,Any]]:
 report=load_json(root/'.local/reports/translation/BR_TRANSLATION_PAK_REPACK_REPORT.json','br_translation_pak_repack_report')
 if report.get('status')!='ok' or report.get('summary',{}).get('failures')!=0: raise TestInstallError('PAK repack report is not clean')
 found={e.get('archive_relative_path'):e for e in report.get('archives',[]) if isinstance(e,dict) and e.get('target_id')==target}
 rules=TARGET_ARCHIVES[target]; required=rules['required']; allowed=set(required)|set(rules['optional']); present=set(found)
 if not set(required).issubset(present) or not present.issubset(allowed): raise TestInstallError(f'Unexpected archives for {target}: {sorted(found)}')
 proof=report.get('title_marker_proof')
 if target=='second_light_original' and isinstance(proof,dict) and proof.get('status')=='ok' and 'Data/PACK00_04_01.PAK' not in present:
  raise TestInstallError('Synthetic title-marker report is active but PACK00_04_01.PAK is missing')
 expected=tuple(rel for rel in (*required,*rules['optional']) if rel in found)
 result=[]
 for rel in expected:
  e=found[rel]; src=root/str(e.get('output_path','')); h=e.get('output_sha256')
  if not src.is_file(): raise TestInstallError(f'Built PAK is missing: {src}')
  if not isinstance(h,str) or sha256_file(src)!=h: raise TestInstallError(f'Built PAK changed after validation: {src}')
  result.append({'relative_path':rel,'source':src,'installed_sha256':h,'installed_bytes':src.stat().st_size})
 return result


CORE_PROFILE_OPEN_STATUSES={"active","prepared","rolling_back","activation_uncertain","rollback_uncertain"}

def refuse_open_quartet_profiles(root:Path,target:str)->None:
 if target!="blue_reflection_quartet": return
 for name in ("quartet_event_profile.json","quartet_shader_profile.json"):
  path=root/".local/state/core_unified_patcher"/name
  if not path.is_file(): continue
  state=load_json(path)
  status=str(state.get("status", ""))
  if status in CORE_PROFILE_OPEN_STATUSES:
   raise TestInstallError(
    f"Refusing to combine the Quartet translation/title test with an open core restoration transaction: {path} (status={status}). Roll it back first."
   )

def write_report(root:Path,report:dict[str,Any])->None:
 hist=latest_report(root).parent/'game_test'/f"{report['transaction_id']}_{report['operation']}_{report['target']}.json"
 atomic_json(hist,report); atomic_json(latest_report(root),report)

def install(root:Path,target:str,game:Path)->int:
 refuse_open_quartet_profiles(root,target)
 active=running_processes(game)
 if active: raise TestInstallError('Game installation appears in use:\n  '+'\n  '.join(active))
 sp=state_path(root,target)
 if sp.is_file():
  s=load_json(sp,'br_translation_game_test_state')
  if s.get('status')=='installed': raise TestInstallError(f'Active test already exists: {sp}; restore it first')
 entries=target_entries(root,target); tid=transaction_id(); backup_root=root/'.local/backups/translation_game_test'/target/tid; backup_root.mkdir(parents=True)
 files=[]
 for e in entries:
  rel=e['relative_path']; dst=game/rel
  if not dst.is_file(): raise TestInstallError(f'Installed PAK is missing: {dst}')
  orig=sha256_file(dst); backup=backup_root/rel; backup.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(dst,backup)
  if sha256_file(backup)!=orig: raise TestInstallError(f'Backup checksum mismatch: {backup}')
  files.append({'relative_path':rel,'destination':str(dst),'backup_path':str(backup),'original_sha256':orig,'original_bytes':dst.stat().st_size,'installed_sha256':e['installed_sha256'],'installed_bytes':e['installed_bytes']})
 state={'type':'br_translation_game_test_state','format_version':1,'target':target,'game_root':str(game),'transaction_id':tid,'status':'installing','backup_root':str(backup_root),'files':files}; atomic_json(sp,state)
 source={e['relative_path']:e['source'] for e in entries}; replaced=[]
 try:
  for f in files:
   atomic_copy(source[f['relative_path']],Path(f['destination']),f['installed_sha256']); replaced.append(f)
  for f in files:
   if sha256_file(Path(f['destination']))!=f['installed_sha256']: raise TestInstallError(f'Post-install verification failed: {f["destination"]}')
 except Exception:
  errors=[]
  for f in reversed(replaced):
   try: atomic_copy(Path(f['backup_path']),Path(f['destination']),f['original_sha256'])
   except Exception as e: errors.append(f"{f['relative_path']}: {e}")
  state['status']='install_failed_rolled_back' if not errors else 'install_failed_rollback_incomplete'; state['rollback_errors']=errors; atomic_json(sp,state); raise
 state['status']='installed'; state['installed_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()); atomic_json(sp,state)
 report={'type':'br_translation_game_test_report','format_version':1,'status':'ok','operation':'install','target':target,'transaction_id':tid,'game_root':'<GAME_ROOT>','files':[{'relative_path':f['relative_path'],'original_sha256':f['original_sha256'],'installed_sha256':f['installed_sha256'],'original_bytes':f['original_bytes'],'installed_bytes':f['installed_bytes']} for f in files],'backup_root':str(backup_root.relative_to(root)),'next_action':'manual_smoke_test_then_restore'}; write_report(root,report)
 print(f'Installed translation test for {target}.'); print(f'Backup: {backup_root}'); return 0

def status(root:Path,target:str,game:Path)->int:
 sp=state_path(root,target)
 if not sp.is_file(): print(f'No test state for {target}.'); return 0
 s=load_json(sp,'br_translation_game_test_state'); print(f"Target: {target}\nState: {s.get('status')}\nTransaction: {s.get('transaction_id')}"); ok=True
 for f in s.get('files',[]):
  dst=game/f['relative_path']
  if not dst.is_file(): rel='missing'; ok=False
  else:
   h=sha256_file(dst)
   if h==f['installed_sha256']: rel='installed-test'
   elif h==f['original_sha256']: rel='original-backup-version'
   else: rel='other:'+h; ok=False
  print(f"  {f['relative_path']}: {rel}")
 return 0 if ok else 3

def restore(root:Path,target:str,game:Path)->int:
 active=running_processes(game)
 if active: raise TestInstallError('Game installation appears in use:\n  '+'\n  '.join(active))
 sp=state_path(root,target)
 if not sp.is_file(): raise TestInstallError(f'No test state: {sp}')
 s=load_json(sp,'br_translation_game_test_state')
 if s.get('status')=='restored': print(f'Already restored: {target}'); return 0
 if s.get('status')!='installed': raise TestInstallError(f"Cannot restore state {s.get('status')!r}")
 if Path(s.get('game_root','')).resolve()!=game.resolve(): raise TestInstallError('Configured game root differs from installation state')
 for f in s['files']:
  b=Path(f['backup_path']); d=game/f['relative_path']
  if not b.is_file() or sha256_file(b)!=f['original_sha256']: raise TestInstallError(f'Backup missing or changed: {b}')
  if not d.is_file(): raise TestInstallError(f'Installed PAK missing: {d}')
  h=sha256_file(d)
  if h not in {f['installed_sha256'],f['original_sha256']}: raise TestInstallError(f'Refusing to overwrite a PAK changed after test installation: {d}\nCurrent SHA-256: {h}')
 for f in s['files']: atomic_copy(Path(f['backup_path']),game/f['relative_path'],f['original_sha256'])
 for f in s['files']:
  if sha256_file(game/f['relative_path'])!=f['original_sha256']: raise TestInstallError(f'Restore verification failed: {game/f["relative_path"]}')
 s['status']='restored'; s['restored_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()); atomic_json(sp,s)
 report={'type':'br_translation_game_test_report','format_version':1,'status':'ok','operation':'restore','target':target,'transaction_id':s['transaction_id'],'game_root':'<GAME_ROOT>','files':[{'relative_path':f['relative_path'],'restored_sha256':f['original_sha256']} for f in s['files']],'backup_root':str(Path(s['backup_root']).relative_to(root)),'next_action':'upload_report_and_describe_manual_result'}; write_report(root,report); print(f'Restored original pre-test PAKs for {target}.'); return 0

def main()->int:
 p=argparse.ArgumentParser(); p.add_argument('operation',choices=('install','status','restore')); p.add_argument('--project-root',required=True); p.add_argument('--target',required=True,choices=sorted(TARGET_ARCHIVES)); p.add_argument('--game-root',required=True); a=p.parse_args(); root=Path(a.project_root).expanduser().resolve(); game=Path(a.game_root).expanduser().resolve()
 if not root.is_dir(): raise TestInstallError(f'Project root missing: {root}')
 if not game.is_dir(): raise TestInstallError(f'Game root missing: {game}')
 return {'install':install,'status':status,'restore':restore}[a.operation](root,a.target,game)

if __name__=='__main__':
 try: raise SystemExit(main())
 except TestInstallError as e: print(f'ERROR: {e}',file=os.sys.stderr); raise SystemExit(1)
