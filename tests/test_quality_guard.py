"""Offline tests for Tiiny capability-bound UI and request quality modes."""
import importlib.util, sys, types, json, os
from pathlib import Path
# Reuse the import mocking in prior offline tests; module stays loaded afterward.
spec=importlib.util.spec_from_file_location('test_offline', Path(__file__).with_name('test_offline.py'))
smoke=importlib.util.module_from_spec(spec)
sys.modules['test_offline'] = smoke
spec.loader.exec_module(smoke)
a=sys.modules['addon']

NO_SCHEMA={'stages':['shape','simplify','texture','export'], 'input_refs':False,
 'inputs':{'shape':['image'],'texture':['image','mesh'],'export':['material_artifact','mesh_glb']}}
assert a._extract_stage_controls(NO_SCHEMA)==[]
assert a._available_quality_modes(NO_SCHEMA)==('STANDARD',)
assert a._effective_quality(NO_SCHEMA,'DRAFT')=='STANDARD'
assert a._effective_quality(NO_SCHEMA,'MAXIMUM')=='STANDARD'
assert a._quality_summary(NO_SCHEMA,'DRAFT')=={}
# Native Hunyuan has known controls, but if Tiiny does not advertise them
# they MUST NOT silently leak into submitted requests.
shape_args=a._stage_params(NO_SCHEMA, {'faces':0,'seed':-1,'custom':[]}, 'shape','MAXIMUM')
assert shape_args == {},shape_args

# Advertised quality, bounds and options support actual distinct presets.
STAGE_SCHEMA={'stages':['shape','texture','export'], 'stage_specs':{
 'shape':{'params':{'num_inference_steps':{'type':'integer','minimum':1,'maximum':20,'default':5},
                    'guidance_scale':{'type':'number','minimum':1.0,'maximum':7.5,'default':5.0}}},
 'texture':{'params':{'texture_size': {'choices':[512,1024,2048],'default':1024}}},
 'export':{'params': []},}}
assert a._available_quality_modes(STAGE_SCHEMA,True)==('STANDARD','DRAFT','MAXIMUM','CUSTOM')
assert a._available_quality_modes(STAGE_SCHEMA,False)==('STANDARD','DRAFT','MAXIMUM','CUSTOM')
assert a._preset_stage_params(STAGE_SCHEMA,'DRAFT','shape')['num_inference_steps']==1
assert a._preset_stage_params(STAGE_SCHEMA,'MAXIMUM','shape')['num_inference_steps']==20
assert a._preset_stage_params(STAGE_SCHEMA,'MAXIMUM','texture')['texture_size']==2048
assert a._quality_summary(STAGE_SCHEMA,'DRAFT',False).get('texture') is None

# An API that only publishes one value does not provide useful Draft/Maximum.
ONLY_ONE={'stage_specs': {'shape': {'params': {'inference_quality':{'choices':['medium']}}}}}
assert a._available_quality_modes(ONLY_ONE)==('STANDARD','CUSTOM')
# Params whose numeric coding is not evidently quality-ordered are not assumed to be quality.
OPAQUE={'stage_specs': {'shape':{'params':{'output_precision':{'choices':['fp16','fp32']}}}}}
assert a._available_quality_modes(OPAQUE)==('STANDARD','CUSTOM')

# Texture-only quality is disabled when PBR is off.
TEXTURE_ONLY={'stage_specs':{'texture':{'params':{'texture_size':{'choices':[512,1024,2048]}}}}}
assert a._available_quality_modes(TEXTURE_ONLY,False)==('STANDARD',)
assert a._available_quality_modes(TEXTURE_ONLY,True)==('STANDARD','DRAFT','MAXIMUM','CUSTOM')

# Guarded worker actually downgrades unavailable presets and saves reason.
import tempfile, base64, struct
with tempfile.TemporaryDirectory() as temp:
    src=os.path.join(temp,'source.png'); open(src,'wb').write(b'FAKE_IMAGE_BYTES')
    raw=json.dumps({'asset':{'version':'2.0'}}).encode()
    raw+=b' ' * ((-len(raw))%4)
    glb=struct.pack('<4sII',b'glTF',2,20+len(raw))+struct.pack('<II',len(raw),0x4E4F534A)+raw
    original_req=a._request
    original_sleep=a.time.sleep
    status={'count':0}
    def request(method,base,key,path,model='',fields=None,files=None,timeout=40,raw=False):
        if path=='/v1/3d/capabilities': return NO_SCHEMA
        if method=='POST' and path=='/v1/3d/tasks':
            params=json.loads(fields['params'])
            assert params=={},'unsupported quality was sent to Tiiny: '+str(params)
            status['count']+=1
            return {'task_id':str(status['count'])}
        if method=='GET' and path.startswith('/v1/3d/tasks/'):
            return {'status':'completed','progress':100,'result':{'output':{
                'artifact_type':'mesh_glb','glb':base64.b64encode(glb).decode()}}}
        raise AssertionError((method,path))
    a._request=request
    a.time.sleep=lambda _:None
    job='quality_guard'
    a._JOBS[job]={'state':'queued','progress':0}
    settings={'base':'http://tiinyhost.local','key':'not-real','model':'Tencent/Hunyuan3d-2.1',
      'image':src,'texture':False,'faces':0,'seed':-1,'quality':'MAXIMUM','custom':[],
      'output_dir':temp,'auto_prepare':False}
    try:
        a._generate_worker(job,settings)
        assert a._JOBS[job]['state']=='importing',a._JOBS[job]
        metadata=json.loads(Path(a._JOBS[job]['filename']).with_suffix('.json').read_text())
        assert metadata['quality_requested']=='MAXIMUM'
        assert metadata['quality']=='STANDARD'
        assert metadata['params_by_stage']=={'shape':{}}
        assert status['count']==1
    finally:
        a._request=original_req
        a.time.sleep=original_sleep
print('PASS: native model does not imply Tiiny support; advertised modes only; worker fallback recorded')
