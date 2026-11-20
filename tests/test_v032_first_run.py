"""Regression: first-use setup, progress markers, local mask and non-misleading preview status."""
import importlib.util
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from PIL import Image

spec = importlib.util.spec_from_file_location('v032_dependencies', Path(__file__).with_name('test_offline.py'))
mod = importlib.util.module_from_spec(spec)
sys.modules['v032_dependencies'] = mod
spec.loader.exec_module(mod)
addon = sys.modules['addon']

with TemporaryDirectory() as temp:
    root = Path(temp)
    # Check no installation is performed for an image with existing alpha.
    source = root / 'source.png'
    dest = root / 'prepared.png'
    photo = Image.new('RGBA', (80, 70), (0, 0, 0, 0))
    photo.putpixel((40, 30), (200, 100, 10, 255))
    photo.save(source)
    stages = []
    args = [sys.executable, '-c', addon._IMAGE_PREP_SCRIPT,
            '--source', str(source), '--out', str(dest), '--canvas', '512',
            '--occupancy', '.85', '--remove-bg']
    result = addon._run_image_prep_process(args, 40, stage_callback=lambda phase, msg: stages.append((phase, msg)))
    assert result.returncode == 0, result.stderr
    assert dest.is_file() and dest.with_suffix('.prep.json').is_file()
    assert dest.with_name('prepared_mask.png').is_file()
    assert any(phase == 6 for phase, msg in stages), stages
    assert not any(phase == 4 for phase, msg in stages), 'Existing alpha must not trigger AI downloads'

    # An opaque reference first asks for rembg; that is expected, not a broken preview.
    opaque = root / 'opaque.jpg'
    Image.new('RGB', (80, 70), (200, 150, 10)).save(opaque)
    failed = addon._run_image_prep_process(
        [sys.executable, '-c', addon._IMAGE_PREP_SCRIPT,
         '--source', str(opaque), '--out', str(root / 'pending.png'),
         '--canvas', '512', '--occupancy', '.85', '--remove-bg'], 40)
    assert failed.returncode == 42 and 'TIINY_NEED_REMBG' in failed.stderr

    # Streaming is used for stages that can be long. It is not an invented download percentage.
    stream = "print('TIINY_PREP_STAGE\\tMODEL\\tLoading model',flush=True);" \
             "print('TIINY_PREP_STAGE\\tMASK\\tComputing mask',flush=True);" \
             "print('TIINY_PREP_STAGE\\tSAVE\\tSaving PNG',flush=True)"
    events = []
    success = addon._run_image_prep_process([sys.executable, '-c', stream], 10,
                                             stage_callback=lambda phase, msg: events.append(phase))
    assert success.returncode == 0 and events == [4, 5, 6], events

    # Simulate a fresh installation: Python/Pillow and rembg are each set up once.
    envdir = root / 'env'
    interpreter = envdir / 'bin' / 'python'
    original = addon._image_prep_runtime, addon._uv_executable, addon._run_prep_command
    addon._image_prep_runtime = lambda: (envdir, interpreter)
    addon._uv_executable = lambda: 'uv-stub'
    operations = []
    def fake_install(command, timeout, explanation):
        operations.append(explanation)
        if 'venv' in command:
            interpreter.parent.mkdir(parents=True, exist_ok=True)
            interpreter.touch()
    addon._run_prep_command = fake_install
    try:
        stages = []
        addon._ensure_image_prep_python(need_rembg=False,
                                       stage_callback=lambda phase, text: stages.append(phase))
        assert len(operations) == 2 and 2 in stages and (envdir / '.tiiny-pillow-ready').is_file()
        addon._ensure_image_prep_python(need_rembg=True,
                                       stage_callback=lambda phase, text: stages.append(phase))
        assert len(operations) == 3 and 3 in stages and (envdir / '.tiiny-rembg-ready').is_file()
        addon._ensure_image_prep_python(need_rembg=True)
        assert len(operations) == 3, 'Packages must not be reinstalled once marked ready'
        assert (envdir.parent / 'image-prep-setup.log').is_file()
    finally:
        addon._image_prep_runtime, addon._uv_executable, addon._run_prep_command = original

print('PASS: first-use stages and expected dependency signaling; installed tools reused; no forced segmentation of transparent PNG')
