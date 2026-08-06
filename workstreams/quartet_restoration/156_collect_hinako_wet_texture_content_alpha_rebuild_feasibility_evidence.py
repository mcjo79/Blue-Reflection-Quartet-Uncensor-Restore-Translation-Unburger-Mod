#!/usr/bin/env python3
"""Stage 156: read-only wet-texture content/alpha and target-native G1T rebuild feasibility.

Consumes the verified stage-155 metadata report and rehydrates only the Hinako
G1T inputs required to inspect source wet-only texture families.  The primary
focus is the grounded school material slot-5 transition dry texture 26 -> wet
texture 23:

* Original dry 26 == Quartet dry 26 exactly;
* Original wet 23 is a distinct 1024x1024 BC1 entry;
* Quartet wet 23 is exactly the same 16x16 BC1 entry as the dry control;
* Original wet 23 is shared exactly across nkd_w, scl_w and swm_w.

The stage decodes BC1/BC3 base-mip statistics without exporting image payloads,
and simulates a target-native rebuild of Quartet scl_w.g1t with only texture
entry 23 replaced by the exact Original wet entry.  It updates G1T offsets and
total size in memory, reparses the result, verifies all other target entries are
unchanged, and optionally validates the temporary rebuilt G1T with gust_g1t -l.

No G1T/G1M/PAK is exported in evidence and no installed-game file is modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT_DEFAULT = SCRIPT_DIR.parent.parent
TOOL_VERSION = "0.1.75"
REPORT_DIR = "hinako_wet_texture_content_alpha_rebuild_feasibility_evidence"
REPORT_NAME = "BR_quartet_restoration_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence.tar.zst"
WORKSPACE_SUBDIR = Path("hinako_wet_texture_content_alpha_rebuild_feasibility")

STAGE155_REPORT = "BR_quartet_restoration_hinako_wet_texture_entry_differential_evidence.tar.zst"
STAGE155_SHA256 = "91944b1da27e935695cb8c8c6781b276995cf9798b60262e810bfe385573da0d"
STAGE155_ROOT = "hinako_wet_texture_entry_differential_evidence"
STAGE154_SHA256 = "caf47bbe9d7485f9545e089a01c6a159bdea9ce715dc6ec5720329c2c99a63c8"

PACKS = (
    ("nkd_w", "data/x64/character/pc00/pc00_nkd_w.g1t"),
    ("scl", "data/x64/character/pc00/pc00_scl.g1t"),
    ("scl_w", "data/x64/character/pc00/pc00_scl_w.g1t"),
    ("swm_w", "data/x64/character/pc00/pc00_swm_w.g1t"),
)
FOCUS_DRY_ID = 26
FOCUS_WET_ID = 23
FOCUS_SOURCE_WET_SHA = "3ac334051bbf5ee86947bdb2a6aecc15dbc0456ba9b41e232278143a9a7f6727"
FOCUS_DRY_SHA = "d7aea404adf36f9684696ac3ff6825481df126f04e639830254a09a3209cfc3a"
FORBIDDEN_REPORT_EXTENSIONS = (".pak", ".g1m", ".g1t", ".g1s", ".g1e", ".g1em", ".elixir", ".elixir.gz", ".ebd", ".ebm", ".kps", ".dds", ".png")

class Stage156Error(RuntimeError): pass

def require(c: bool, m: str) -> None:
    if not c: raise Stage156Error(m)

def progress(m: str) -> None: print(f"[stage156] {m}", flush=True)

def sha256_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024), b''): h.update(b)
    return h.hexdigest()

def safe_relative(v: str, label: str) -> str:
    p=PurePosixPath(str(v).replace('\\','/'))
    require(p.parts and not p.is_absolute() and '..' not in p.parts, f"unsafe {label}: {v}")
    return p.as_posix()

def load_module(path: Path, name: str) -> Any:
    require(path.is_file(), f"missing module: {path}")
    spec=importlib.util.spec_from_file_location(name,path); require(spec is not None and spec.loader is not None, f"cannot load {path}")
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod

def write_tsv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str,Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(fields),delimiter='\t',lineterminator='\n',extrasaction='ignore'); w.writeheader()
        for r in rows: w.writerow({k:r.get(k,'') for k in fields})

def make_archive(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True,exist_ok=True); tmp=output.with_name(output.name+'.tmp'); tmp.unlink(missing_ok=True)
    cp=subprocess.run(['tar','--zstd','-cf',str(tmp),'-C',str(source.parent),source.name],text=True,capture_output=True)
    require(cp.returncode==0, cp.stderr.strip() or 'archive creation failed'); os.replace(tmp,output)

def read_stage155(report_root: Path) -> tuple[dict[str,Any],list[dict[str,str]],list[dict[str,str]]]:
    arc=report_root/STAGE155_REPORT; require(arc.is_file(),f"missing stage-155 report: {arc}")
    actual=sha256_file(arc); require(actual==STAGE155_SHA256,f"stage-155 evidence SHA drift: {actual}")
    with tempfile.TemporaryDirectory(prefix='stage156-prereq-') as td:
        cp=subprocess.run(['tar','--zstd','-tf',str(arc)],text=True,capture_output=True); require(cp.returncode==0,cp.stderr.strip() or 'cannot list stage155')
        names=[safe_relative(x.strip(),'stage155 member') for x in cp.stdout.splitlines() if x.strip()]
        require(names and {PurePosixPath(x).parts[0] for x in names}=={STAGE155_ROOT},'unexpected stage155 root')
        require(not any(x.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS) for x in names),'payload in stage155 report')
        cp=subprocess.run(['tar','--zstd','-xf',str(arc),'-C',td],text=True,capture_output=True); require(cp.returncode==0,cp.stderr.strip() or 'cannot extract stage155')
        root=Path(td)/STAGE155_ROOT
        s=json.loads((root/'SUMMARY.json').read_text())
        require(s.get('tool_version')=='0.1.73','stage155 version drift')
        require(s.get('stage154_evidence_sha256')==STAGE154_SHA256,'stage154 chain drift')
        require(s.get('school_focus_transition_rows')==3 and s.get('school_focus_source_wet_transition_rows')==1,'focus transition count drift')
        require(s.get('school_focus_target_wet_transition_rows')==0,'target unexpectedly has wet transition')
        require(s.get('source_wet_only_shared_payload_family_rows')==7,'wet-only family count drift')
        require(s.get('parse_skip_rows')==0,'stage155 parse skips')
        focus=list(csv.DictReader((root/'SCHOOL_WET_FOCUS_TEXTURE_TRANSITIONS.tsv').open(),delimiter='\t'))
        cross=list(csv.DictReader((root/'SOURCE_WET_ONLY_SHARED_TARGET_INDEX_AUDIT.tsv').open(),delimiter='\t'))
        return s,focus,cross

def rgb565(v:int)->tuple[int,int,int]:
    r=(v>>11)&31; g=(v>>5)&63; b=v&31
    return ((r*255+15)//31,(g*255+31)//63,(b*255+15)//31)

def _interp(a:int,b:int,wa:int,wb:int,d:int)->int: return (wa*a+wb*b)//d

def decode_base_stats(payload: bytes, tex_type:int, width:int, height:int) -> dict[str,Any]:
    if tex_type==0x59: block_bytes=8; fmt='BC1'
    elif tex_type==0x5B: block_bytes=16; fmt='BC3'
    else: return {'decode_status':'unsupported','format_class':f'0x{tex_type:02x}'}
    bw=(width+3)//4; bh=(height+3)//4; need=bw*bh*block_bytes
    require(len(payload)>=need,f"payload shorter than base mip: {len(payload)} < {need}")
    count=0; sr=sg=sb=sa=0; sr2=sg2=sb2=sa2=0; amin=255; amax=0; rmin=gmin=bmin=255; rmax=gmax=bmax=0; zero=nonopaque=gray=0; alpha_mode_blocks=0
    off=0
    for by in range(bh):
      for bx in range(bw):
        block=payload[off:off+block_bytes]; off+=block_bytes
        if tex_type==0x5B:
            a0,a1=block[0],block[1]; bits=int.from_bytes(block[2:8],'little')
            ap=[a0,a1]
            if a0>a1:
                ap += [((7-i)*a0+i*a1)//7 for i in range(1,7)]
            else:
                ap += [((5-i)*a0+i*a1)//5 for i in range(1,5)] + [0,255]
            cpart=block[8:16]; c0,c1,ci=struct.unpack('<HHI',cpart)
            p0=rgb565(c0); p1=rgb565(c1)
            cp=[p0,p1,tuple(_interp(p0[j],p1[j],2,1,3) for j in range(3)),tuple(_interp(p0[j],p1[j],1,2,3) for j in range(3))]
        else:
            c0,c1,ci=struct.unpack('<HHI',block); p0=rgb565(c0); p1=rgb565(c1)
            if c0>c1:
                cp=[p0,p1,tuple(_interp(p0[j],p1[j],2,1,3) for j in range(3)),tuple(_interp(p0[j],p1[j],1,2,3) for j in range(3))]; ap=[255]*4
            else:
                alpha_mode_blocks+=1; cp=[p0,p1,tuple((p0[j]+p1[j])//2 for j in range(3)),(0,0,0)]; ap=[255,255,255,0]
        for py in range(4):
          y=by*4+py
          if y>=height: continue
          for px in range(4):
            x=bx*4+px
            if x>=width: continue
            pi=py*4+px; idx=(ci>>(2*pi))&3; r,g,b=cp[idx]
            if tex_type==0x5B: ai=(bits>>(3*pi))&7; a=ap[ai]
            else: a=ap[idx]
            count+=1; sr+=r;sg+=g;sb+=b;sa+=a; sr2+=r*r;sg2+=g*g;sb2+=b*b;sa2+=a*a
            rmin=min(rmin,r);gmin=min(gmin,g);bmin=min(bmin,b);amin=min(amin,a);rmax=max(rmax,r);gmax=max(gmax,g);bmax=max(bmax,b);amax=max(amax,a)
            if a==0: zero+=1
            if a<255: nonopaque+=1
            if max(r,g,b)-min(r,g,b)<=2: gray+=1
    def mean(s): return s/count if count else 0.0
    def std(s,s2):
        m=mean(s); return math.sqrt(max(0.0,s2/count-m*m)) if count else 0.0
    return {
      'decode_status':'ok','format_class':fmt,'base_mip_bytes':need,'decoded_pixels':count,
      'r_min':rmin,'r_max':rmax,'r_mean':round(mean(sr),6),'r_std':round(std(sr,sr2),6),
      'g_min':gmin,'g_max':gmax,'g_mean':round(mean(sg),6),'g_std':round(std(sg,sg2),6),
      'b_min':bmin,'b_max':bmax,'b_mean':round(mean(sb),6),'b_std':round(std(sb,sb2),6),
      'alpha_min':amin,'alpha_max':amax,'alpha_mean':round(mean(sa),6),'alpha_std':round(std(sa,sa2),6),
      'alpha_zero_pixels':zero,'alpha_nonopaque_pixels':nonopaque,'alpha_nonopaque_ratio':round(nonopaque/count,8) if count else 0.0,
      'near_grayscale_pixels':gray,'near_grayscale_ratio':round(gray/count,8) if count else 0.0,
      'bc1_alpha_mode_blocks':alpha_mode_blocks,
    }

def raw_entry(data: bytes, parsed: Mapping[str,Any], idx:int) -> bytes:
    r=parsed['entries'][idx]; return data[int(r['entry_offset']):int(r['entry_offset'])+int(r['entry_size'])]

def payload_entry(data: bytes, parsed: Mapping[str,Any], idx:int) -> bytes:
    r=parsed['entries'][idx]; raw=raw_entry(data,parsed,idx); return raw[int(r['payload_offset_in_entry']):]

def rebuild_one_entry(target_data: bytes, parser: Any, idx:int, replacement_raw: bytes) -> bytes:
    p=parser.parse_g1t(target_data,'target-rebuild-base'); n=p['texture_count']; require(0<=idx<n,'bad replacement index')
    endian='<' if p['byte_order']=='little' else '>'
    header_size=int(p['header_size'])
    offsets=[struct.unpack_from(endian+'I',target_data,header_size+4*i)[0] for i in range(n)]
    base_offset=offsets[0]; require(base_offset>=4*n,'unexpected first texture offset')
    prefix=bytearray(target_data[:header_size])
    table_extra=bytearray(target_data[header_size:header_size+base_offset])
    raws=[raw_entry(target_data,p,i) for i in range(n)]; raws[idx]=replacement_raw
    new_offsets=[]; cursor=base_offset
    for r in raws: new_offsets.append(cursor); cursor+=len(r)
    for i,o in enumerate(new_offsets): struct.pack_into(endian+'I',table_extra,4*i,o)
    out=prefix+table_extra+b''.join(raws)
    struct.pack_into(endian+'I',out,8,len(out))
    return bytes(out)

def gust_list(gust:Path,p:Path,timeout:int=120)->tuple[str,int]:
    """List a G1T with gust_g1t without assuming the tool's stdout encoding.

    Some real/vendor builds emit non-UTF-8 bytes in descriptive text.  The only
    information needed here is the number of ASCII entry lines, so keep stdout
    as bytes and match the ASCII ``0x`` prefix directly.
    """
    if not gust.is_file(): return 'not_available',0
    try:
        cp=subprocess.run(
            [str(gust),'-l',str(p)],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=False,timeout=timeout,
        )
    except subprocess.TimeoutExpired: return 'timeout',0
    if cp.returncode!=0: return f'error_{cp.returncode}',0
    return 'ok',sum(1 for line in cp.stdout.splitlines() if line.startswith(b'0x'))

def build_report(project_root:Path,*,report_root:Path|None=None,output_report_root:Path|None=None,workspace_root:Path|None=None,original_root:Path|None=None,quartet_root:Path|None=None,gust_pak_path:Path|None=None,verify_payload_hashes:bool=True,create_archive:bool=True,timeout_seconds:int=1800)->tuple[Path|None,dict[str,Any]]:
    project_root=project_root.resolve(); report_root=(report_root or project_root/'.local/reports/quartet_restoration').resolve(); output_report_root=(output_report_root or report_root).resolve(); workspace_root=(workspace_root or project_root/'.local/workspaces/quartet_restoration'/WORKSPACE_SUBDIR).resolve()
    output=output_report_root/REPORT_DIR; archive=output_report_root/REPORT_NAME
    if output.exists(): import shutil; shutil.rmtree(output)
    output.mkdir(parents=True)
    s155,focus155,cross155=read_stage155(report_root)
    focus5=next(r for r in focus155 if int(r['texture_slot'])==5)
    require(int(focus5['dry_texture_id'])==FOCUS_DRY_ID and int(focus5['wet_texture_id'])==FOCUS_WET_ID,'stage155 focus id drift')
    require(focus5['source_dry_payload_sha256']==FOCUS_DRY_SHA and focus5['target_dry_payload_sha256']==FOCUS_DRY_SHA,'exact dry control drift')
    require(focus5['source_wet_payload_sha256']==FOCUS_SOURCE_WET_SHA,'source wet focus hash drift')
    require(focus5['target_wet_payload_sha256']==FOCUS_DRY_SHA,'Quartet wet no longer reuses dry placeholder')
    progress('stage-155 prerequisite verified; rehydrating focused Hinako wet texture packs read-only')
    st155=load_module(project_root/'workstreams/quartet_restoration/155_collect_hinako_wet_texture_entry_differential_evidence.py','stage156_st155')
    br=load_module(project_root/'Blue_Reflection_Text_Tool/br_restoration_tool.py','stage156_br')
    st125=load_module(project_root/'workstreams/quartet_restoration/125_collect_character_state_exact_rehydration_evidence.py','stage156_st125')
    inventories=st125.load_asset_inventories(project_root); required=[p for _,p in PACKS]
    extraction=st125.ensure_extraction_cache(project_root=project_root,workspace_root=workspace_root,inventories=inventories,required_paths=required,original_root=original_root,quartet_root=quartet_root,gust_pak_path=gust_pak_path,br=br,timeout_seconds=timeout_seconds)
    bytes_map={}; parsed={}; input_rows=[]
    for side in ('source','target'):
      for token,norm in PACKS:
        pair_id,e=inventories[(side,norm.casefold())]; local=br.inventory_workspace_file(workspace_root,side,pair_id,str(e['archive']),str(e['path'])); require(local.is_file(),f'missing {side} {norm}')
        actual=sha256_file(local)
        if verify_payload_hashes: require(actual==str(e['sha256']),f'payload hash drift {side}:{token}:{actual}')
        data=local.read_bytes(); p=st155.parse_g1t(data,f'{side}:{token}'); bytes_map[(side,token)]=data; parsed[(side,token)]=p
        input_rows.append({'side':side,'state_token':token,'normalized_path':norm,'sha256':actual,'size':len(data),'payload_in_evidence':False})
    # Exact focus checks on real payloads.
    source_dry=parsed[('source','scl')]['entries'][FOCUS_DRY_ID]
    target_dry=parsed[('target','scl')]['entries'][FOCUS_DRY_ID]
    source_wet=parsed[('source','scl_w')]['entries'][FOCUS_WET_ID]
    target_wet=parsed[('target','scl_w')]['entries'][FOCUS_WET_ID]
    require(source_dry['raw_entry_sha256']==target_dry['raw_entry_sha256']==target_wet['raw_entry_sha256'],'focus exact dry/raw control failed')
    require(source_dry['payload_sha256']==target_dry['payload_sha256']==target_wet['payload_sha256']==FOCUS_DRY_SHA,'focus dry payload control failed')
    require(source_wet['payload_sha256']==FOCUS_SOURCE_WET_SHA,'source wet payload drift')
    for tok in ('nkd_w','scl_w','swm_w'):
        require(parsed[('source',tok)]['entries'][FOCUS_WET_ID]['payload_sha256']==FOCUS_SOURCE_WET_SHA,f'source common wet focus drift {tok}')
        require(parsed[('target',tok)]['entries'][FOCUS_WET_ID]['payload_sha256']==FOCUS_DRY_SHA,f'target dry-placeholder reuse drift {tok}')
    # Decode primary focus and coherent source wet-only families spanning nkd/scl/swm.
    target_dry_hashes={str(e['payload_sha256']) for tok,norm in PACKS if tok=='scl' for e in parsed[('target',tok)]['entries']}
    candidate_rows=[]
    for r in cross155:
        packs=set(r['source_wet_packs'].split(','))
        if packs!={'nkd_w','scl_w','swm_w'} or r['target_same_indices_still_exactly_shared']!='True': continue
        loc=r['source_locations'].split(','); idxs={int(x.rsplit(':',1)[1]) for x in loc}; require(len(idxs)==1,'cross-state family index drift'); idx=next(iter(idxs))
        sr=parsed[('source','scl_w')]['entries'][idx]; tr=parsed[('target','scl_w')]['entries'][idx]
        sp=payload_entry(bytes_map[('source','scl_w')],parsed[('source','scl_w')],idx); tp=payload_entry(bytes_map[('target','scl_w')],parsed[('target','scl_w')],idx)
        ss=decode_base_stats(sp,int(sr['texture_type']),int(sr['width']),int(sr['height'])); ts=decode_base_stats(tp,int(tr['texture_type']),int(tr['width']),int(tr['height']))
        candidate_rows.append({
          'texture_index':idx,'source_payload_sha256':sr['payload_sha256'],'target_payload_sha256':tr['payload_sha256'],
          'source_width':sr['width'],'source_height':sr['height'],'target_width':tr['width'],'target_height':tr['height'],'texture_type':sr['texture_type'],
          'source_format':ss.get('format_class',''),'target_format':ts.get('format_class',''),'source_decode_status':ss.get('decode_status',''),'target_decode_status':ts.get('decode_status',''),
          'source_alpha_min':ss.get('alpha_min',''),'source_alpha_max':ss.get('alpha_max',''),'source_alpha_mean':ss.get('alpha_mean',''),'source_alpha_nonopaque_ratio':ss.get('alpha_nonopaque_ratio',''),
          'source_near_grayscale_ratio':ss.get('near_grayscale_ratio',''),'source_r_std':ss.get('r_std',''),'source_g_std':ss.get('g_std',''),'source_b_std':ss.get('b_std',''),
          'target_alpha_min':ts.get('alpha_min',''),'target_alpha_max':ts.get('alpha_max',''),'target_alpha_mean':ts.get('alpha_mean',''),'target_alpha_nonopaque_ratio':ts.get('alpha_nonopaque_ratio',''),
          'target_near_grayscale_ratio':ts.get('near_grayscale_ratio',''),'target_r_std':ts.get('r_std',''),'target_g_std':ts.get('g_std',''),'target_b_std':ts.get('b_std',''),
          'target_payload_present_in_target_dry_packs':str(tr['payload_sha256']) in target_dry_hashes,
          'source_wet_only_shared_across_nkd_scl_swm':True,'target_same_index_shared_across_nkd_scl_swm':True,
          'wet_skin_or_transparency_semantics_confirmed':False,'write_authorized':False,
        })
    focus_src_stats=decode_base_stats(payload_entry(bytes_map[('source','scl_w')],parsed[('source','scl_w')],FOCUS_WET_ID),int(source_wet['texture_type']),int(source_wet['width']),int(source_wet['height']))
    focus_tgt_stats=decode_base_stats(payload_entry(bytes_map[('target','scl_w')],parsed[('target','scl_w')],FOCUS_WET_ID),int(target_wet['texture_type']),int(target_wet['width']),int(target_wet['height']))
    # Simulate a native Quartet G1T rebuild containing exactly one source raw entry.
    src_raw=raw_entry(bytes_map[('source','scl_w')],parsed[('source','scl_w')],FOCUS_WET_ID)
    tgt_data=bytes_map[('target','scl_w')]; rebuilt=rebuild_one_entry(tgt_data,st155,FOCUS_WET_ID,src_raw); rp=st155.parse_g1t(rebuilt,'rebuilt-target-scl_w')
    require(rp['texture_count']==parsed[('target','scl_w')]['texture_count'],'rebuilt texture count drift')
    changed=[]
    for i in range(rp['texture_count']):
        before=raw_entry(tgt_data,parsed[('target','scl_w')],i); after=raw_entry(rebuilt,rp,i)
        if hashlib.sha256(before).digest()!=hashlib.sha256(after).digest(): changed.append(i)
    require(changed==[FOCUS_WET_ID],f'rebuilt changed entries drift: {changed}')
    require(rp['entries'][FOCUS_WET_ID]['raw_entry_sha256']==source_wet['raw_entry_sha256'],'rebuilt focus raw entry mismatch')
    gust=project_root/'.local/vendor/gust_tools/gust_g1t'
    with tempfile.TemporaryDirectory(prefix='stage156-g1t-') as tempdir:
        temp=Path(tempdir)/'pc00_scl_w.g1t'; temp.write_bytes(rebuilt); gs,gc=gust_list(gust,temp)
    require(gs in {'ok','not_available'},f'gust_g1t rebuild validation failed: {gs}')
    if gs=='ok': require(gc==rp['texture_count'],f'gust_g1t rebuilt count mismatch {gc}')
    rebuild_rows=[{
      'target_state_token':'scl_w','texture_index':FOCUS_WET_ID,'target_original_container_size':len(tgt_data),'rebuilt_container_size':len(rebuilt),'size_delta':len(rebuilt)-len(tgt_data),
      'changed_texture_entries':len(changed),'changed_texture_indices':','.join(map(str,changed)),'source_replacement_raw_entry_sha256':source_wet['raw_entry_sha256'],'rebuilt_focus_raw_entry_sha256':rp['entries'][FOCUS_WET_ID]['raw_entry_sha256'],
      'all_other_target_entries_preserved':changed==[FOCUS_WET_ID],'reparse_ok':True,'gust_g1t_list_status':gs,'gust_g1t_list_texture_rows':gc,
      'local_no_install_rebuild_feasible':bool(changed==[FOCUS_WET_ID] and gs in {'ok','not_available'}),'profile_built':False,'pak_repacked':False,'installed_game_modified':False,'write_authorized':False,
    }]
    focus_rows=[{
      'texture_slot':5,'dry_texture_id':FOCUS_DRY_ID,'wet_texture_id':FOCUS_WET_ID,'source_dry_raw_equals_target_dry_raw':source_dry['raw_entry_sha256']==target_dry['raw_entry_sha256'],
      'target_wet_raw_equals_exact_dry_control':target_wet['raw_entry_sha256']==target_dry['raw_entry_sha256'],'source_wet_shared_exactly_across_nkd_scl_swm':True,
      'source_wet_payload_sha256':source_wet['payload_sha256'],'source_wet_dimensions':f"{source_wet['width']}x{source_wet['height']}",'target_wet_payload_sha256':target_wet['payload_sha256'],'target_wet_dimensions':f"{target_wet['width']}x{target_wet['height']}",
      'source_format':focus_src_stats.get('format_class',''),'source_alpha_min':focus_src_stats.get('alpha_min',''),'source_alpha_max':focus_src_stats.get('alpha_max',''),'source_alpha_mean':focus_src_stats.get('alpha_mean',''),'source_alpha_nonopaque_ratio':focus_src_stats.get('alpha_nonopaque_ratio',''),'source_near_grayscale_ratio':focus_src_stats.get('near_grayscale_ratio',''),'source_r_std':focus_src_stats.get('r_std',''),'source_g_std':focus_src_stats.get('g_std',''),'source_b_std':focus_src_stats.get('b_std',''),
      'target_format':focus_tgt_stats.get('format_class',''),'target_alpha_min':focus_tgt_stats.get('alpha_min',''),'target_alpha_max':focus_tgt_stats.get('alpha_max',''),'target_alpha_mean':focus_tgt_stats.get('alpha_mean',''),'target_alpha_nonopaque_ratio':focus_tgt_stats.get('alpha_nonopaque_ratio',''),'target_near_grayscale_ratio':focus_tgt_stats.get('near_grayscale_ratio',''),'target_r_std':focus_tgt_stats.get('r_std',''),'target_g_std':focus_tgt_stats.get('g_std',''),'target_b_std':focus_tgt_stats.get('b_std',''),
      'missing_wet_texture_transition_statistically_grounded':True,'wet_skin_or_transparency_semantics_confirmed':False,'write_authorized':False,
    }]
    write_tsv(output/'INPUTS.tsv',['side','state_token','normalized_path','sha256','size','payload_in_evidence'],input_rows)
    write_tsv(output/'COMMON_WET_SHARED_CONTENT_STATS.tsv',list(candidate_rows[0].keys()) if candidate_rows else ['texture_index'],candidate_rows)
    write_tsv(output/'SCHOOL_SLOT5_CONTENT_ALPHA_AUDIT.tsv',list(focus_rows[0].keys()),focus_rows)
    write_tsv(output/'SCHOOL_SLOT5_TARGET_NATIVE_REBUILD_FEASIBILITY.tsv',list(rebuild_rows[0].keys()),rebuild_rows)
    write_tsv(output/'EXTRACTION_INPUTS.tsv',sorted({k for r in extraction for k in r.keys()}),extraction)
    source_common=[r for r in candidate_rows if r['source_wet_only_shared_across_nkd_scl_swm']]
    summary={
      'type':'br_quartet_restoration_hinako_wet_texture_content_alpha_rebuild_feasibility_evidence_summary','format_version':1,'tool_version':TOOL_VERSION,
      'status':'stage155_grounded_missing_wet_texture_transition_content_alpha_and_local_rebuild_feasibility_complete_no_write','stage155_evidence_sha256':STAGE155_SHA256,
      'stage155_school_focus_transition_rows':s155['school_focus_transition_rows'],'stage155_source_wet_only_shared_payload_family_rows':s155['source_wet_only_shared_payload_family_rows'],
      'cross_state_source_wet_only_exact_shared_rows_analyzed':len(source_common),'focus_texture_index':FOCUS_WET_ID,'focus_dry_control_texture_index':FOCUS_DRY_ID,
      'focus_exact_cross_game_dry_control':True,'focus_target_wet_reuses_exact_dry_entry':True,'focus_source_wet_shared_across_nkd_scl_swm':True,
      'focus_source_format':focus_src_stats.get('format_class'),'focus_source_dimensions':f"{source_wet['width']}x{source_wet['height']}",'focus_target_dimensions':f"{target_wet['width']}x{target_wet['height']}",
      'focus_source_alpha_nonopaque_ratio':focus_src_stats.get('alpha_nonopaque_ratio'),'focus_source_near_grayscale_ratio':focus_src_stats.get('near_grayscale_ratio'),
      'focus_local_target_native_g1t_rebuild_feasible':rebuild_rows[0]['local_no_install_rebuild_feasible'],'focus_rebuild_changed_texture_entry_rows':1,
      'focus_rebuild_gust_g1t_status':gs,'runtime_probe_candidate_rows':1 if rebuild_rows[0]['local_no_install_rebuild_feasible'] else 0,
      'runtime_validated':False,'production_eligible':False,
      'policy':{'content_statistics_are_clues_only':True,'alpha_statistics_are_not_semantics':True,'wet_skin_droplet_semantics_confirmed':False,'wet_transparency_semantics_confirmed':False,'raw_entry_runtime_write_authorized':False,'g1t_container_rebuild_write_authorized':False,'profile_built':False,'pak_repacked':False,'installed_game_modified':False,'core_modified':False,'translation_modified':False,'legacy_dlc_modified':False,'git_modified':False,'proprietary_payloads_in_evidence':False,'whole_g1mm_transplant_reuse_forbidden':True},
      'next_action':'If the local report confirms the exact dry control, target-wet dry-placeholder reuse, source wet entry 23 shared across nkd_w/scl_w/swm_w, successful BC1/BC3 content parsing, and a one-entry target-native scl_w.g1t rebuild accepted by the parser/gust_g1t, prepare a separate no-install PACK10_02 Fast Test profile that changes only pc00_scl_w.g1t entry 23 while retaining the already runtime-stable School_Wet canonical-uniform component. Do not infer transparency or droplet semantics from the texture statistics alone.'
    }
    (output/'SUMMARY.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    for p in output.rglob('*'):
        if p.is_file(): require(not p.name.casefold().endswith(FORBIDDEN_REPORT_EXTENSIONS),f'payload in report: {p.name}')
    if create_archive: make_archive(output,archive); return archive,summary
    return None,summary

def parse_args(argv:Sequence[str]|None=None)->argparse.Namespace:
    p=argparse.ArgumentParser(); p.add_argument('--project-root',type=Path,default=PROJECT_ROOT_DEFAULT); p.add_argument('--report-root',type=Path); p.add_argument('--output-report-root',type=Path); p.add_argument('--workspace-root',type=Path); p.add_argument('--original-root',type=Path); p.add_argument('--quartet-root',type=Path); p.add_argument('--gust-pak',type=Path); p.add_argument('--timeout-seconds',type=int,default=1800); p.add_argument('--no-verify-payload-hashes',action='store_true'); return p.parse_args(argv)

def main(argv:Sequence[str]|None=None)->int:
    a=parse_args(argv)
    try:
        arc,s=build_report(a.project_root,report_root=a.report_root,output_report_root=a.output_report_root,workspace_root=a.workspace_root,original_root=a.original_root,quartet_root=a.quartet_root,gust_pak_path=a.gust_pak,timeout_seconds=a.timeout_seconds,verify_payload_hashes=not a.no_verify_payload_hashes)
        print(json.dumps(s,indent=2,sort_keys=True))
        if arc: print(f'[stage156] report archive: {arc}'); print(f'[stage156] SHA-256: {sha256_file(arc)}')
        return 0
    except Stage156Error as e: print(f'[stage156] ERROR: {e}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
