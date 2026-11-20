"""Smoke-check both Preferences and Blender sidebar layout calls with fake bpy UI objects."""
import importlib.util, json, sys
from pathlib import Path
from types import SimpleNamespace
sp=importlib.util.spec_from_file_location('smoke',Path(__file__).with_name('test_offline.py'))
m=importlib.util.module_from_spec(sp);sys.modules['smoke']=m;sp.loader.exec_module(m)
a=sys.modules['addon']
t=json.loads((Path(__file__).parent / 'fixtures' / 'tiiny_capabilities_trellis2.json').read_text())
class Layout:
    def __init__(self):self.seen=[]
    def row(self,*arg,**kw):return self
    def column(self,*arg,**kw):return self
    def box(self,*arg,**kw):return self
    def label(self,**kw):self.seen.append(('label',kw.get('text','')));return self
    def prop(self,owner,name,**kw):self.seen.append(('prop',name));return self
    def operator(self,name,**kw):self.seen.append(('operator',name));return SimpleNamespace(mode='')
    def separator(self,*arg,**kw):self.seen.append(('separator',''))
    def template_icon(self,*arg,**kw):pass
    def progress(self,**kw):self.seen.append(('progress',kw));return self
    def split(self,*arg,**kw):return self
    def grid_flow(self,*arg,**kw):return self
    @property
    def enabled(self):return True
    @enabled.setter
    def enabled(self,value):pass
pref=SimpleNamespace(tiiny_model=a.MODELS[1][0],tiiny_api_url='http://tiinyhost.local',
                     tiiny_api_key='test-key',input_dir='/tmp/input',output_dir='/tmp/output',
                     use_local_image_tools=True)
cs=[]
for c in a._extract_stage_controls(t):
    cs.append(SimpleNamespace(model_id=pref.tiiny_model,stage=c['stage'],param_name=c['key'],label=c['label'],
         enabled=False,datatype=c['kind'],value_enum='fast',value_int=0,value_bool=False,value_text='',value_float=0.0,
         default_json=json.dumps(c['default']),min_json=json.dumps(c['min']) if c['min'] is not None else '',
         max_json=json.dumps(c['max']) if c['max'] is not None else '',help_text=c['help']))
props=SimpleNamespace(model=a.MODELS[1][0],image='',prepared_image='',quality='CUSTOM',auto_prepare=True,
    remove_bg=True,smart_crop=True,occupancy=.85,upscale=True,segment_model='isnet-general-use',canvas='AUTO',
    texture=True,controls=cs,seed=-1,faces=0,job_id='',trellis_postprocess='OFF')
ctx=SimpleNamespace(scene=SimpleNamespace(tiiny_settings=props),preferences=SimpleNamespace(addons={'addon':SimpleNamespace(preferences=pref)}))
a._CAPABILITIES[(a._identity(pref.tiiny_api_url,pref.tiiny_api_key),pref.tiiny_model)]={'caps':t}
# Existing UI smoke expectations describe the normal post-install mode.
a._setup_ready=lambda: True
a._setup_in_progress=lambda: False
for cls in (a.TIINY_Preferences,a.TIINY_PT_Main,a.TIINY_PT_Advanced):
    self=object.__new__(cls)
    lay=Layout(); self.layout=lay
    # preferences simulated with same fields
    if cls==a.TIINY_Preferences:
        for k,v in vars(pref).items():setattr(self,k,v)
    self.draw(ctx)
    print(cls.__name__,len(lay.seen),'layout operations')
    assert lay.seen
    if cls==a.TIINY_Preferences:
        assert ('prop','input_dir') in lay.seen and ('prop','output_dir') in lay.seen
        assert ('prop','tiiny_model') in lay.seen
    if cls==a.TIINY_PT_Main:
        assert ('operator','tiiny.select_image') in lay.seen
    if cls==a.TIINY_PT_Advanced:
        assert ('prop','value_enum') in lay.seen and ('prop','value_int') in lay.seen
print('PASS: Preferences + main panel + typed Custom controls render in fake UI')

# Live progress must be displayed through Blender 5.3 UILayout.progress.
a._JOBS['live_test']={'state':'running','stage':'texture','progress':37,'message':'Texture: sampling'}
props.job_id='live_test'
lay=Layout(); view=object.__new__(a.TIINY_PT_Main); view.layout=lay
view.draw(ctx)
bars=[v for kind,v in lay.seen if kind=='progress']
assert len(bars)==1 and bars[0]['factor']==.37 and bars[0]['type']=='BAR'
assert '37%' in bars[0]['text'] and 'Texture' in bars[0]['text']
print('PASS: sidebar uses native progress bar for active Tiiny job')

# Onboarding must not treat a missing PNG as an error while background setup runs.
import time
props.job_id = ''
a._JOBS.clear()
a._status_set('prep', state='working', signature='', phase=4,
              started_at=time.monotonic()-4, message='Loading background model (first use may download weights)')
lay = Layout()
view = object.__new__(a.TIINY_PT_Main)
view.layout = lay
view.draw(ctx)
preparation_bars = [v for kind,v in lay.seen if kind == 'progress'
                    and 'Preparation:' in v.get('text','')]
assert len(preparation_bars) == 1, preparation_bars
assert preparation_bars[0]['text'] == 'Preparation: stage 4/7'
assert preparation_bars[0]['type'] == 'BAR'
assert 0 < preparation_bars[0]['factor'] < 1
labels = [v for kind,v in lay.seen if kind == 'label']
assert any('Elapsed:' in v for v in labels)
assert any('First use:' in v for v in labels)
assert any('model' in v.lower() for v in labels)
print('PASS: setup-stage progress, elapsed time and first-use explanation appear in sidebar')
