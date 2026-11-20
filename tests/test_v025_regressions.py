"""v0.2.5 UX and safety regression tests, no live Blender/Tiiny required."""
import importlib.util,sys,json,tempfile
from pathlib import Path
from types import SimpleNamespace
sp=importlib.util.spec_from_file_location('offline',Path(__file__).with_name('test_offline.py'))
m=importlib.util.module_from_spec(sp);sys.modules['offline']=m;sp.loader.exec_module(m)
a=sys.modules['addon']
base=Path(__file__).parent
caps=json.loads((base/'fixtures'/'tiiny_capabilities_trellis2.json').read_text())
assert caps['stage_specs']['simplify']['params']['project_geometry']['default'] is None
# 1. Resetting the add-on and opening an old .blend cannot authorize a persisted image.
with tempfile.TemporaryDirectory() as td:
    f=Path(td)/'duck.png';f.write_bytes(b'PNGTEST')
    p=SimpleNamespace(image=str(f),prepared_image='stale.png',prepared_signature='stale',
        original_preview=None,prepared_preview=None,job_id='old',auto_prepare=True,texture=True,
        quality='STANDARD',seed=-1,faces=0,controls=[],remove_bg=False,segment_model='isnet-general-use',
        smart_crop=True,canvas='AUTO',occupancy=.85,upscale=True)
    pr=SimpleNamespace(tiiny_api_url='http://tiinyhost.local',tiiny_api_key='secret',
        tiiny_model=a.MODELS[0][0],input_dir=td,output_dir=td)
    scene=SimpleNamespace(tiiny_settings=p)
    ctx=SimpleNamespace(scene=scene,preferences=SimpleNamespace(addons={'addon':SimpleNamespace(preferences=pr)}))
    assert a._accepted_image(ctx)==''
    assert a._settings_snapshot(ctx)['image']==''
    a._queue_auto_prepare(ctx)
    assert a._AUTO_PREP_REQUEST is None
    op=a.TIINY_OT_SelectImage(); op.filepath=str(f)
    assert op.execute(ctx)=={'FINISHED'}
    assert a._accepted_image(ctx)==str(f)
    assert a._settings_snapshot(ctx)['image']==str(f)
    assert a._AUTO_PREP_REQUEST is not None
    assert a.TIINY_OT_ClearImage().execute(ctx)=={'FINISHED'}
    assert a._accepted_image(ctx)==''
    a._clear_session_images()  # no disk mutations
    assert f.exists()
# 2. Nullable bool must be tri-state, no double checkbox required in UI.
for selection,expected in [('TRUE',True),('FALSE',False)]:
    entry=SimpleNamespace(datatype='bool',value_bool_choice=selection,
                          min_json='',max_json='',param_name='project_geometry')
    assert a._cast_custom(entry) is expected
entries=[SimpleNamespace(model_id='m',param_name='project_geometry',stage='simplify',
                         datatype='bool',enabled=False,value_bool_choice='DEFAULT',
                         min_json='',max_json='',value_bool=False)]
props=SimpleNamespace(controls=entries)
assert a._custom_snapshot(props,'m')==[]
entries[0].value_bool_choice='FALSE'
assert a._custom_snapshot(props,'m')==[{'stage':'simplify','param':'project_geometry','enabled':True,'value':False}]
# 3. Both presets use actual quality enums, never forced 8192 texture maps.
assert a._global_preset(caps,'MAXIMUM')['output_precision']=='high'
assert a._global_preset(caps,'DRAFT')['inference_quality']=='fast'
assert all('texture_size' not in a._preset_stage_params(caps,mode,'export') for mode in ('DRAFT','MAXIMUM'))
print('PASS: stale source blocked; explicit file selection and clear; boolean tri-state; quality remains capabilities-based')
