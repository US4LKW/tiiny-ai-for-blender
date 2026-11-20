"""Regression checks for opt-in local preparation and narrow sidebar onboarding."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import tempfile
import time

spec = importlib.util.spec_from_file_location('v035_test_base', Path(__file__).with_name('test_offline.py'))
base = importlib.util.module_from_spec(spec)
sys.modules['v035_test_base'] = base
spec.loader.exec_module(base)
a = sys.modules['addon']

class Layout:
    def __init__(self):
        self.labels=[]
        self.props=[]
        self.operators=[]
        self.bars=[]
        self._enabled=True
    def box(self,*args,**kw):return self
    def row(self,*args,**kw):return self
    def column(self,*args,**kw):return self
    def label(self,*,text='',icon='NONE'):self.labels.append(str(text))
    def prop(self,owner,name,*args,**kw):self.props.append(name)
    def operator(self,name,*args,**kw):
        self.operators.append(name)
        return SimpleNamespace(mode='')
    def template_icon(self,*args,**kw):pass
    def progress(self,**kw):self.bars.append(kw)
    def separator(self):pass
    @property
    def enabled(self):return self._enabled
    @enabled.setter
    def enabled(self,val):self._enabled=val

with tempfile.TemporaryDirectory() as temp:
    base_dir=Path(temp)
    img=base_dir/'reference.png'
    img.write_bytes(b'placeholder source pixels')
    pref=SimpleNamespace(
        tiiny_api_url='http://tiinyhost.local',tiiny_api_key='test',
        tiiny_model=a.MODELS[1][0], input_dir=str(base_dir), output_dir=str(base_dir),
        use_local_image_tools=True)
    props=SimpleNamespace(image=str(img),prepared_image='',prepared_signature='',original_preview=None,
        auto_prepare=True,remove_bg=True,segment_model='isnet-general-use',smart_crop=True,
        canvas='AUTO',occupancy=.85,upscale=True,texture=True,quality='STANDARD',
        seed=42,faces=0,controls=[],job_id='',trellis_postprocess='OFF',
        trellis_overrides=False,hunyuan_overrides=False,trellis_custom_base='NATIVE',
        hunyuan_custom_base='NATIVE',save_stage_previews=False,show_request_preview=False,
        trellis_quality='STANDARD',hunyuan_quality='STANDARD')
    scene=SimpleNamespace(tiiny_settings=props)
    ctx=SimpleNamespace(scene=scene,preferences=SimpleNamespace(addons={'addon':SimpleNamespace(preferences=pref)}))
    a._IMAGE_SELECTIONS[a._scene_token(scene)]=str(img)
    a._status_set('setup',state='not_ready',phase=0,message='Not started')
    old_ready=a._setup_ready
    old_busy=a._setup_in_progress
    old_begin=a._begin_background_setup
    old_record=a._prep_install_status
    a._setup_ready=lambda:False
    a._setup_in_progress=lambda:True
    a._prep_install_status=lambda:dict(python=False,rembg=False,weights=False,validated=False,log=base_dir/'nothing.log')
    try:
        # First-run: no image picker, preview or preparation until tools are ready.
        a._status_set('setup',state='working',phase=5,message='Preparing ISNet weights',started_at=time.monotonic()-5)
        layout=Layout(); a.TIINY_PT_Main.draw(SimpleNamespace(layout=layout),ctx)
        assert 'tiiny.select_image' not in layout.operators
        assert 'tiiny.clear_image' not in layout.operators
        assert 'tiiny.prepare_image' not in layout.operators
        assert 'tiiny.generate_3d' not in layout.operators
        assert any('Tools setup' in p.get('text','') for p in layout.bars)
        assert any('Image tools are not ready' in l for l in layout.labels)
        assert all('Tools ready: 100%' not in l for l in layout.labels)
        # Preferences toggle visible and same progress bar.
        panel=object.__new__(a.TIINY_Preferences)
        for k,v in vars(pref).items():setattr(panel,k,v)
        panel.layout=Layout(); panel.draw(ctx)
        assert 'use_local_image_tools' in panel.layout.props
        assert any('Tools setup' in p.get('text','') for p in panel.layout.bars)
        # Direct mode: no progress, no processing controls, no second thumbnail.
        pref.use_local_image_tools=False
        a._status_set('setup',state='ok',phase=6,message='Ready')
        layout=Layout();a.TIINY_PT_Main.draw(SimpleNamespace(layout=layout),ctx)
        assert 'tiiny.select_image' in layout.operators
        assert 'tiiny.generate_3d' in layout.operators
        assert 'tiiny.prepare_image' not in layout.operators
        assert 'tiiny.refresh_thumbnails' not in layout.operators
        assert 'remove_bg' not in layout.props and 'auto_prepare' not in layout.props
        assert 'texture' in layout.props
        assert not any('Tools ready' in x or 'Local image tools' in x for x in layout.labels)
        assert any('transparent PNG' in x for x in layout.labels)
        s=a._settings_snapshot(ctx)
        assert not s['use_local_image_tools'] and not s['auto_prepare'] and not s['remove_bg']
        layout=Layout();a.TIINY_PT_Advanced.draw(SimpleNamespace(layout=layout),ctx)
        assert 'canvas' not in layout.props and 'smart_crop' not in layout.props
        assert 'seed' in layout.props and 'faces' in layout.props
        # Enabling normal operation shows no permanent status banner.
        pref.use_local_image_tools=True
        a._setup_ready=lambda:True
        a._setup_in_progress=lambda:False
        layout=Layout();a.TIINY_PT_Main.draw(SimpleNamespace(layout=layout),ctx)
        assert 'tiiny.prepare_image' in layout.operators
        assert 'tiiny.refresh_thumbnails' in layout.operators
        assert 'auto_prepare' in layout.props and 'remove_bg' in layout.props
        assert not any('Tools ready' in x or 'Local image tools' in x for x in layout.labels)
        assert not any('Tools setup' in x.get('text','') for x in layout.bars)
        # Toggle handlers never erase installed tools, just the preview and queues.
        a._begin_background_setup=lambda:True
        a._AUTO_PREP_REQUEST=(time.monotonic()+10,{'image':str(img)})
        pref.use_local_image_tools=False
        a._on_local_tools_toggle(pref,ctx)
        assert a._AUTO_PREP_REQUEST is None
        assert not a._tools_enabled(pref)
        assert a._accepted_image(ctx)==str(img)
        # Direct-image mode cannot be tricked into launching local preparation.
        try:
            a._prepare_image({'use_local_image_tools':False})
        except RuntimeError as exc:
            assert 'disabled' in str(exc)
        else:
            raise AssertionError('Direct-image mode must not prepare anything locally')
        # No autoreinstall of local weights on a direct-mode request.
        assert a._begin_background_setup() is True  # monkeypatch sanity
        a._begin_background_setup=old_begin
        assert a._begin_background_setup() is False
    finally:
        a._setup_ready=old_ready
        a._setup_in_progress=old_busy
        a._begin_background_setup=old_begin
        a._prep_install_status=old_record
        a._IMAGE_SELECTIONS.clear()
        a._AUTO_PREP_REQUEST=None

# An actual direct-image generation must send the original bytes to the model,
# never call the local image-preparation runtime, and still produce a GLB.
import base64
import json
import struct
with tempfile.TemporaryDirectory() as temp:
    image_path=Path(temp)/'reference.jpg'
    image_path.write_bytes(b'JPEG-BYTES-KEPT-EXACTLY')
    document=json.dumps({'asset':{'version':'2.0'}}).encode('utf-8')
    document+=b' '*((-len(document))%4)
    glb=struct.pack('<4sII',b'glTF',2,20+len(document))+struct.pack('<II',len(document),0x4e4f534a)+document
    calls=[]
    original_request=a._request
    original_prepare=a._prepare_image
    original_sleep=a.time.sleep
    def fake_request(method,base,key,path,model='',fields=None,files=None,raw=False,**kw):
        if path=='/v1/3d/capabilities':
            return {'stages':['shape','texture','export'],'inputs':{'shape':['image']},'input_refs':False}
        if path=='/v1/3d/tasks' and method=='POST':
            calls.append(fields['stage'])
            assert files['image'][1] == image_path.read_bytes()
            return {'task_id':'direct-shape'}
        if path=='/v1/3d/tasks/direct-shape' and method=='GET':
            return {'status':'completed','progress':100,'result':{'output':{'artifacts':[
                {'artifact_type':'mesh_glb_preview','artifact_id':'final-preview'}]}}}
        if '/artifacts/final-preview' in path and raw:
            return glb
        raise AssertionError((method,path))
    a._request=fake_request
    a._prepare_image=lambda *args,**kw: (_ for _ in ()).throw(AssertionError('Local processor used in direct mode'))
    a.time.sleep=lambda _:None
    try:
        for model in (a.MODELS[0][0],a.MODELS[1][0]):
            jid='direct'+str(len(calls))
            a._JOBS[jid]={'state':'queued'}
            a._generate_worker(jid,{'base':'http://tiinyhost.local','key':'test', 'model':model,
                'texture':False,'quality':'STANDARD','custom':[], 'seed':42,'faces':0,
                'image':str(image_path), 'auto_prepare':False,'use_local_image_tools':False,
                'output_dir':temp})
            assert a._job_get(jid)['state']=='importing',a._job_get(jid)
            a._PENDING_IMPORT.get_nowait()
        assert calls==['shape','shape'],calls
    finally:
        a._request=original_request
        a._prepare_image=original_prepare
        a.time.sleep=original_sleep

# Short success model message must not break into several rows in a narrow sidebar.
original_get_caps=a._get_caps
try:
    a._get_caps=lambda *args,**kw:{'stages':['shape','texture','export']}
    a._probe_worker('model','http://tiinyhost.local','test','microsoft/TRELLIS.2-4B','test-identity')
    assert a._status_get('model')['message']=='3D + PBR ready'
finally:
    a._get_caps=original_get_caps
print('PASS: optional tools enabled/disabled, startup panel, direct GLB settings, model label')
