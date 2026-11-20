"""Offline smoke tests for Tiiny AI for Blender, without Blender or a real Pocket Lab."""
import base64
import importlib.util
import json
import os
import struct
import sys
import tempfile
import types
from pathlib import Path

# Minimal Blender API surface to import and register add-on classes.
bpy = types.ModuleType('bpy')
class FakeTypes:
    class PropertyGroup: pass
    class AddonPreferences: pass
    class Operator: pass
    class Panel: pass
    class Scene: pass
    class Image: pass
bpy.types = FakeTypes
bpy_props = types.ModuleType('bpy.props')
for n in ['BoolProperty','CollectionProperty','EnumProperty','FloatProperty','IntProperty','PointerProperty','StringProperty']:
    setattr(bpy_props, n, lambda *args, **kwargs: None)
bpy.props = bpy_props
# Dedicated bpy.utils.previews collection (mock for offline UI checks).
class FakePreview:
    icon_id = 101
class FakePreviewCollection(dict):
    def load(self, slot, filepath, file_type, force_reload=False):
        assert file_type == 'IMAGE'
        assert Path(filepath).is_file() if 'Path' in globals() else os.path.isfile(filepath)
        v = FakePreview()
        self[slot] = v
        return v
preview_module = types.ModuleType('bpy.utils.previews')
preview_module.new = FakePreviewCollection
preview_module.remove = lambda pcoll: pcoll.clear()
utils_module = types.ModuleType('bpy.utils')
utils_module.register_class = lambda x: None
utils_module.unregister_class = lambda x: None
utils_module.previews = preview_module
bpy.utils = utils_module
sys.modules['bpy.utils'] = utils_module
sys.modules['bpy.utils.previews'] = preview_module
bpy.app = types.SimpleNamespace(timers=types.SimpleNamespace(is_registered=lambda x:False,
    register=lambda *a,**kw:None,unregister=lambda *a,**kw:None))
bpy.path = types.SimpleNamespace(abspath=lambda p:p)
sys.modules['bpy']=bpy
sys.modules['bpy.props']=bpy_props
p=str(Path(__file__).parent.parent / 'tiiny_ai_for_blender' / '__init__.py')
spec=importlib.util.spec_from_file_location('addon',p)
a=importlib.util.module_from_spec(spec)
sys.modules['addon']=a
spec.loader.exec_module(a)
a.register()
a.unregister()

assert a._normalize_base('http://tiinyhost.local/v1') == 'http://tiinyhost.local'
for unsafe in ('file:///etc/passwd', 'http://user:pw@bad', 'http://abc/v1/xyz', 'https://abc/?x=y'):
    try:a._normalize_base(unsafe)
    except ValueError: pass
    else: raise AssertionError(unsafe)

caps = {
    'stages': ['shape','simplify','texture','export'],
    'input_refs': False,
    'inputs': {'shape':['image'],'simplify':['mesh'],'texture':['image','mesh'], 'export':['material_artifact','mesh_glb']},
    'stage_specs': {
        'shape': {'params': {'inference_quality': {'type': 'string', 'choices': ['low', 'medium', 'high'], 'default': 'medium'},
                             'seed': {'type':'integer', 'default':0}}},
        'texture': {'params': {'asset_quality': {'type':'integer','minimum':1, 'maximum':5, 'default':3},
                               'output_precision': {'choices': ['fp16', 'fp32'], 'default': 'fp16'}}},
        'simplify': {'params': {'target_faces':{'type':'integer','min':1000,'max':500000}}},
        'export': {'params': []},
    }
}
assert a._preset_stage_params(caps,'DRAFT','shape') == {'inference_quality':'low'}
assert a._preset_stage_params(caps,'MAXIMUM','shape') == {'inference_quality':'high'}
assert a._preset_stage_params(caps,'MAXIMUM','texture') == {'asset_quality':5}
assert a._preset_stage_params(caps,'DRAFT','texture') == {'asset_quality':1}
assert a._preset_stage_params(caps,'STANDARD','texture') == {}
assert not any('output_precision' in v for v in (a._preset_stage_params(caps,'DRAFT','texture'),a._preset_stage_params(caps,'MAXIMUM','texture')))

