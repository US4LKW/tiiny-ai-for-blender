"""Offline image-preparation tests: no Tiiny, no Blender, no PyPI downloads."""
import sys, os, json, subprocess, tempfile, importlib.util, types
from pathlib import Path
from PIL import Image, ImageDraw

# Stub minimum Blender environment.
bpy = types.ModuleType('bpy')
class FakeTypes:
    class PropertyGroup: pass
    class AddonPreferences: pass
    class Operator: pass
    class Panel: pass
    class Scene: pass
    class Image: pass
bpy.types=FakeTypes
props=types.ModuleType('bpy.props')
for n in ['BoolProperty','CollectionProperty','EnumProperty','FloatProperty','IntProperty','PointerProperty','StringProperty']:
    setattr(props, n, lambda *args,**kwargs: None)
bpy.props=props
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
bpy.app=types.SimpleNamespace(timers=types.SimpleNamespace(is_registered=lambda x:False,
    register=lambda *a,**kw:None,unregister=lambda *a,**kw:None))
bpy.path=types.SimpleNamespace(abspath=lambda p:p)
sys.modules['bpy']=bpy
sys.modules['bpy.props']=props
spec=importlib.util.spec_from_file_location('addon',Path(__file__).parent.parent / 'tiiny_ai_for_blender' / '__init__.py')
a=importlib.util.module_from_spec(spec)
sys.modules['addon']=a
spec.loader.exec_module(a)

def call(inp,out,opts=(),env=None):
    cmd=[sys.executable,'-c',a._IMAGE_PREP_SCRIPT,'--source',str(inp),'--out',str(out),
         '--canvas','512','--occupancy','0.85']+list(opts)
    return subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',env=env,timeout=60)

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    src=root / 'subject.png'
    img=Image.new('RGBA',(400,200),(0,0,0,0))
    dr=ImageDraw.Draw(img)
    dr.ellipse((270,25,360,150),fill=(210,34,20,255))
    img.save(src)
    out=root / 'prepared.png'
    res=call(src,out,['--remove-bg'])
    assert res.returncode==0, res.stderr
    assert out.is_file() and (root / 'prepared_mask.png').is_file()
    info=json.loads(out.with_suffix('.prep.json').read_text())
    assert info['already_transparent'] is True and not info['segmentation_applied']
    result=Image.open(out)
    assert result.size==(512,512)
    bbox=result.getchannel('A').getbbox()
    cx=(bbox[0]+bbox[2])/2; cy=(bbox[1]+bbox[3])/2
    assert abs(cx-256)<=3 and abs(cy-256)<=3,(cx,cy)
    assert max(bbox[2]-bbox[0],bbox[3]-bbox[1]) >= 380,bbox
    assert info['upscale_factor']>1
    # Opaque images require a background remover when enabled.
    opaque=root / 'opaque.jpg'; Image.new('RGB',(220,120),(70,20,150)).save(opaque)
    res=call(opaque,root/'pending.png',['--remove-bg'])
    assert res.returncode==42 and 'TIINY_NEED_REMBG' in res.stderr
    # Without bg removal, the output can still be centered/canvas-aligned.
    res=call(opaque,root/'unmasked.png',[])
    assert res.returncode==0,res.stderr
    assert Image.open(root/'unmasked.png').size==(512,512)
    # A fake segmentation backend verifies the segmentation and mask pathway.
    fake_dir=root / 'mock';fake_dir.mkdir()
    (fake_dir/'rembg.py').write_text('''\nfrom PIL import Image\ndef new_session(model): return model\ndef remove(img,session=None,only_mask=False):\n    img=img.convert("RGBA")\n    mask=Image.new("L",img.size,0)\n    from PIL import ImageDraw\n    ImageDraw.Draw(mask).rectangle((5,5,img.width//2,img.height-5),fill=255)\n    if only_mask:\n        return mask\n    img.putalpha(mask)\n    return img\n''')
    env={**os.environ,'PYTHONPATH':str(fake_dir)}
    res=call(opaque,root/'segmented.png',['--remove-bg','--with-rembg'],env=env)
    assert res.returncode==0, res.stderr
    info=json.loads((root/'segmented.prep.json').read_text())
    assert info['segmentation_applied'] and info['mask']
    assert (root/info['mask']).is_file()
    # Same settings+image -> stable cache identity, change option -> new cache.
    config={'image':str(src),'model':'Tencent/Hunyuan3d-2.1', 'remove_bg':True,'segment_model':'isnet-general-use',
            'canvas':'AUTO','occupancy':.85,'smart_crop':True,'upscale':True,'output_dir':str(root)}
    sig=a._prep_signature(config)
    assert a._prep_signature(config)==sig
    config['occupancy']=.75
    assert a._prep_signature(config)!=sig
