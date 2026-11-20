"""v0.1.0 development refresh: passive thumbnails, image-path hover, packaged release."""
import importlib.util
import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import tomllib
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
fixture = importlib.util.spec_from_file_location('test_v038_fixture', Path(__file__).with_name('test_offline.py'))
module = importlib.util.module_from_spec(fixture)
sys.modules['test_v038_fixture'] = module
fixture.loader.exec_module(module)
addon = sys.modules['addon']

assert addon.TIINY_OT_CopyImagePath.bl_idname == 'tiiny.copy_image_path'
assert not hasattr(addon.TIINY_PG_Settings, 'original_thumbnail')
assert 'template_icon_view(' not in (ROOT/'tiiny_ai_for_blender/__init__.py').read_text()

class Layout:
    def __init__(self): self.labels=[];self.previews=[];self.ops=[]
    def column(self,*args,**kwargs):return self
    def row(self,*args,**kwargs):return self
    def label(self,*,text='',icon='NONE'):self.labels.append(text)
    def template_icon(self,icon_id,scale):self.previews.append((icon_id,scale))
    def operator(self,name,*args,**kwargs):
        op=SimpleNamespace(filepath='')
        self.ops.append((name,op,kwargs))
        return op

with tempfile.TemporaryDirectory() as temp:
    name='sample girl image.png'
    path=Path(temp)/name
    path.write_bytes(b'preview test dummy')
    obj=Layout()
    addon._draw_image_preview(obj,str(path),'Original','original')
    assert obj.previews == [(101,5.0)]
    assert obj.labels == ['Original'], obj.labels
    assert len(obj.ops) == 1
    identifier, props, kwargs = obj.ops[0]
    assert identifier == 'tiiny.copy_image_path'
    assert kwargs['text'] == '' and kwargs['icon']=='INFO' and kwargs['emboss'] is False
    assert props.filepath == str(path.resolve())
    tooltip=addon.TIINY_OT_CopyImagePath.description(None, props)
    assert str(path.resolve()) in tooltip and 'Click to copy path' in tooltip
    instance=addon.TIINY_OT_CopyImagePath()
    instance.filepath=props.filepath
    messages=[]
    instance.report=lambda *a:messages.append(a)
    clipboard=SimpleNamespace(clipboard='')
    assert instance.execute(SimpleNamespace(window_manager=clipboard)) == {'FINISHED'}
    assert clipboard.clipboard == props.filepath
    assert messages

manifest=tomllib.loads((ROOT/'tiiny_ai_for_blender/blender_manifest.toml').read_text('utf-8'))
assert manifest['id']=='tiiny_ai_for_blender' and manifest['version']=='0.1.0'
installer=ROOT/'releases/tiiny_ai_for_blender-0.1.0.zip'
assert installer.is_file()
with ZipFile(installer) as z:
    assert z.testzip() is None
    assert z.namelist()==['blender_manifest.toml','__init__.py','LICENSE']
    for name in z.namelist():
        original = (ROOT if name == 'LICENSE' else ROOT/'tiiny_ai_for_blender') / name
        assert hashlib.sha256(z.read(name)).digest()==hashlib.sha256(original.read_bytes()).digest()
for doc in (ROOT/'README.md', ROOT/'docs/INSTALLATION.md',ROOT/'releases/README.md'):
    assert doc.is_file()
    content=doc.read_text('utf8')
    assert 'tiiny_ai_for_blender-0.1.0.zip' in content
    assert 'Install from Disk' in content or doc.name=='README.md'

print('PASS: two passive image previews, hover tooltip + copy, no popup selector, exact installer in GitHub project')
