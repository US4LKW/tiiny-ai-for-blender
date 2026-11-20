"""Regression: native Blender progress + source-guided Hunyuan optional controls."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

p = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('offline_v026', p / 'test_offline.py')
offline = importlib.util.module_from_spec(spec)
sys.modules['offline_v026'] = offline
spec.loader.exec_module(offline)
a = sys.modules['addon']
h = json.loads((p/'fixtures'/'tiiny_capabilities_hunyuan3d.json').read_text())
t = json.loads((p/'fixtures'/'tiiny_capabilities_trellis2.json').read_text())

# Expose typed Custom Hunyuan fields only when advertised by the device.
controls = a._extract_stage_controls(h)
indexed = {(x['stage'], x['key']): x for x in controls}
for stage, name, kind in [
    ('shape', 'step', 'int'), ('shape', 'guidance_scale', 'float'),
    ('texture', 'paint_step', 'int'), ('texture', 'guidance_scale', 'float'),
]:
    assert indexed[(stage, name)]['kind'] == kind
assert indexed[('shape', 'step')]['min'] == 1
assert indexed[('shape', 'step')]['max'] == 20
assert not any(x['stage']=='shape' and x['key']=='step' for x in a._extract_stage_controls(t))
# Removing an advertised name also removes the inferred UI control.
removed = json.loads(json.dumps(h))
removed['params']['shape'].remove('step')
assert ('shape','step') not in {(x['stage'],x['key']) for x in a._extract_stage_controls(removed)}
assert a._global_preset(h,'MAXIMUM') == {'output_precision':'high','inference_quality':'quality','asset_quality':'quality'}
# No silent Custom injection if top-level Tiiny supported list changes.
settings={'faces':0,'seed':-1, 'custom':[
    {'stage':'shape','param':'step','enabled':True,'value':10},
    {'stage':'shape','param':'does_not_exist','enabled':True,'value':5},
]}
assert a._stage_params(h,settings,'shape','CUSTOM') == {'step':10}
assert 'step' not in a._stage_params(removed,settings,'shape','CUSTOM')

# Native UILayout.progress gets a normalized factor and stage label.
class FakeLayout:
    def __init__(self): self.bar=None
    def progress(self,*,factor,text,type):self.bar=(factor,text,type)
for source,expect in [({'progress':36,'stage':'shape'},.36),
                      ({'progress':101,'stage':'export'},1.0),
                      ({'progress':-7,'stage':'queued'},0.0),
                      ({'progress':None},0.0),
                      ({'progress':'no number'},0.0),
                      ({'progress':float('nan')},0.0)]:
    lay=FakeLayout();a._draw_job_progress(lay,source)
    assert lay.bar is not None
    assert lay.bar[0] == expect and lay.bar[2]=='BAR'
    assert '%' in lay.bar[1]

# Main panel must draw bar for live jobs as well as percentages.
spec2 = importlib.util.spec_from_file_location('ui_offline',p/'test_ui_offline.py')
# The UI test file is run separately and enhanced below.
print('PASS: upstream optional Hunyuan controls, Tiiny advert guard, preset safety, native progress factors')