print('PASS: source alpha shortcut, mask and crop, image centering, resizing, opaque warning, CPU segmenter pathway, cache')
# Mock Blender UI callbacks: selecting an image should schedule nonblocking prep.
from types import SimpleNamespace
with tempfile.TemporaryDirectory() as tmp:
    src=Path(tmp)/'img.png'; Image.new('RGB',(64,64),(128,128,128)).save(src)
    class Props:
        def __init__(self):
            self.image=str(src);self.model=a.MODELS[0][0];self.auto_prepare=True;self.remove_bg=False
            self.segment_model='isnet-general-use';self.smart_crop=True;self.canvas='AUTO'
            self.occupancy=.85;self.upscale=True;self.texture=True;self.quality='STANDARD'
            self.faces=0;self.seed=-1;self.prepared_image='';self.prepared_signature=''
            self.original_preview=None;self.prepared_preview=None;self.controls=[]
    props=Props()
    bpy.data=SimpleNamespace(images=SimpleNamespace(load=lambda name,check_existing=False:SimpleNamespace(filepath=name)))
    pref=SimpleNamespace(output_dir=tmp,input_dir=tmp,tiiny_model=a.MODELS[0][0],tiiny_api_url='http://tiinyhost.local',tiiny_api_key='dummy')
    c=SimpleNamespace(scene=SimpleNamespace(tiiny_settings=props),preferences=SimpleNamespace(addons={'addon':SimpleNamespace(preferences=pref)}))
    assert a._accepted_image(c)==''  # Old .blend image is NOT authorized
    a._load_source_preview(props,c)
    assert a._AUTO_PREP_REQUEST is None  # Must not auto-prepare stale photo
    a._IMAGE_SELECTIONS[a._scene_token(c.scene)] = str(src)  # User explicitly chooses it
    a._load_source_preview(props,c)
    assert a._file_thumbnail('original', str(src)).icon_id == 101
    assert a._AUTO_PREP_REQUEST is not None and a._AUTO_PREP_REQUEST[1]['image']==str(src)
    props.canvas='768';a._on_prep_option_change(props,c)
    assert props.prepared_image=='' and a._AUTO_PREP_REQUEST[1]['canvas']=='768'
print('PASS: Blender preview callbacks schedule auto preparation and invalidate stale image')

# Mock preview rendering without Blender: template_icon receives an ImagePreview icon_id.
class DrawColumn:
    def __init__(self): self.icons=[]; self.labels=[]; self.operators=[]
    def label(self, **kw): self.labels.append(kw)
    def row(self, **kw): return self
    def column(self, **kw): return self
    def template_icon(self, icon_id, scale): self.icons.append((icon_id,scale))
    def operator(self, identifier, **kw):
        target=SimpleNamespace(filepath='')
        self.operators.append((identifier, target))
        return target
class DrawRoot:
    def __init__(self): self.col=DrawColumn()
    def column(self, align=True): return self.col
with tempfile.TemporaryDirectory() as tmp:
    src=Path(tmp)/'thumb.png'
    Image.new('RGBA',(40,30),(255,10,30,255)).save(src)
    root=DrawRoot()
    a._draw_image_preview(root,str(src),'Original','original')
    assert root.col.icons and root.col.icons[0][0]==101
    assert any(identifier=='tiiny.copy_image_path' and target.filepath==str(src.resolve())
               for identifier,target in root.col.operators)
    assert not any('Preview not ready' in x.get('text','') for x in root.col.labels)
print('PASS: offline Blender file-thumbnail UI using bpy.utils.previews')
# A completed background job must be picked up on Blender main thread and
# marked ready only if the source/params still match.
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp)/'original.png'
    Image.new('RGBA',(128,128),(10,20,40,255)).save(src)
    out = Path(tmp)/'prepared'/ 'prepared_abc.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGBA',(512,512),(10,20,40,255)).save(out)
    report={'canvas':[512,512],'segmentation_applied':False,
            'already_transparent':True,'mask':None,'warning':None}
    props = Props()
    props.image=str(src)
    props.remove_bg=True
    props.prepared_image=''
    prefs=SimpleNamespace(output_dir=tmp,input_dir=tmp,tiiny_model=a.MODELS[0][0],tiiny_api_url='http://tiinyhost.local',tiiny_api_key='dummy')
    ctx=SimpleNamespace(scene=SimpleNamespace(tiiny_settings=props),preferences=SimpleNamespace(addons={'addon':SimpleNamespace(preferences=prefs)}),window_manager=None)
    bpy.context=ctx
    a._IMAGE_SELECTIONS[a._scene_token(ctx.scene)] = str(src)
    a._AUTO_PREP_REQUEST=None
    opts=a._settings_snapshot(ctx)
    signature=a._prep_signature(opts)
    a._PENDING_PREVIEW.put((str(out),signature,report))
    a._main_tick()
    assert props.prepared_image==str(out),props.prepared_image
    assert a._status_get('prep')['state']=='ok'
    assert a._status_get('prep')['report']['already_transparent']
    preview=DrawRoot()
    a._draw_image_preview(preview,props.prepared_image,'Prepared','prepared')
    assert preview.col.icons
print('PASS: preview queue applied to current image and shown with native thumbnails')
