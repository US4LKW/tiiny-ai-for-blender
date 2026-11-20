"""Regression checks for v0.3.6 narrow statuses, preview tooltips and management controls."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time

sp = importlib.util.spec_from_file_location('v036_base', Path(__file__).with_name('test_offline.py'))
mod = importlib.util.module_from_spec(sp)
sys.modules['v036_base'] = mod
sp.loader.exec_module(mod)
a = sys.modules['addon']
a._JOBS.clear()  # Baseline transport tests leave simulated imports queued.

# The raw messages remain available, but every sidebar job line is concise.
examples = {
    ('shape', 'shape: Shape diffusion step\n13/50'): 'Shape diffusion 13/50',
    ('shape', 'shape: Volume decoding step\n96/887'): 'Decode volume 96/887',
    ('shape', 'shape: Volume refinement step 46/507'): 'Refine volume 46/507',
    ('texture', 'texture: Preparing internal paint conditions'): 'Preparing PBR',
    ('texture', 'texture: Paint diffusion step\n1/15'): 'PBR diffusion 1/15',
    ('export', 'export: Projecting material and exporting GLB'): 'Exporting GLB',
}
for (stage, message), expected in examples.items():
    job = {'stage': stage, 'message': message}
    assert a._compact_job_message(job) == expected
    assert len(a._compact_job_message(job)) <= 24
    assert '\n' not in a._compact_job_message(job)
    assert message == job['message'], 'Full remote status must be retained'
assert 'Tiiny status:' in a.TIINY_OT_CopyJobMessage.description(None, SimpleNamespace(message='shape: volume step'))

class Layout:
    def __init__(self):
        self.labels = []
        self.ops = []
        self.props = []
        self.bars = []
        self.previews = []
        self.enabled = True
    def row(self, *args, **kwargs): return self
    def column(self, *args, **kwargs): return self
    def box(self, *args, **kwargs): return self
    def label(self, *, text='', icon='NONE'): self.labels.append(str(text))
    def operator(self, name, *args, **kwargs):
        self.ops.append((name, dict(kwargs)))
        return SimpleNamespace()
    def prop(self, owner, name, *args, **kwargs): self.props.append(name)
    def progress(self, **kwargs): self.bars.append(kwargs)
    def template_icon(self, icon_id, scale): self.previews.append(('legacy', icon_id))
    def template_icon_view(self, obj, prop, **kwargs): self.previews.append(('native', prop, kwargs))
    def separator(self): pass

with tempfile.TemporaryDirectory() as tdir:
    root = Path(tdir)
    source = root / 'A long filename for reference image.png'
    source.write_bytes(b'fake bytes for a thumbnail that only needs to exist')
    pref = SimpleNamespace(
        tiiny_api_url='http://tiinyhost.local', tiiny_api_key='test',
        tiiny_model=a.MODELS[0][0], input_dir=str(root), output_dir=str(root),
        use_local_image_tools=True,
    )
    props = SimpleNamespace(
        image=str(source), prepared_image='', prepared_signature='', original_preview=None,
        auto_prepare=True, remove_bg=True, segment_model='isnet-general-use', smart_crop=True,
        canvas='AUTO', occupancy=.85, upscale=True, texture=True, quality='STANDARD',
        seed=42, faces=0, controls=[], job_id='', trellis_postprocess='OFF',
        trellis_overrides=False, hunyuan_overrides=False, trellis_custom_base='NATIVE',
        hunyuan_custom_base='NATIVE', save_stage_previews=False, show_request_preview=False,
        trellis_quality='STANDARD', hunyuan_quality='STANDARD',
    )
    scene = SimpleNamespace(tiiny_settings=props)
    context = SimpleNamespace(scene=scene, preferences=SimpleNamespace(addons={'addon':SimpleNamespace(preferences=pref)}))
    a._IMAGE_SELECTIONS[a._scene_token(scene)] = str(source)
    initial_ready = a._setup_ready
    initial_progress = a._setup_in_progress
    initial_install = a._prep_install_status
    try:
        a._setup_ready = lambda: False
        a._setup_in_progress = lambda: True
        a._prep_install_status = lambda: dict(python=False,rembg=False,weights=False,validated=False,log=root/'nothing.log')
        a._status_set('setup', state='working', phase=5, started_at=time.monotonic(), message='Checking ISNet')
        sidebar = Layout()
        a.TIINY_PT_Main.draw(SimpleNamespace(layout=sidebar),context)
        names = [name for name, _ in sidebar.ops]
        assert 'tiiny.select_image' not in names, names
        assert 'tiiny.clear_image' not in names
        assert 'tiiny.prepare_image' not in names
        assert 'tiiny.refresh_thumbnails' not in names
        assert 'tiiny.generate_3d' not in names
        assert not any(name in sidebar.props for name in ('auto_prepare','remove_bg','canvas'))
        assert not sidebar.previews
        assert len(sidebar.bars)==1,sidebar.bars
        assert sidebar.bars[0]['factor'] < 1
        # Setup must never hide Stop for a process-wide job in another scene.
        a._JOBS['setup-active-job'] = {'state': 'running', 'stage': 'shape', 'progress': 25}
        active_sidebar = Layout()
        a.TIINY_PT_Main.draw(SimpleNamespace(layout=active_sidebar), context)
        assert 'tiiny.cancel_3d' in [name for name, _ in active_sidebar.ops]
        assert 'tiiny.select_image' not in [name for name, _ in active_sidebar.ops]
        a._JOBS.clear()
        # Regressed maintenance operations must exist even during installation.
        ppanel = object.__new__(a.TIINY_Preferences)
        for key, val in vars(pref).items(): setattr(ppanel,key,val)
        panel = Layout(); ppanel.layout=panel; ppanel.draw(context)
        names = [name for name,_ in panel.ops]
        assert 'tiiny.install_tools' in names and 'tiiny.remove_tools' in names
        assert 'tiiny.clean_uninstall' in names
        # Same actions must be shown when setup is complete and the progress bar is hidden.
        a._setup_ready = lambda: True
        a._setup_in_progress = lambda: False
        a._prep_install_status = lambda: dict(python=True,rembg=True,weights=True,validated=True,log=root/'none.log')
        a._status_set('setup',state='ok',phase=6,message='Installed')
        panel = Layout();ppanel.layout=panel;ppanel.draw(context)
        names = [name for name,_ in panel.ops]
        assert 'tiiny.install_tools' in names and 'tiiny.remove_tools' in names
        assert 'tiiny.clean_uninstall' in names
        assert any('Installed and cached' in label for label in panel.labels)
        assert not panel.bars
        # Image controls return when tools are ready.
        sidebar = Layout()
        a.TIINY_PT_Main.draw(SimpleNamespace(layout=sidebar),context)
        names=[name for name,_ in sidebar.ops]
        assert 'tiiny.select_image' in names and 'tiiny.prepare_image' in names
        assert 'tiiny.generate_3d' in names
        # Passive large thumbnail without a popup. Full-path hover on adjacent icon.
        preview = Layout()
        a._draw_image_preview(preview,str(source),'Original','original',context)
        assert ('legacy', 101) in preview.previews
        assert not any(item[0] == 'native' for item in preview.previews)
        assert source.name not in preview.labels
        assert any(name == 'tiiny.copy_image_path' for name, _ in preview.ops)
        assert str(source.resolve()) in a.TIINY_OT_CopyImagePath.description(
            context, SimpleNamespace(filepath=str(source.resolve())))
        # Hidden local tools do not remove clean uninstall actions, and restore direct-mode image selection.
        pref.use_local_image_tools=False
        panel=Layout();ppanel.use_local_image_tools=False;ppanel.layout=panel;ppanel.draw(context)
        names=[name for name,_ in panel.ops]
        assert 'tiiny.clean_uninstall' in names and 'tiiny.remove_tools' in names
        sidebar=Layout();a.TIINY_PT_Main.draw(SimpleNamespace(layout=sidebar),context)
        names=[name for name,_ in sidebar.ops]
        assert 'tiiny.select_image' in names and 'tiiny.prepare_image' not in names
        assert 'tiiny.generate_3d' in names
        # Complete task message is available on hover/click, while status text stays short.
        pref.use_local_image_tools=True
        props.job_id='live-task'
        a._JOBS['live-task']={'state':'running','stage':'shape','progress':10,
                              'message':'shape: Shape diffusion step\n13/50'}
        sidebar=Layout();a.TIINY_PT_Main.draw(SimpleNamespace(layout=sidebar),context)
        buttons=[kwargs for name,kwargs in sidebar.ops if name=='tiiny.copy_job_message']
        assert len(buttons)==1 and buttons[0]['text']=='Shape diffusion 13/50',buttons
    finally:
        a._setup_ready = initial_ready
        a._setup_in_progress = initial_progress
        a._prep_install_status = initial_install
        a._IMAGE_SELECTIONS.clear()
        a._JOBS.clear()
        a._status_set('setup',state='not_ready',phase=0,message='')
print('PASS: v0.3.6 quality-preserving UI fixes, setup gating, maintenance actions, image-path tooltips and short job statuses')
