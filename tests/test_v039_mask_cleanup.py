"""Focused mask-cleanup behavior tests, with no AI download or Tiiny calls.

Fixtures encode meaningful foreground/detail expectations independently of the
cleanup implementation. Comparisons occur before crop/resampling, which would
otherwise prevent pixel-for-pixel preservation checks.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

from mask_cleanup_fixtures import evaluate, fixtures, image_from_alpha


SOURCE = Path(__file__).resolve().parents[1] / 'tiiny_ai_for_blender' / '__init__.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
constants = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id in {
            '_MASK_CLEANUP_SCRIPT', '_IMAGE_PREP_SCRIPT', '_IMAGE_PREP_REVISION'
        } for target in node.targets
    ):
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), constants)
assert '_MASK_CLEANUP_SCRIPT' in constants, 'Mask helper must be testable independently.'
helper = {}
exec(constants['_MASK_CLEANUP_SCRIPT'], helper)
clean = helper['clean_soft_mask']
cases = {case.name: case for case in fixtures()}

for case in cases.values():
    result, report = clean(Image.fromarray(case.rgba[:, :, 3], 'L'))
    assert isinstance(result, Image.Image) and result.mode == 'L'
    assert result.size == (case.rgba.shape[1], case.rgba.shape[0])
    assert isinstance(report, dict)
    output = case.rgba.copy()
    output[:, :, 3] = np.asarray(result)
    measurements = evaluate(case, output)
    assert measurements['alpha_changed_in_preserve_region'] == 0, measurements
    assert measurements['nonzero_alpha_in_clear_region'] == 0, measurements
    assert measurements['pixels_with_increased_alpha'] == 0, measurements
print('PASS: empty/opaque/translucent masks, thin opaque and weak hair, multiple parts, real holes, broad weak shadow')

# Repeated cleanup must not progressively damage a mask on retries.
case = cases['thin_detail_and_shadow']
first, _ = clean(Image.fromarray(case.rgba[:, :, 3], 'L'))
second, _ = clean(first)
assert np.array_equal(first, second), 'Cleanup must be idempotent.'
print('PASS: repeated mask cleanup does not progressively erode the result')

# Reusing the same public add-on version must not reuse an obsolete mask.
signature_namespace = {'Path': Path, 'json': json, 'hashlib': hashlib,
                       '_IMAGE_PREP_REVISION': constants['_IMAGE_PREP_REVISION']}
signature_node = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == '_prep_signature')
exec(compile(ast.Module(body=[signature_node], type_ignores=[]), str(SOURCE), 'exec'),
     signature_namespace)
signature = signature_namespace['_prep_signature']
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    path = root / 'cache_input.png'
    Image.fromarray(cases['thin_detail_and_shadow'].rgba, 'RGBA').save(path)
    settings = {'image': str(path), 'model': 'microsoft/TRELLIS.2-4B',
                'remove_bg': True, 'segment_model': 'isnet-general-use',
                'canvas': 'AUTO', 'occupancy': .85, 'smart_crop': True,
                'upscale': True, 'output_dir': str(root)}
    default_signature = signature(settings)
    assert signature(settings) == default_signature
    assert signature(dict(settings, clean_mask=True, clean_existing_alpha=False)) == default_signature
    assert signature(dict(settings, clean_mask=False)) != default_signature
    assert signature(dict(settings, clean_existing_alpha=True)) != default_signature
    signature_namespace['_IMAGE_PREP_REVISION'] = 'different-algorithm-revision-for-test'
    assert signature(settings) != default_signature
print('PASS: cleanup options and algorithm revision invalidate prepared-image cache without a version bump')


def call_script(source, output, options, env, crop=False):
    command = [sys.executable, '-c', constants['_IMAGE_PREP_SCRIPT'],
               '--source', str(source), '--out', str(output),
               '--canvas', '512', '--occupancy', '1.0']
    if not crop:
        command.append('--no-crop')
    command += list(options)
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr or result.stdout
    return (np.asarray(Image.open(output).convert('RGBA')),
            json.loads(output.with_suffix('.prep.json').read_text(encoding='utf-8')))


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    backend = root / 'mock_backend'
    backend.mkdir()
    (backend / 'rembg.py').write_text('''
import os
from PIL import Image
def new_session(model):
    return model
def remove(image, session=None, only_mask=False, **kwargs):
    assert only_mask is True, 'Segmentation must request a mask without replacing source RGB.'
    return Image.open(os.environ['TIINY_TEST_MASK']).convert('L')
''', encoding='utf-8')
    env = dict(os.environ)
    env['PYTHONPATH'] = str(backend)
    source_rgba = cases['thin_detail_and_shadow'].rgba
    mask = root / 'source_mask.png'
    Image.fromarray(source_rgba[:, :, 3], 'L').save(mask)
    env['TIINY_TEST_MASK'] = str(mask)
    source = root / 'opaque_source.png'
    Image.fromarray(source_rgba[:, :, :3], 'RGB').save(source)

    cleaned, report = call_script(source, root / 'cleaned.png', ['--remove-bg', '--with-rembg'], env)
    measurements = evaluate(cases['thin_detail_and_shadow'], cleaned)
    assert measurements['alpha_changed_in_preserve_region'] == 0, measurements
    assert measurements['nonzero_alpha_in_clear_region'] == 0, measurements
    assert measurements['recolored_retained_pixels'] == 0, measurements
    assert np.all(cleaned[cleaned[:, :, 3] == 0, :3] == 0), 'Generated transparent RGB must be clean.'
    assert report['segmentation_applied'] is True
    assert report.get('prep_revision') == constants['_IMAGE_PREP_REVISION'], report
    saved_mask = np.asarray(Image.open(root / report['mask']))
    assert np.array_equal(saved_mask, cleaned[:, :, 3]), 'Saved mask must equal prepared alpha.'

    uncleaned, _ = call_script(source, root / 'uncleaned.png',
                              ['--remove-bg', '--with-rembg', '--no-mask-cleanup'], env)
    assert np.array_equal(uncleaned[:, :, 3], source_rgba[:, :, 3])
    visible = source_rgba[:, :, 3] > 0
    assert np.array_equal(uncleaned[:, :, :3][visible], source_rgba[:, :, :3][visible])

    # A user-provided PNG mask is intentionally authoritative by default.
    supplied = root / 'supplied_rgba.png'
    Image.fromarray(source_rgba, 'RGBA').save(supplied)
    preserved, report = call_script(supplied, root / 'preserved.png', ['--remove-bg'], env)
    assert report['already_transparent'] is True and report['segmentation_applied'] is False
    assert np.array_equal(preserved[:, :, 3], source_rgba[:, :, 3])
    assert np.array_equal(preserved[:, :, :3][visible], source_rgba[:, :, :3][visible])

    explicit, report = call_script(supplied, root / 'explicit.png',
                                  ['--remove-bg', '--clean-existing-alpha'], env)
    measurements = evaluate(cases['thin_detail_and_shadow'], explicit)
    assert measurements['nonzero_alpha_in_clear_region'] == 0, measurements
    assert measurements['alpha_changed_in_preserve_region'] == 0, measurements
    assert measurements['recolored_retained_pixels'] == 0, measurements
    assert report['segmentation_applied'] is False

    # Crop must preserve a strand that cleanup deliberately kept, even when
    # cleanup did not need to remove anything and reports applied=False.
    strand_mask = Image.new('L', (120, 120), 0)
    drawing = ImageDraw.Draw(strand_mask)
    drawing.rectangle((30, 50, 90, 95), fill=255)
    drawing.line((60, 14, 60, 50), fill=16, width=1)
    strand_rgba = image_from_alpha(np.asarray(strand_mask))
    strand_source = root / 'strand_source.png'
    Image.fromarray(strand_rgba[:, :, :3], 'RGB').save(strand_source)
    strand_mask.save(mask)
    cropped, report = call_script(strand_source, root / 'strand_cropped.png',
                                  ['--remove-bg', '--with-rembg'], env, crop=True)
    assert report['mask_cleanup']['applied'] is False, report['mask_cleanup']
    assert report['mask_cleanup']['status'] == 'unchanged', report['mask_cleanup']
    assert report['crop_alpha_threshold'] == 0, report
    x0, y0, x1, y1 = report['object_bbox']
    assert y0 <= 14 and y1 >= 96, report['object_bbox']
    assert x0 <= 30 and x1 >= 91, report['object_bbox']
    # Locate a point near the top of the retained strand after the real resize
    # and centering steps, using the report's actual dimensions.
    object_width, object_height = report['object_size']
    canvas_width, canvas_height = report['canvas']
    probe_x = round((canvas_width-object_width)//2 + (60.5-x0)*object_width/(x1-x0)-.5)
    probe_y = round((canvas_height-object_height)//2 + (25.5-y0)*object_height/(y1-y0)-.5)
    saved_alpha = np.asarray(Image.open(root / report['mask']))
    assert np.array_equal(saved_alpha, cropped[:, :, 3])
    assert 0 < int(saved_alpha[probe_y, probe_x]) < 64, (probe_x, probe_y, report)

    # An entirely soft supplied mask uses the uncertainty fallback. Cropping
    # must respect that decision instead of turning alpha16 into an empty box.
    translucent_mask = Image.new('L', (120, 120), 0)
    ImageDraw.Draw(translucent_mask).ellipse((20, 15, 99, 104), fill=16)
    translucent_source = root / 'translucent_source.png'
    Image.fromarray(image_from_alpha(np.asarray(translucent_mask)), 'RGBA').save(translucent_source)
    translucent, report = call_script(translucent_source, root / 'translucent_cropped.png',
                                      ['--remove-bg', '--clean-existing-alpha'], env, crop=True)
    assert report['mask_cleanup']['applied'] is False
    assert report['crop_alpha_threshold'] == 0
    x0, y0, x1, y1 = report['object_bbox']
    assert x0 <= 20 and y0 <= 15 and x1 >= 100 and y1 >= 105, report['object_bbox']
    assert np.count_nonzero(translucent[:, :, 3]) > 0
    assert int(translucent[:, :, 3].max()) < 64
print('PASS: generated mask cleanup, source RGB preservation, mask file, cleanup opt-out, existing alpha opt-in')
print('PASS: real crop/resize preserves retained alpha16 hair and uncertain translucent masks')
