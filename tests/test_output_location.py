"""Check _prepare_image writes to the selected output, not the old default."""
import importlib.util, sys, json, tempfile, os
from pathlib import Path
from PIL import Image
from types import SimpleNamespace
# Load mocked Blender and add-on
sp=importlib.util.spec_from_file_location('smoke',Path(__file__).with_name('test_offline.py'))
m=importlib.util.module_from_spec(sp);sys.modules['smoke']=m;sp.loader.exec_module(m)
a=sys.modules['addon']
with tempfile.TemporaryDirectory() as work:
    root=Path(work)
    photo=root/'source.png'
    Image.new('RGBA',(150,100),(220,50,90,180)).save(photo)
    # The persistent image-prep environment is mocked with the existing test Python.
    old=a._ensure_image_prep_python
    a._ensure_image_prep_python=lambda need_rembg=False,message_callback=None,stage_callback=None: (Path(sys.executable), False)
    base={'image':str(photo),'model':'Tencent/Hunyuan3d-2.1','remove_bg':True,
          'canvas':'AUTO','segment_model':'isnet-general-use','occupancy':.85,
          'smart_crop':True,'upscale':True}
    try:
        first={**base,'output_dir':str(root/'chosenA')}
        path,sig,report=a._prepare_image(first)
        assert path.parent==root/'chosenA'/'prepared',path
        assert path.is_file() and report['already_transparent']
        second={**base,'output_dir':str(root/'chosenB')}
        path2,sig2,report2=a._prepare_image(second)
        assert path2.parent==root/'chosenB'/'prepared',path2
        assert path!=path2 and sig!=sig2
        assert not (root/'Documents').exists()
        assert photo.read_bytes()==(root/'source.png').read_bytes()
        assert path2.with_suffix('.prep.json').is_file()
        print('PASS: actual image pipeline writes prepared files only to chosen output folders; separate cache ids')
    finally:
        a._ensure_image_prep_python=old