# Synthetic GLB with correctly shaped JSON chunk (not renderable but enough to check transport).
doc=json.dumps({'asset':{'version':'2.0'},'materials':[{}], 'textures':[{}], 'images':[{}]}).encode('utf-8')
doc+=b' ' * ((-len(doc)) % 4)
glb=struct.pack('<4sII',b'glTF',2,20+len(doc)) + struct.pack('<II',len(doc),0x4E4F534A)+doc
assert a._glb_counts(glb)=={'materials':1,'textures':1,'images':1}

# Simulate two separate stage pipelines, including device-side references for TRELLIS.
for trellis in (False, True):
    record=[]
    step={'index':0, 'tid':'', 'phase':''}
    local_caps = {**caps, 'input_refs': trellis}
    if trellis:
        local_caps['inputs'] = {'shape':['image'],'texture':['shape_artifact','geometry_artifact','image'],
                                'export':['material_artifact','mesh_glb'], 'simplify':['mesh']}
    model='microsoft/TRELLIS.2-4B' if trellis else 'Tencent/Hunyuan3d-2.1'
    def fake_request(method,base,key,path,model='',fields=None,files=None,timeout=40,raw=False):
        record.append((method,path,model,fields or {},list((files or {}).keys())))
        if path == '/v1/3d/capabilities':return local_caps
        if method=='POST' and path=='/v1/3d/tasks':
            step['index']+=1
            step['phase']=fields['stage']
            step['tid']='task'+str(step['index'])
            if trellis and step['phase']=='texture':
                assert 'shape_artifact' in json.loads(fields['input_refs'])
                assert 'geometry_artifact' in json.loads(fields['input_refs'])
                assert 'image' in files
            if trellis and step['phase']=='export':
                assert 'material_artifact' in json.loads(fields['input_refs'])
            return {'task_id':step['tid']}
        if method=='GET' and path.startswith('/v1/3d/tasks/') and '/artifacts/' not in path:
            stage = step['phase']
            if stage=='shape' and trellis:
                return {'progress':100,'status':'completed','result':{'output':{'artifacts':[
                  {'artifact_type':'shape','artifact_id':'s1'},
                  {'artifact_type':'geometry','artifact_id':'g1'},
                  {'artifact_type':'mesh_glb_preview','artifact_id':'p1'},
                ]}}}
            if stage=='shape':
                return {'progress':100,'status':'completed','result':{'output':{'artifact_type':'mesh_glb',
                  'glb':base64.b64encode(glb).decode('ascii')}}}
            if stage=='texture':
                if trellis:return {'progress':100,'status':'completed','result':{'output':{'artifacts':[
                    {'artifact_type':'material_artifact','artifact_id':'m1'}]}}}
                return {'progress':100,'status':'completed','result':{'output':{'artifact_type':'material_artifact',
                  'mesh':base64.b64encode(b'materialbytes').decode('ascii')}}}
            if stage=='export':
                return {'progress':100,'status':'completed','result':{'output':{'artifact_type':'mesh_glb',
                  'artifact_id':'glb1'}}}
        if raw and '/artifacts/' in path:return glb
        raise AssertionError((method,path,model))
    original=a._request
    original_sleep=a.time.sleep
    a._request=fake_request
    a.time.sleep=lambda n:None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            image=os.path.join(tmp,'input.png')
            with open(image,'wb') as f:f.write(b'PNGTEST')
            jid='test_'+('trellis' if trellis else 'hunyuan')
            a._JOBS[jid]={'state':'running', 'progress':0}
            data={'base':'http://tiinyhost.local','key':'fake-secret','model':model,
                  'image':image, 'texture':True, 'faces':0,'seed':-1,
                  'quality':'MAXIMUM','custom':[],'output_dir':tmp}
            a._generate_worker(jid, data)
            assert a._JOBS[jid]['state']=='importing', a._JOBS[jid]
            path=a._JOBS[jid]['filename']
            assert os.path.isfile(path)
            assert os.path.isfile(path[:-4]+'.json')
            saved=json.load(open(path[:-4]+'.json',encoding='utf-8'))
            assert saved['quality']=='MAXIMUM'
            assert saved['pbr_textures_requested'] is True
            assert len(record) >= 3
            assert all(m==model for method,path,m,_,_ in record if path.startswith('/v1/3d/'))
            _,importfile = a._PENDING_IMPORT.get_nowait()
            assert importfile == path
    finally:
        a._request=original
        a.time.sleep=original_sleep

