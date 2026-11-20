"""Real offline validation against two user-exported Tiiny capabilities JSON."""
import importlib.util, sys, json, tempfile
from pathlib import Path
from types import SimpleNamespace
# Load fake bpy and addon from sibling smoke suite.
spec=importlib.util.spec_from_file_location('test_offline',Path(__file__).with_name('test_offline.py'))
mod=importlib.util.module_from_spec(spec);sys.modules['test_offline']=mod;spec.loader.exec_module(mod)
a=sys.modules['addon']
real = Path(__file__).parent / 'fixtures'
h=json.loads((real/'tiiny_capabilities_hunyuan3d.json').read_text())
t=json.loads((real/'tiiny_capabilities_trellis2.json').read_text())
for name,caps in [('Hunyuan',h),('Trellis',t)]:
    print(name, 'quality modes:',a._available_quality_modes(caps,True))
    assert a._available_quality_modes(caps,True)==('STANDARD','DRAFT','MAXIMUM','CUSTOM')
    assert a._available_quality_modes(caps,False)==('STANDARD','DRAFT','MAXIMUM','CUSTOM')
    assert a._global_preset(caps,'DRAFT')=={'output_precision':'draft','inference_quality':'fast','asset_quality':'fast'}
    assert a._global_preset(caps,'MAXIMUM')=={'output_precision':'high','inference_quality':'quality','asset_quality':'quality'}
    expected_standard = ({'output_precision':'standard','inference_quality':'balance'}
                         if name == 'Trellis' else {})
    assert a._preset_stage_params(caps,'STANDARD','shape')==expected_standard

hs=a._preset_stage_params(h,'MAXIMUM','shape')
assert hs=={'output_precision':'high','inference_quality':'quality','asset_quality':'quality'},hs
for stage in ('shape','texture','export','simplify'):
    got=a._preset_stage_params(t,'MAXIMUM',stage)
    expected={'shape':{'output_precision':'high','inference_quality':'quality'},
              'texture':{'inference_quality':'quality'},'export':{'asset_quality':'quality'},
              'simplify':{'asset_quality':'quality'}}[stage]
    assert got==expected,(stage,got,expected)
controls=a._extract_stage_controls(t)
print('TRELLIS controls:',[(x['stage'],x['key'],x['kind'],x['min'],x['max'],x['choices']) for x in controls])
d={(x['stage'],x['key']):x for x in controls}
for field,kind,choices in [('pipeline_type','enum',['512','1024']),('project_geometry','bool',[]),
                           ('texture_size','int',[]),('bake_projection','enum',['vertex_fallback','texel']),
                           ('remesh_resolution','int',[])]:
    stage={'pipeline_type':'shape','project_geometry':'simplify','texture_size':'export',
           'bake_projection':'export','remesh_resolution':'simplify'}[field]
    assert d[(stage,field)]['kind']==kind,(field,d[(stage,field)])
    if choices:assert d[(stage,field)]['choices']==choices
assert d[('export','texture_size')]['min']==256 and d[('export','texture_size')]['max']==8192
assert not [c for c in controls if c['kind']=='unknown']
assert ('export','output_name') not in d
assert ('texture','inference_quality') not in d # controlled globally
# Explicit output path: cache key changes if user moves folder, same source+options.
with tempfile.TemporaryDirectory() as temp:
    inp=Path(temp)/'duck.png';inp.write_bytes(b'source-placeholder')
    opts={'image':str(inp),'model':a.MODELS[0][0], 'remove_bg':True,
          'segment_model':'isnet-general-use','canvas':'AUTO','occupancy':.85,
          'smart_crop':True,'upscale':True,'output_dir':str(Path(temp)/'folderA')}
    s1=a._prep_signature(opts)
    opts['output_dir']=str(Path(temp)/'folderB')
    assert a._prep_signature(opts)!=s1
    assert not (Path(temp)/'folderA').exists() and not (Path(temp)/'folderB').exists()
    ctx=SimpleNamespace(scene=SimpleNamespace(tiiny_settings=SimpleNamespace(
       image=str(inp),texture=True,quality='STANDARD',faces=0,seed=-1,controls=[],
       auto_prepare=True,remove_bg=True,segment_model='isnet-general-use',
       smart_crop=True,canvas='AUTO',occupancy=.85,upscale=True)),
       preferences=SimpleNamespace(addons={'addon':SimpleNamespace(preferences=SimpleNamespace(
          tiiny_api_url='http://tiinyhost.local',tiiny_api_key='dummy',
          tiiny_model=a.MODELS[0][0],output_dir=str(Path(temp)/'folderA'),input_dir=temp))}))
    st=a._settings_snapshot(ctx)
    assert st['output_dir']==str(Path(temp)/'folderA')
    assert st['model']==a.MODELS[0][0]
    ctx.preferences.addons['addon'].preferences.tiiny_model=a.MODELS[1][0]
    ctx.preferences.addons['addon'].preferences.output_dir=str(Path(temp)/'folderB')
    st2=a._settings_snapshot(ctx)
    assert st2['model']==a.MODELS[1][0]
    assert st2['output_dir']==str(Path(temp)/'folderB')
    assert not (Path(temp)/'folderB').exists()
# Manual clear on addon reinstall and .blend load
scene=SimpleNamespace(tiiny_settings=SimpleNamespace(image='old.png',prepared_image='old_prep.png',
                prepared_signature='dead',job_id='old_job'))
mod.bpy.data=SimpleNamespace(scenes=[scene])
a._AUTO_PREP_REQUEST=(123,{'image':'old.png'})
a._clear_session_images()
assert scene.tiiny_settings.image=='' and scene.tiiny_settings.prepared_image=='' and a._AUTO_PREP_REQUEST is None
print('PASS: exported Hunyuan+TRELLIS schemas, quality presets, typed anyOf, stable dirs, shared model selector, no auto old image')
