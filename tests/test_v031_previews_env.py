"""Regression: stable local environment and refreshed Blender thumbnail after folder replacement."""
import importlib.util
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image
sp=importlib.util.spec_from_file_location('testdeps', Path(__file__).with_name('test_offline.py'))
m=importlib.util.module_from_spec(sp)
sys.modules['testdeps']=m
sp.loader.exec_module(m)
a=sys.modules['addon']

# The image prepared by user's test contains a real alpha channel and usable data.
with TemporaryDirectory() as temp:
    root=Path(temp)
    image=root/'new.png'
    Image.new('RGBA',(40,40),(30,50,160,255)).save(image)
    first=a._file_thumbnail('prepared',str(image))
    key1=a._THUMBNAIL_NAMES['prepared']
    assert first.icon_id > 0
    a._clear_thumbnail('prepared')
    assert key1 not in a._THUMBNAILS
    # The output directory has been moved/deleted and re-created.
    image.unlink()
    assert a._file_thumbnail('prepared',str(image)) is None
    Image.new('RGBA',(42,42),(25,200,60,255)).save(image)
    second=a._file_thumbnail('prepared',str(image))
    key2=a._THUMBNAIL_NAMES['prepared']
    assert second.icon_id > 0 and key1 != key2
    # Refresh operates strictly on thumbnails, never background processing.
    assert a.TIINY_OT_RefreshThumbnails.bl_idname=='tiiny.refresh_thumbnails'
print('PASS: replaced preview gets a new icon key and can be reloaded without running rembg')

with TemporaryDirectory() as temp:
    root=Path(temp)
    envdir=root/'env'
    interp=envdir/'bin'/'python'
    oldpath=a._image_prep_runtime
    olduv=a._uv_executable
    oldrun=a._run_prep_command
    a._image_prep_runtime=lambda: (envdir,interp)
    a._uv_executable=lambda: 'uv-stub'
    calls=[]
    def fake_run(cmd,timeout,explanation):
        calls.append(list(cmd))
        if cmd[1]=='venv':
            interp.parent.mkdir(parents=True,exist_ok=True)
            interp.touch()
    a._run_prep_command=fake_run
    try:
        got,is_rembg=a._ensure_image_prep_python(need_rembg=False)
        assert got==interp and not is_rembg
        assert [c[1] for c in calls] == ['venv','pip']
        got,is_rembg=a._ensure_image_prep_python(need_rembg=True)
        assert got==interp and is_rembg
        assert [c[1] for c in calls] == ['venv','pip','pip']
        for x in range(4):
            got,is_rembg=a._ensure_image_prep_python(need_rembg=True)
            assert is_rembg
        assert len(calls)==3,'uv must never be run again after environment is configured'
    finally:
        a._image_prep_runtime=oldpath
        a._uv_executable=olduv
        a._run_prep_command=oldrun
print('PASS: one-time local Python/Pillow/rembg installation; later sessions run with persistent interpreter')