print('PASS: registration, safe URL, metadata/schema presets, Hunyuan, TRELLIS references, PBR and GLB output')

# Auth and redirect tests through an actual local HTTP server.
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer right-key':
            self.send_response(401)
            self.end_headers()
            return
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', 'http://example.org/steal')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'data': {'stages': ['shape']}}).encode())
    def log_message(self,*args):pass
server=HTTPServer(('127.0.0.1',0),Handler)
thread=Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    local='http://127.0.0.1:%d' % server.server_address[1]
    assert a._request('GET',local,'right-key','/v1/3d/capabilities', model='Tencent/Hunyuan3d-2.1')['stages']==['shape']
    try:a._request('GET',local,'wrong-key','/test')
    except RuntimeError as exc:assert '401' in str(exc)
    else:raise AssertionError('accepted bad key')
    try:a._request('GET',local,'right-key','/redirect')
    except RuntimeError as exc:assert '302' in str(exc)
    else:raise AssertionError('followed unsafe redirect')
finally:
    server.shutdown();server.server_close()

# Clear separation between successful auth and a stopped 3D engine.
identity='test_fingerprint'
orig_request=a._request
orig_caps=a._get_caps
try:
    a._request=lambda *x,**kw: {'cpu':0}
    def no_model(*args): raise RuntimeError('3D model unavailable (HTTP 503)')
    a._get_caps=no_model
    a._probe_worker('connection','http://tiinyhost.local','right-key','Tencent/Hunyuan3d-2.1',identity)
    assert a._status_get('connection')['state']=='ok'
    assert a._status_get('model')['state']=='error'
finally:
    a._request=orig_request
    a._get_caps=orig_caps

# Schema merging: param name list can be complemented by controls definitions.
merged={'stage_specs':{'shape':{'params':['inference_quality'],'controls':{'inference_quality':{
    'choices':[{'value':'fast'},{'value':'high'}],'default':'high'}}}}}
assert a._extract_stage_controls(merged)[0]['choices']==['fast','high']
assert a._preset_stage_params(merged,'DRAFT','shape')=={'inference_quality':'fast'}

# User overrides must be type checked before dispatch.
entry=types.SimpleNamespace(datatype='int', value_int=11, value_enum='',choices_json='[]',
    min_json='2',max_json='10',param_name='steps')
try:a._cast_custom(entry)
except ValueError:pass
else:raise AssertionError('out-of-range quality accepted')
print('PASS: HTTP auth, redirects refused, stopped model does not invalidate API key, schema merging, custom bounds')
# Shape-only mode can import a preview GLB from TRELLIS without texture/export.
def test_shape_only():
    names=[]
    def fake(method,base,key,path,model='',fields=None,files=None,raw=False,**kwargs):
        if path=='/v1/3d/capabilities':
            return {'stages':['shape','texture','export'],'input_refs':True,'inputs':{'shape':['image']}}
        if method=='POST' and path=='/v1/3d/tasks':
            names.append(fields['stage'])
            return {'task_id':'preview_shape'}
        if '/artifacts/preview' in path and raw:return glb
        if method=='GET' and '/tasks/preview_shape' in path:
            return {'status':'completed','progress':100,'result':{'output':{'artifacts':[
                    {'artifact_type':'mesh_glb_preview','artifact_id':'preview'}]}}}
        raise AssertionError((method,path))
    original=a._request
    sleep=a.time.sleep
    a._request=fake
    a.time.sleep=lambda n:None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            f=os.path.join(tmp,'ref.jpg');open(f,'wb').write(b'JPEG')
            jid='shape_only';a._JOBS[jid]={'state':'queued'}
            a._generate_worker(jid,{'base':'http://tiinyhost.local','key':'key','model':'microsoft/TRELLIS.2-4B',
                       'texture':False,'quality':'STANDARD','custom':[],'seed':-1,'faces':0,'image':f,
                       'output_dir':tmp})
            assert names==['shape'],names
            assert a._job_get(jid)['state']=='importing',a._job_get(jid)
            a._PENDING_IMPORT.get_nowait()
    finally:
        a._request=original
        a.time.sleep=sleep
test_shape_only()
print('PASS: PBR disabled runs shape only and downloads a preview GLB')
