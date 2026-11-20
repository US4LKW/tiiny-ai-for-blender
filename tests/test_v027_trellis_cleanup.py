"""Offline TRELLIS optional post-process stage and device-side reference chain."""
import importlib.util, json, sys, tempfile, os, struct, base64
from pathlib import Path

p = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('test_offline_v027',p/'test_offline.py')
mod = importlib.util.module_from_spec(spec); sys.modules['test_offline_v027'] = mod
spec.loader.exec_module(mod)
a = sys.modules['addon']
caps=json.loads((p/'fixtures'/'tiiny_capabilities_trellis2.json').read_text())
# Distinguish original no-geometry processing vs opt-in repair modes.
for mode, expected in (
 ('OFF',{}),
 ('DEFAULT',{'simplify':True}),
 ('REMESH256',{'simplify':True,'remesh_resolution':256,'remesh_closing_iterations':1}),
 ('REMESH512',{'simplify':True,'remesh_resolution':512,'remesh_closing_iterations':1}),
):
 settings={'model': 'microsoft/TRELLIS.2-4B','faces':0,'seed':-1,'custom':[],
           'trellis_postprocess':mode}
 # v0.3.0 makes Standard explicit; legacy surface settings are preserved.
 assert a._stage_params(caps,settings,'simplify','STANDARD')==({'asset_quality':'balance','simplify':True} | (expected if mode!='OFF' else {}))
# Hunyuan must never receive TRELLIS-only remesh overrides.
h=json.loads((p/'fixtures'/'tiiny_capabilities_hunyuan3d.json').read_text())
assert 'remesh_resolution' not in a._stage_params(h,{'model':'Tencent/Hunyuan3d-2.1','faces':0,'seed':-1,'custom':[],
       'trellis_postprocess':'REMESH512'},'simplify','STANDARD')

raw=json.dumps({'asset':{'version':'2.0'},'materials':[{}], 'textures':[{},{}]}).encode()
raw+=b' '*((-len(raw))%4)
glb=struct.pack('<4sII',b'glTF',2,20+len(raw))+struct.pack('<II',len(raw),0x4E4F534A)+raw
orig_req=a._request
orig_sleep=a.time.sleep
try:
 for mode, expected_stages in [('OFF',['shape','texture','export']),
                               ('DEFAULT',['shape','simplify','texture','export']),
                               ('REMESH256',['shape','simplify','texture','export'])]:
  with tempfile.TemporaryDirectory() as temp:
   image=Path(temp,'source.png');image.write_bytes(b'placeholder data; no image decoding with auto_prepare=False')
   posted=[];inp=[];current={}
   def req(method, base, key, path, model='', fields=None, files=None,timeout=40,raw=False):
    if path=='/v1/3d/capabilities':return caps
    if path=='/v1/3d/tasks' and method=='POST':
     stage=fields['stage'];params=json.loads(fields['params'])
     posted.append((stage,params))
     inref=json.loads(fields.get('input_refs') or '{}')
     inp.append((stage,inref))
     current[stage]=str(len(posted))
     return {'task_id':str(len(posted))}
    if method=='GET' and path.startswith('/v1/3d/tasks/'):
     tid=path.split('/')[-1];stage=posted[int(tid)-1][0]
     output={'shape':{'artifacts':[{'artifact_type':'shape_artifact','artifact_id':'shape1'}]},
             'simplify':{'artifacts':[{'artifact_type':'geometry_artifact','artifact_id':'geo1'}]},
             'texture':{'artifacts':[{'artifact_type':'material_artifact','artifact_id':'mat1'}]},
             'export':{'glb':base64.b64encode(glb).decode(),
                       'artifacts':[{'artifact_type':'mesh_glb','payload_key':'glb','filename':'output.glb'}]}}[stage]
     return {'status':'completed','progress':100,'result':{'output':output}}
    raise AssertionError((method,path))
   a._request=req; a.time.sleep=lambda _:None
   job='trellis_'+mode
   a._JOBS[job]={'state':'queued','progress':0}
   cfg={'base':'http://tiinyhost.local','key':'fake','model':'microsoft/TRELLIS.2-4B',
        'image':str(image),'output_dir':temp,'quality':'STANDARD','texture':True,
        'faces':0,'seed':-1,'custom':[],'trellis_postprocess':mode,'auto_prepare':False}
   a._generate_worker(job,cfg)
   assert a._JOBS[job]['state']=='importing',(mode,a._JOBS[job])
   assert [x[0] for x in posted]==expected_stages,(mode,posted)
   if mode!='OFF':
    assert inp[-1][1]['geometry_artifact']=={'task_id':'2','artifact_id':'geo1'},inp
    assert posted[1][1]['simplify'] is True
    if mode=='REMESH256':assert posted[1][1]['remesh_resolution']==256
   assert Path(a._JOBS[job]['filename']).is_file()
   report=json.loads(Path(a._JOBS[job]['filename']).with_suffix('.json').read_text())
   assert report['trellis_geometry_cleanup']==mode
 print('PASS: TRELLIS default unaffected; opt-in cleanup stage/remesh controls; artifact reference arrives at export; manifest records mode')
finally:
 a._request=orig_req;a.time.sleep=orig_sleep
