# Tiiny AI - local Image-to-3D Blender extension
# Inspired by the open-source Blender MCP project by Siddharth Ahuja (MIT).
# This edition does not embed an MCP server or connect to commercial model APIs.

EXTENSION_VERSION = (0, 1, 0)
DEVELOPMENT_BUILD = 'dev-0.3.9'
# Cache provenance changes independently of the public/development version.
_IMAGE_PREP_REVISION = 'mask-cleanup-1'

import base64
import copy
import hashlib
import json
import mimetypes
import math
import os
import queue
import shutil
import subprocess
import re
import struct
import threading
import time
import uuid
import io
from pathlib import Path
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

import bpy
import bpy.utils.previews
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)

MODELS = (
    ('Tencent/Hunyuan3d-2.1', 'Hunyuan3D 2.1', 'Tencent Hunyuan 3D on Pocket Lab'),
    ('microsoft/TRELLIS.2-4B', 'TRELLIS.2 4B', 'Microsoft TRELLIS 2 on Pocket Lab'),
)
STAGE_INPUTS = {
    'background': ['image'], 'shape': ['image'], 'simplify': ['mesh'],
    'texture': ['image', 'mesh'], 'export': ['material_artifact', 'mesh_glb'],
}
STAGE_FIELDS = {'material_artifact': 'material', 'mesh_glb': 'mesh'}
QUALITY_KEYS = {
    'quality', 'inference_quality', 'asset_quality', 'quality_level',
    'inference_steps', 'steps', 'num_inference_steps', 'texture_resolution',
    'texture_size', 'texture_quality', 'resolution', 'detail_level',
}
LOW_WORDS = ('draft', 'fast', 'quick', 'low', 'minimum', 'min', 'preview', 'speed')
HIGH_WORDS = ('maximum', 'max', 'high', 'highest', 'ultra', 'best', 'quality', 'fine')
QUALITY_ORDER = {
    'draft': -5, 'preview': -4, 'fast': -3, 'lowest': -3, 'low': -2,
    'minimum': -2, 'min': -2, 'standard': 0, 'default': 0, 'balanced': 0,
    'normal': 0, 'medium': 0, 'balance': 0, 'high': 2, 'quality': 2, 'best': 3,
    'ultra': 4, 'maximum': 5, 'max': 5,
}


# Only enable these optional types when *this Tiiny device* advertises
# the exact parameter name for the relevant stage. The field names come from
# Tiiny /v1/3d/capabilities; the type/reference values are sourced from the
# upstream Tencent code. They are NOT verified TiinyOS defaults or bounds.
# Preset-only requests do not include these; manual overrides are opt-in.
HUNYUAN_UPSTREAM_HINTS = {
    'shape': {
        'step': {
            'type': 'integer', 'title': 'Shape steps (Tencent reference)',
            'default': 5, 'minimum': 1, 'maximum': 20,
            'description': 'Experimental Tiiny step. Tencent API documents num_inference_steps 1..20 (default 5); Tiiny limits are not published. Override only after testing.',
        },
        'guidance_scale': {
            'type': 'number', 'title': 'Shape guidance (Tencent reference)',
            'default': 5.0, 'minimum': 0.1, 'maximum': 20.0,
            'description': 'Experimental on Tiiny. Tencent shape API documents guidance_scale 0.1..20 (default 5.0).',
        },
    },
    'texture': {
        'paint_step': {
            'type': 'integer', 'title': 'PBR painting steps (experimental)',
            'default': 50, 'minimum': 1,
            'description': 'Tiiny advertises paint_step but no bounds. Upstream Tencent PBR diffusion uses inference steps (50 by default); mapping/range on Tiiny unverified.',
        },
        'guidance_scale': {
            'type': 'number', 'title': 'PBR guidance (experimental)',
            'default': 7.5, 'minimum': 0.1,
            'description': 'Tiiny advertises texture guidance_scale, no bounds. Tencent PBR pipeline uses 7.5 by default; Tiiny mapping unverified.',
        },
    },
}


def _is_hunyuan_caps(caps):
    return isinstance(caps, dict) and 'hunyuan' in str(caps.get('model', '')).lower()


def _is_trellis_caps(caps):
    return isinstance(caps, dict) and 'trellis' in str(caps.get('model', '')).lower()


CUSTOM_BASE_ITEMS = (
    ('NATIVE', 'Server defaults', 'Omit preset quality controls; retain explicit manual overrides'),
    ('DRAFT', 'Draft', 'Start with the advertised fast generation tier'),
    ('STANDARD', 'Standard', 'Start with the Standard generation preset'),
    ('MAXIMUM', 'Maximum', 'Start with the highest advertised generation tier'),
)


def _model_property(model, suffix):
    return ('trellis_' if 'TRELLIS' in model else 'hunyuan_') + suffix


def _overrides_active(props, model):
    return props.quality == 'CUSTOM' or bool(getattr(props, _model_property(model, 'overrides'), False))


def _base_preset(settings, preset):
    base = settings.get('custom_base', 'NATIVE') if preset == 'CUSTOM' else preset
    if base not in ('NATIVE', 'STANDARD', 'DRAFT', 'MAXIMUM'):
        raise ValueError('Unknown base preset: ' + str(base))
    return base

_LOCK = threading.RLock()
_STATUS = {'connection': {}, 'model': {}}
_CAPABILITIES = {}  # Per-session cache: (url+key fingerprint, model) -> schema
_PENDING_IMPORT = queue.Queue()
_PENDING_PREVIEW = queue.Queue()
_AUTO_PREP_REQUEST = None
_JOBS = {}
_JOB_CANCEL_EVENTS = {}
_JOB_REPORTS = {}
_REPORT_LOCK = threading.RLock()
_NETWORK_SLOTS = threading.BoundedSemaphore(4)
_REMOTE_CANCEL_TASKS = set()
_POLL_INTERVAL = 2.0
_NETWORK_GRACE_SECONDS = 300
_NEXT_REFRESH = 0
_ENUM_CACHE = {}  # keep dynamic Blender EnumProperty option strings alive
_ACTIVE = True
_THUMBNAILS = None  # bpy.utils.previews.ImagePreviewCollection, owned by this add-on
_THUMBNAIL_KEYS = {}  # preview slot -> (resolved file, file size, modification time)
_THUMBNAIL_NAMES = {}  # preview slot -> unique collection key, never reuse a destroyed icon name
_THUMBNAIL_SEQUENCE = 0
_THUMBNAIL_ATTEMPTS = {}  # preview slot -> last_attempt and failed retries
_IMAGE_PREP_ENV_LOCK = threading.RLock()
_BACKGROUND_TOOLS_LOCK = threading.Lock()
_SETUP_THREAD = None
_SETUP_TOTAL_STAGES = 6
_SETUP_AUTO_SCHEDULED = False
_IMAGE_SELECTIONS = {}  # Per-scene, session-authorized source image paths


def _ui_message_lines(message, width=29, max_lines=2):
    """Word-wrap short status text without splitting normal words.

    The complete error text is retained in the diagnostic log. Blender sidebar
    labels are often narrow and do not reliably wrap their own text.
    """
    words = str(message or '').replace('\r', ' ').replace('\n', ' ').split()
    lines = []
    current = ''
    for word in words:
        if len(word) > width:
            word = word[:width - 3] + '...'
        candidate = (current + ' ' + word).strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        if len(last) + 3 <= width:
            lines[-1] = last + '...'
        else:
            # Prefer dropping a whole word rather than leaving an abrupt fragment.
            prior = last.rsplit(' ', 1)[0] if ' ' in last else last[:width - 3]
            lines[-1] = prior[:width - 3].rstrip() + '...'
    return lines


_SETUP_STEP_LABELS = {
    1: 'Checking local tools',
    2: 'Checking Python 3.12',
    3: 'Installing Pillow',
    4: 'Installing CPU packages',
    5: 'Preparing ISNet weights',
    6: 'Verifying local tools',
}


def _scene_token(scene):
    try:
        return scene.as_pointer()
    except (AttributeError, RuntimeError):
        return id(scene)


def _accepted_image(context):
    """Only accept a reference image the user selected during THIS session.

    Scene PropertyGroups can be restored from .blend data. SKIP_SAVE is not a
    reliable authorization mechanism for stored Scene properties.
    """
    scene = getattr(context, 'scene', None) if context is not None else None
    if scene is None or not hasattr(scene, 'tiiny_settings'):
        return ''
    path = str(getattr(scene.tiiny_settings, 'image', '') or '')
    return path if path and _IMAGE_SELECTIONS.get(_scene_token(scene)) == path else ''




def _thumbnail_collection():
    global _THUMBNAILS
    if _THUMBNAILS is None:
        _THUMBNAILS = bpy.utils.previews.new()
    return _THUMBNAILS


def _clear_thumbnail(slot):
    """Forget the old icon handle; file moves require a NEW Blender preview key."""
    _THUMBNAIL_KEYS.pop(slot, None)
    _THUMBNAIL_ATTEMPTS.pop(slot, None)
    key = _THUMBNAIL_NAMES.pop(slot, None)
    if key is not None and _THUMBNAILS is not None and key in _THUMBNAILS:
        try:
            del _THUMBNAILS[key]
        except (KeyError, ReferenceError, RuntimeError):
            pass


def _file_thumbnail(slot, filepath):
    """Display a PNG/JPG from disk using a fresh Blender icon after replacement.

    Blender's thumbnail cache can keep a stale handle if a prepared folder is
    moved or removed while the side panel is open. Reusing the literal name
    'prepared' after removing that thumbnail is unreliable on some versions.
    Instead, each reload gets a unique collection key and a forced file reload.
    """
    global _THUMBNAIL_SEQUENCE
    if not filepath:
        _clear_thumbnail(slot)
        return None
    path = Path(filepath)
    try:
        if not path.is_file():
            _clear_thumbnail(slot)
            return None
        stat = path.stat()
        signature = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        coll = _thumbnail_collection()
        current = _THUMBNAIL_NAMES.get(slot)
        if _THUMBNAIL_KEYS.get(slot) != signature or current not in coll:
            _clear_thumbnail(slot)
            _THUMBNAIL_SEQUENCE += 1
            key = 'tiiny_%s_%d' % (slot, _THUMBNAIL_SEQUENCE)
            preview = coll.load(key, str(path), 'IMAGE', force_reload=True)
            _THUMBNAIL_KEYS[slot] = signature
            _THUMBNAIL_NAMES[slot] = key
            _THUMBNAIL_ATTEMPTS[slot] = {'attempted_at': time.monotonic(), 'retries': 0}
            return preview
        preview = coll[current]
        # An asynchronously generated icon can initially have icon_id=0.
        # Retry a few times with a genuinely new collection key. This is only
        # a thumbnail retry; image preparation and model inference are untouched.
        trial = _THUMBNAIL_ATTEMPTS.get(slot) or {}
        if (preview.icon_id == 0 and trial.get('retries', 0) < 3
                and time.monotonic() - trial.get('attempted_at', 0) > 2.5):
            retries = trial.get('retries', 0) + 1
            _clear_thumbnail(slot)
            _THUMBNAIL_SEQUENCE += 1
            key = 'tiiny_%s_%d' % (slot, _THUMBNAIL_SEQUENCE)
            preview = coll.load(key, str(path), 'IMAGE', force_reload=True)
            _THUMBNAIL_KEYS[slot] = signature
            _THUMBNAIL_NAMES[slot] = key
            _THUMBNAIL_ATTEMPTS[slot] = {'attempted_at': time.monotonic(), 'retries': retries}
        return preview
    except (OSError, KeyError, RuntimeError, ValueError, ReferenceError):
        return None


# Preparation steps represent completed workflow phases, not elapsed-time estimates.
_PREP_TOTAL_STEPS = 7


def _prep_notice(message_callback, stage_callback, phase, message):
    if stage_callback:
        stage_callback(int(phase), message)
    if message_callback:
        message_callback(message)


def _prep_setup_log_path():
    envdir, _ = _image_prep_runtime()
    return envdir.parent / 'image-prep-setup.log'


def _prep_log(message):
    """Best-effort local diagnostics; never log source paths, API keys or prompts."""
    try:
        target = _prep_setup_log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('a', encoding='utf-8') as out:
            out.write(time.strftime('%Y-%m-%d %H:%M:%S') + ' | ' + str(message).replace('\n', ' ')[:240] + '\n')
    except (OSError, RuntimeError):
        pass


def _image_prep_home():
    """Dedicated private data directory. Never remove a shared rembg cache."""
    return _image_prep_runtime()[0].parent


def _model_cache_root():
    return _image_prep_home() / 'rembg-models'


def _image_prep_environment():
    # Support both older U2NET_HOME and modern REMBG_HOME layouts.
    cache = str(_model_cache_root())
    return {**os.environ, 'U2NET_HOME': cache, 'REMBG_HOME': cache}


def _cached_private_model(model='isnet-general-use'):
    root = _model_cache_root()
    return next((candidate for candidate in (
        root / (model + '.onnx'), root / 'models' / model / (model + '.onnx'),
    ) if candidate.is_file() and candidate.stat().st_size > 1000000), None)


def _prep_install_status(segment_model='isnet-general-use'):
    """Read-only indicators. Model existence alone never proves ONNX load success."""
    envdir, interpreter = _image_prep_runtime()
    ready = _image_prep_home() / '.tiiny-setup-complete'
    return {
        'python': interpreter.is_file() and (envdir / '.tiiny-pillow-ready').is_file(),
        'rembg': (envdir / '.tiiny-rembg-ready').is_file(),
        'weights': _cached_private_model(segment_model) is not None,
        'validated': ready.is_file(),
        'log': _prep_setup_log_path(),
    }


def _copy_shared_weights_once():
    """Reuse old downloads without ever deleting the old shared rembg data."""
    if _cached_private_model():
        return False
    model = 'isnet-general-use.onnx'
    shared = [Path.home() / '.u2net' / model,
              Path.home() / '.rembg' / 'models' / 'isnet-general-use' / model]
    for source in shared:
        try:
            if source.is_file() and source.stat().st_size > 1000000:
                root = _model_cache_root()
                root.mkdir(parents=True, exist_ok=True)
                temp = root / (model + '.copying')
                shutil.copy2(source, temp)
                temp.replace(root / model)
                return True
        except OSError:
            pass  # RemBg can download instead; no shared cache is modified.
    return False


def _setup_update(stage, message, state='working', started_at=None):
    previous = _status_get('setup')
    _status_set('setup', state=state, phase=stage, message=message,
                started_at=started_at if started_at is not None else previous.get('started_at', time.monotonic()))
    _prep_log('SETUP step %s: %s' % (stage, message))


def _setup_worker():
    """Eager, idempotent install independent of the user's image and Tiiny key."""
    started = time.monotonic()
    _setup_update(1, 'Checking local image-processing tools', started_at=started)
    try:
        with _BACKGROUND_TOOLS_LOCK:
            _setup_update(2, 'Checking Python 3.12 environment')
            _ensure_image_prep_python(need_rembg=False, setup_stage=True)
            _setup_update(4, 'Checking/installing CPU segmentation packages')
            interpreter, _ = _ensure_image_prep_python(need_rembg=True, setup_stage=True)
            _setup_update(5, 'Preparing ISNet model weights')
            if _copy_shared_weights_once():
                _prep_log('Copied already downloaded shared ISNet weights into the private add-on cache')
            # new_session downloads, verifies and loads the ONNX model (one-time check).
            script = ("from rembg import new_session; "
                      "new_session('isnet-general-use'); "
                      "print('TIINY_MODEL_READY', flush=True)")
            result = _run_image_prep_process([str(interpreter), '-c', script], 1800)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or 'No error text')[-450:].replace('\n',' ')
                raise RuntimeError('ISNet download or model validation failed: ' + detail)
            if not _cached_private_model():
                raise RuntimeError('ISNet reported success but no private ONNX weights were found')
            _setup_update(6, 'Verifying installed image-preparation tools')
            (_image_prep_home() / '.tiiny-setup-complete').write_text('ready\n', encoding='ascii')
            _setup_update(6, 'Local image tools ready (100%)', state='ok')
    except Exception as exc:
        _setup_update(0, str(exc), state='error')


def _begin_background_setup():
    global _SETUP_THREAD
    if not _ACTIVE or not _tools_enabled():
        return False
    if _SETUP_THREAD is not None and _SETUP_THREAD.is_alive():
        return False
    status = _prep_install_status()
    if status['python'] and status['rembg'] and status['weights'] and status['validated']:
        _status_set('setup', state='ok', phase=_SETUP_TOTAL_STAGES,
                    message='Local image tools ready (100%)')
        return False
    if not bool(getattr(bpy.app, 'online_access', True)):
        _status_set('setup', state='error', phase=0,
                    message='Blender Online Access is disabled. Enable it in Preferences > System and retry.')
        return False
    _status_set('setup', state='queued', phase=1,
                started_at=time.monotonic(), message='Starting local image tools installation...')
    _SETUP_THREAD = threading.Thread(target=_setup_worker, name='TiinyImageToolsSetup', daemon=True)
    _SETUP_THREAD.start()
    return True


def _tools_enabled(preferences=None):
    """Whether the user opted into local preparation. The Tiiny API is independent."""
    if preferences is None:
        try:
            preferences = bpy.context.preferences.addons[__name__].preferences
        except (AttributeError, KeyError, RuntimeError, ReferenceError):
            return True  # Preserve historical defaults when bpy context is unavailable.
    return bool(getattr(preferences, 'use_local_image_tools', True))


def _setup_in_progress():
    return (_status_get('setup').get('state') in ('queued', 'working')
            or (_SETUP_THREAD is not None and _SETUP_THREAD.is_alive()))


def _setup_ready():
    status = _prep_install_status()
    return all(status[k] for k in ('python', 'rembg', 'weights', 'validated'))


def _on_local_tools_toggle(self, context):
    """Switch modes without deleting user files, cached wheels or downloaded weights."""
    global _AUTO_PREP_REQUEST
    _AUTO_PREP_REQUEST = None
    try:
        scene = getattr(context, 'scene', None)
        if scene is not None and hasattr(scene, 'tiiny_settings'):
            _invalidate_prepared(scene.tiiny_settings)
        if _tools_enabled(self):
            _begin_background_setup()
            if scene is not None and hasattr(scene, 'tiiny_settings'):
                _queue_auto_prepare(context)
        else:
            _status_set('prep', state='not_ready', message='Direct image mode: no local processing')
            # An installer already running completes safely. The resulting tools
            # remain unused until this preference is enabled again.
    except (RuntimeError, AttributeError, KeyError, ReferenceError):
        pass


def _automatic_setup_start():
    if _ACTIVE and _tools_enabled():
        _begin_background_setup()
    return None


def _draw_local_setup(layout, compact=False):
    """Draw the shared setup progress without clipped or mid-word UI labels."""
    status = _status_get('setup')
    installed = _prep_install_status()
    state = status.get('state')
    all_present = all(installed[name] for name in ('python', 'rembg', 'weights', 'validated'))
    # Never hide an error when stale marker files remain on disk.
    if state == 'ok' and not all_present:
        state = 'missing'
    elif all_present and state not in ('working', 'queued', 'error', 'missing'):
        state = 'ok'
    if state == 'ok':
        layout.progress(factor=1.0, type='BAR', text='Tools ready: 100%')
        layout.label(text='ISNet ready (cached)', icon='CHECKMARK')
    elif state in ('working', 'queued'):
        phase = max(0, min(_SETUP_TOTAL_STAGES - 1, int(status.get('phase') or 0)))
        layout.progress(factor=min(.95, phase / _SETUP_TOTAL_STAGES),
                        type='BAR', text='Tools setup: %d/%d' % (phase, _SETUP_TOTAL_STAGES))
        layout.label(text=_SETUP_STEP_LABELS.get(phase, 'Starting local setup'), icon='TIME')
        if phase == 5:
            layout.label(text='Checking cached ISNet' if installed['weights'] and installed['validated'] else
                         'First download may take time', icon='INFO')
            layout.label(text='Download % is unavailable', icon='INFO')
        started = status.get('started_at')
        elapsed = max(0, int(time.monotonic() - started)) if isinstance(started, (float, int)) else 0
        layout.label(text='Elapsed: %d:%02d' % divmod(elapsed, 60), icon='TIME')
    elif state == 'error':
        layout.label(text='Local tools setup failed', icon='ERROR')
        for i, line in enumerate(_ui_message_lines(status.get('message') or 'See setup log')):
            layout.label(text=line, icon='INFO' if i == 0 else 'NONE')
        if compact:
            layout.label(text='See Preferences for log', icon='INFO')
    elif state == 'missing':
        layout.label(text='Tools missing; reinstalling', icon='INFO')
    else:
        layout.label(text='Local tools not installed', icon='INFO')
    if not compact:
        row = layout.row(align=True)
        retry = row.row(align=True)
        retry.enabled = state not in ('working', 'queued')
        retry.operator('tiiny.install_tools', text='Install / Retry tools', icon='FILE_REFRESH')
        reset = row.row(align=True)
        reset.enabled = state not in ('working', 'queued')
        reset.operator('tiiny.remove_tools', text='Remove local tools', icon='TRASH')
        layout.label(text='Only private tools are removed.', icon='INFO')
        layout.label(text='Images and shared caches stay.')
        clean = layout.row(align=True)
        clean.enabled = state not in ('working', 'queued')
        clean.operator('tiiny.clean_uninstall', text='Clean Uninstall (add-on + local tools)', icon='TRASH')



# Image preparation runs in a separate uv-managed Python 3.12 environment.
# This keeps Blender's own Python environment clean, avoids external APIs, and
# does not execute third-party image segmentation packages in Blender process.
_MASK_CLEANUP_SCRIPT = r'''
from collections import deque
from PIL import Image, ImageChops, ImageFilter

def clean_soft_mask(mask):
    """Remove weak background residue while protecting soft edge detail.

    This is a conservative mask heuristic, not semantic shadow detection.
    Morphology detects thin ridges only; retained alpha values are unchanged.
    No connected foreground component is discarded just because it is small.
    """
    mask = mask.convert("L")
    width, height = mask.size
    histogram = mask.histogram()
    weak_pixels = sum(histogram[1:64])
    foreground_pixels = sum(histogram[1:])
    core_pixels = sum(histogram[192:])
    radius = max(1, min(8, round(max(width, height) / 512)))
    info = {
        "algorithm": "protected-fringe-and-ridges-v1",
        "status": "unchanged", "applied": False,
        "weak_alpha_below": 64, "protected_edge_radius_px": radius,
        "weak_pixels_before": weak_pixels, "removed_pixels": 0,
        "protected_thin_pixels": 0,
        "foreground_pixels_before": foreground_pixels,
        "foreground_pixels_after": foreground_pixels,
    }
    if not foreground_pixels:
        info["status"] = "skipped_empty_mask"
        return mask, info
    if not weak_pixels:
        info["status"] = "unchanged_no_weak_alpha"
        return mask, info
    # Do not erase an entirely translucent or uncertain foreground.
    if core_pixels < max(4, round(foreground_pixels * .001)):
        info["status"] = "skipped_uncertain_foreground"
        return mask, info

    strong = mask.point(lambda value: 255 if value >= 64 else 0)
    near = strong.filter(ImageFilter.MaxFilter(2 * radius + 1)).tobytes()
    opened = mask.filter(ImageFilter.MinFilter(2 * radius + 1))
    opened = opened.filter(ImageFilter.MaxFilter(2 * radius + 1))
    contrast = ImageChops.subtract(mask, opened).tobytes()
    source = mask.tobytes()
    ridges = bytearray(len(source))
    pending = deque()
    for index, value in enumerate(source):
        difference = contrast[index]
        if 0 < value < 64 and difference >= 3 and 5 * difference >= 3 * value:
            ridges[index] = 1
            if near[index]:
                ridges[index] = 2
                pending.append(index)

    # Preserve faint narrow strands connected to any protected foreground.
    # An iterative queue avoids recursion limits on long hair or whiskers.
    while pending:
        index = pending.popleft()
        y, x = divmod(index, width)
        for ny in range(max(0, y - 1), min(height, y + 2)):
            start = ny * width
            for nx in range(max(0, x - 1), min(width, x + 2)):
                neighbor = start + nx
                if ridges[neighbor] == 1:
                    ridges[neighbor] = 2
                    pending.append(neighbor)

    result = bytearray(source)
    removed = thin = 0
    for index, value in enumerate(source):
        if 0 < value < 64 and not near[index]:
            if ridges[index] == 2:
                thin += 1
            else:
                result[index] = 0
                removed += 1
    info.update(status="cleaned" if removed else "unchanged",
                applied=bool(removed), removed_pixels=removed,
                protected_thin_pixels=thin,
                foreground_pixels_after=foreground_pixels - removed)
    return Image.frombytes("L", mask.size, bytes(result)), info
'''


_IMAGE_PREP_SCRIPT = _MASK_CLEANUP_SCRIPT + r'''
import argparse, json, os, sys
from pathlib import Path
from PIL import Image, ImageOps

def stage(name, text):
    print("TIINY_PREP_STAGE\t" + name + "\t" + text, flush=True)

p = argparse.ArgumentParser()
p.add_argument("--source", required=True)
p.add_argument("--out", required=True)
p.add_argument("--canvas", type=int, required=True)
p.add_argument("--occupancy", type=float, required=True)
p.add_argument("--remove-bg", action="store_true")
p.add_argument("--segment", default="isnet-general-use")
p.add_argument("--with-rembg", action="store_true")
p.add_argument("--no-crop", action="store_true")
p.add_argument("--no-upscale", action="store_true")
p.add_argument("--no-mask-cleanup", action="store_true")
p.add_argument("--clean-existing-alpha", action="store_true")
p.add_argument("--prep-revision", default="mask-cleanup-1")
a = p.parse_args()

src = ImageOps.exif_transpose(Image.open(a.source)).convert("RGBA")
original_size = list(src.size)
alpha = src.getchannel("A")
existing_alpha = alpha.getextrema()[0] < 250
removed = False
if a.remove_bg and not existing_alpha:
    if not a.with_rembg:
        sys.stderr.write("TIINY_NEED_REMBG\n")
        sys.exit(42)
    weights_home = Path(os.environ.get("U2NET_HOME") or (Path.home() / ".u2net"))
    weights_cached = (weights_home / (a.segment + ".onnx")).is_file() or \
        (weights_home / "models" / a.segment / (a.segment + ".onnx")).is_file()
    stage("MODEL", "Loading cached background model" if weights_cached else
          "Checking/downloading background model weights on first use")
    from rembg import remove, new_session
    session = new_session(a.segment)
    stage("MASK", "Computing foreground mask on CPU")
    # Request the mask separately. A black-composited cutout would attenuate
    # edge RGB before consumers apply the PNG alpha for a second time.
    predicted_mask = remove(src, session=session, only_mask=True).convert("L")
    if predicted_mask.size != src.size:
        raise RuntimeError("Background remover returned an unexpected mask size")
    src.putalpha(predicted_mask)
    removed = True

cleanup = {"enabled": not a.no_mask_cleanup, "applied": False,
           "status": "disabled" if a.no_mask_cleanup else "no_mask",
           "removed_pixels": 0}
mask_cleanup_ran = False
if not a.no_mask_cleanup:
    if removed or (existing_alpha and a.clean_existing_alpha):
        stage("CLEANUP", "Cleaning soft background; protecting fine edges")
        cleaned, cleanup = clean_soft_mask(src.getchannel("A"))
        mask_cleanup_ran = True
        cleanup["enabled"] = True
        src.putalpha(cleaned)
    elif existing_alpha:
        cleanup["status"] = "preserved_source_alpha"
cleanup["source"] = "segmentation" if removed else ("source_alpha" if existing_alpha else "none")

# Cleanup already decided which faint details to retain. A second alpha cutoff
# would clip protected strands, even when cleanup did not need to remove pixels.
crop_alpha_threshold = 0 if mask_cleanup_ran else 20
if a.no_crop or not (removed or existing_alpha):
    bbox = (0, 0, src.width, src.height)
else:
    mask = src.getchannel("A").point(lambda value: 255 if value > crop_alpha_threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise RuntimeError("Background removal returned an empty mask")
    # Add 2% margins so fine outlines are not clipped.
    x0, y0, x1, y1 = bbox
    margin = max(2, round(max(x1-x0, y1-y0)*.02))
    bbox = (max(0,x0-margin), max(0,y0-margin),
            min(src.width,x1+margin), min(src.height,y1+margin))
src = src.crop(bbox)

fit = max(8, round(a.canvas*a.occupancy))
scale = fit / max(src.size)
if a.no_upscale:
    scale = min(1., scale)
size = (max(1, round(src.width*scale)), max(1,round(src.height*scale)))
if size != src.size:
    src = src.resize(size, Image.Resampling.LANCZOS)
background = (0,0,0,0) if (existing_alpha or removed) else (255,255,255,255)
canvas = Image.new("RGBA",(a.canvas,a.canvas),background)
x=(a.canvas-src.width)//2
y=(a.canvas-src.height)//2
canvas.alpha_composite(src,(x,y))
# Keep ordinary straight-alpha PNG colors. Only fully invisible RGB is cleared.
invisible = canvas.getchannel("A").point(lambda value: 255 if value == 0 else 0)
canvas.paste((0,0,0,0), mask=invisible)
stage("SAVE", "Centering, resizing and saving prepared PNG")
dest=Path(a.out)
dest.parent.mkdir(parents=True,exist_ok=True)
canvas.save(dest,format="PNG",optimize=True)
mask_path = None
if existing_alpha or removed:
    mask_path = dest.with_name(dest.stem+"_mask.png")
    canvas.getchannel("A").save(mask_path,format="PNG")
report = {
  "prep_revision": a.prep_revision, "mask_cleanup": cleanup,
  "alpha_encoding": "straight",
  "crop_alpha_threshold": crop_alpha_threshold,
  "original_size": original_size, "canvas": list(canvas.size),
  "object_size": list(src.size), "object_bbox": list(bbox),
  "already_transparent": existing_alpha, "segmentation_applied": removed,
  "segmentation_model": a.segment if removed else None,
  "upscale_factor": round(scale,3), "mask": mask_path.name if mask_path else None,
  "warning": ("Upscaling cannot restore lost source detail" if scale>2.0 else None),
}
dest.with_suffix(".prep.json").write_text(json.dumps(report, indent=2),encoding="utf-8")
print(json.dumps(report))
'''


def _uv_executable():
    uv = shutil.which('uv')
    if uv:
        return uv
    home = Path.home()
    candidates = [home / '.local' / 'bin' / 'uv.exe',
                  home / '.cargo' / 'bin' / 'uv.exe']
    appdata = os.environ.get('LOCALAPPDATA')
    if appdata:
        candidates.append(Path(appdata) / 'Microsoft' / 'WinGet' / 'Links' / 'uv.exe')
    return str(next((v for v in candidates if v.is_file()), ''))


def _prep_signature(settings):
    src = Path(settings['image'])
    stat = src.stat()
    fields = {name: settings.get(name) for name in (
        'image', 'model', 'remove_bg', 'segment_model', 'canvas',
        'occupancy', 'smart_crop', 'upscale')}
    fields['prep_revision'] = _IMAGE_PREP_REVISION
    fields['clean_mask'] = bool(settings.get('clean_mask', True))
    fields['clean_existing_alpha'] = bool(settings.get('clean_existing_alpha', False))
    # The destination is part of the cache key. Never reuse a preview from an old folder.
    fields['output_dir'] = str(Path(settings['output_dir']).expanduser().resolve())
    fields['mtime_ns'], fields['size'] = stat.st_mtime_ns, stat.st_size
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]


def _effective_canvas(settings):
    if settings['canvas'] != 'AUTO':
        return int(settings['canvas'])
    # Conservative app-side preprocessing defaults (not claimed Tiiny API limits).
    return 1024 if 'TRELLIS' in settings['model'] else 512


def _image_prep_runtime():
    """An isolated, persistent Python environment (never Blender's Python)."""
    local = os.environ.get('LOCALAPPDATA') if os.name == 'nt' else None
    root = Path(local) if local else Path.home() / '.cache'
    envdir = root / 'TiinyAIForBlender' / 'image-prep-py312'
    executable = envdir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    return envdir, executable


def _run_prep_command(cmd, timeout, explanation):
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding='utf-8', errors='replace',
                                timeout=timeout, check=False,
                                stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RuntimeError(explanation + ' timed out') from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or 'No error text')[-900:].replace('\n', ' ')
        raise RuntimeError('%s failed: %s' % (explanation, detail))
    return result


def _run_image_prep_process(cmd, timeout, message_callback=None, stage_callback=None):
    """Stream known stage markers while keeping subprocess output off the UI.

    The rembg weights loader does not publish a reliable percentage through this
    interface. The panel therefore reports the stage and elapsed time, not a
    fabricated download percent. Reading both pipes avoids deadlocks on Windows.
    """
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace', bufsize=1,
        stdin=subprocess.DEVNULL, creationflags=flags, env=_image_prep_environment())
    events = queue.Queue()
    lines_out, lines_err = [], []

    def read_pipe(stream, kind):
        try:
            for line in stream:
                events.put((kind, line.rstrip('\r\n')))
        finally:
            stream.close()
            events.put((kind, None))

    threads = [threading.Thread(target=read_pipe, args=(proc.stdout, 'out'), daemon=True),
               threading.Thread(target=read_pipe, args=(proc.stderr, 'err'), daemon=True)]
    for thread in threads:
        thread.start()
    finished = set()
    started = time.monotonic()
    try:
        while len(finished) < 2 or proc.poll() is None:
            if time.monotonic() - started > timeout:
                proc.kill()
                proc.wait()
                raise RuntimeError('Local image preparation timed out during model setup or masking')
            try:
                kind, line = events.get(timeout=.25)
            except queue.Empty:
                continue
            if line is None:
                finished.add(kind)
            elif kind == 'out' and line.startswith('TIINY_PREP_STAGE\t'):
                parts = line.split('\t', 2)
                if len(parts) == 3:
                    code, text = parts[1], parts[2]
                    phase = {'MODEL': 4, 'MASK': 5, 'CLEANUP': 5, 'SAVE': 6}.get(code, 5)
                    _prep_notice(message_callback, stage_callback, phase, text)
                    _prep_log(code + ': ' + text)
            elif kind == 'out':
                lines_out.append(line)
            else:
                lines_err.append(line)
            if len(lines_out) > 150:
                del lines_out[:75]
            if len(lines_err) > 150:
                del lines_err[:75]
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for thread in threads:
            thread.join(timeout=1.0)
    return subprocess.CompletedProcess(cmd, proc.returncode,
                                       '\n'.join(lines_out), '\n'.join(lines_err))


def _ensure_image_prep_python(need_rembg=False, message_callback=None, stage_callback=None, setup_stage=False):
    """Install packages once and run directly thereafter, without uv network resolution.

    ONNX weights are stored in this add-on's private cache. The background
    installer prefetches ISNet; optional segmentation models remain on-demand.
    """
    envdir, interpreter = _image_prep_runtime()
    with _IMAGE_PREP_ENV_LOCK:
        pillow_marker = envdir / '.tiiny-pillow-ready'
        rembg_marker = envdir / '.tiiny-rembg-ready'
        if not interpreter.is_file() or not pillow_marker.is_file():
            uv = _uv_executable()
            if not uv:
                raise RuntimeError('uv not found. Install uv (winget install --id=astral-sh.uv -e) and restart Blender')
            _prep_notice(message_callback, stage_callback, 2, 'Setting up local Python for image preparation (first use only)')
            envdir.parent.mkdir(parents=True, exist_ok=True)
            if not interpreter.is_file():
                _run_prep_command([uv, 'venv', '--python', '3.12', str(envdir)], 600, 'Creating image-prep environment')
            if setup_stage:
                _setup_update(3, 'Installing/checking Pillow package')
            _prep_notice(message_callback, stage_callback, 2, 'Installing Pillow in the local image environment')
            _run_prep_command([uv, 'pip', 'install', '--python', str(interpreter), 'Pillow'],
                              600, 'Installing Pillow in local environment')
            pillow_marker.write_text('ready\n', encoding='ascii')
            _prep_log('Pillow environment ready')
        if need_rembg and not rembg_marker.is_file():
            uv = _uv_executable()
            if not uv:
                raise RuntimeError('uv required for one-time local background remover setup')
            _prep_notice(message_callback, stage_callback, 3, 'Installing CPU background removal tools (first use only)')
            _run_prep_command([uv, 'pip', 'install', '--python', str(interpreter), 'rembg[cpu]'],
                              1200, 'Installing rembg in local environment')
            rembg_marker.write_text('ready\n', encoding='ascii')
            _prep_log('rembg CPU environment ready')
        return interpreter, rembg_marker.is_file()


def _prepare_image(settings, message_callback=None, stage_callback=None):
    """Create an alpha-masked, centred square PNG, retaining source photo.

    Package installations happen only at first use; subsequent preparations run
    an already installed Python executable directly, without contacting PyPI.
    The default ISNet weights are preinstalled on add-on startup. If that
    private cache is removed, rembg may fetch the model again on demand.
    """
    if not settings.get('use_local_image_tools', True):
        raise RuntimeError('Local image tools disabled. Use the selected image directly.')
    _prep_notice(message_callback, stage_callback, 1, 'Checking source image and prepared-image cache')
    signature = _prep_signature(settings)
    target = Path(settings['output_dir']) / 'prepared' / ('tiiny_prepared_' + signature + '.png')
    reportpath = target.with_suffix('.prep.json')
    if target.is_file() and reportpath.is_file():
        report = json.loads(reportpath.read_text(encoding='utf-8'))
        # Legacy reports may contain an absolute path to a directory that was
        # moved later. Always resolve the mask beside the current prepared PNG.
        mask = target.with_name(target.stem + '_mask.png')
        report['mask'] = mask.name if mask.is_file() else None
        _prep_notice(message_callback, stage_callback, 6, 'Prepared image found in the local cache')
        return target, signature, report
    dest = target.resolve()
    cmdargs = ['--source', settings['image'], '--out', str(dest),
               '--canvas', str(_effective_canvas(settings)),
               '--occupancy', str(settings['occupancy']), '--segment', settings['segment_model'],
               '--prep-revision', _IMAGE_PREP_REVISION]
    if not settings.get('clean_mask', True):
        cmdargs.append('--no-mask-cleanup')
    if settings.get('clean_existing_alpha', False):
        cmdargs.append('--clean-existing-alpha')
    if settings['remove_bg']:
        cmdargs.append('--remove-bg')
    if not settings['smart_crop']:
        cmdargs.append('--no-crop')
    if not settings['upscale']:
        cmdargs.append('--no-upscale')

    if _status_get('setup').get('state') in ('working','queued'):
        _prep_notice(message_callback, stage_callback, 1, 'Waiting for local image tools installation...')
    with _BACKGROUND_TOOLS_LOCK:
        return _prepare_image_with_tools(settings, cmdargs, target, reportpath,
                                         signature, message_callback, stage_callback)


def _prepare_image_with_tools(settings, cmdargs, target, reportpath, signature,
                              message_callback=None, stage_callback=None):
    executable, has_rembg = _ensure_image_prep_python(message_callback=message_callback, stage_callback=stage_callback)
    _prep_notice(message_callback, stage_callback, 3, 'Reading image and checking transparency')
    args = [str(executable), '-c', _IMAGE_PREP_SCRIPT] + cmdargs
    if has_rembg and settings['remove_bg']:
        args.append('--with-rembg')
    res = _run_image_prep_process(args, timeout=1200 if has_rembg else 300,
                                   message_callback=message_callback, stage_callback=stage_callback)
    if res.returncode == 42 and 'TIINY_NEED_REMBG' in res.stderr:
        executable, has_rembg = _ensure_image_prep_python(need_rembg=True,
                                                           message_callback=message_callback, stage_callback=stage_callback)
        _prep_notice(message_callback, stage_callback, 4,
                     'Starting local AI segmentation (model weights may download on first use)')
        args = [str(executable), '-c', _IMAGE_PREP_SCRIPT] + cmdargs + ['--with-rembg']
        res = _run_image_prep_process(args, timeout=1200,
                                       message_callback=message_callback, stage_callback=stage_callback)
    if res.returncode != 0:
        details = (res.stderr or res.stdout or '')[-1000:].replace('\n', ' ')
        _prep_log('Image preparation subprocess failed (exit code %s)' % res.returncode)
        lower = details.lower()
        if any(token in lower for token in ('connection refused', 'name resolution', 'urlopen error',
                                            'failed to download', 'connection reset', 'timed out',
                                            'certificate verify failed', 'http error', 'network is unreachable')):
            raise RuntimeError('Background model download or network access failed. Check internet access and retry; see the local setup log.')
        if 'no module named' in lower or 'modulenotfounderror' in lower:
            raise RuntimeError('Local image preparation dependency is missing. Restart Blender and retry; if it persists, inspect the setup log.')
        raise RuntimeError('Image preparation failed. Check the local setup log and retry. ' + details[-190:])
    if not target.is_file() or not reportpath.is_file():
        raise RuntimeError('Image preparation finished without prepared PNG')
    report = json.loads(reportpath.read_text(encoding='utf-8'))
    _prep_notice(message_callback, stage_callback, 6, 'Prepared PNG and mask saved successfully')
    return target, signature, report


def _prep_worker(settings):
    signature = None
    started_at = time.monotonic()
    try:
        signature = _prep_signature(settings)
        _status_set('prep', state='working', signature=signature, phase=1,
                    started_at=started_at, message='Checking reference image...')
        def progress(phase, message):
            _status_set('prep', state='working', signature=signature, phase=phase,
                        started_at=started_at, message=message)
        target, signature, report = _prepare_image(settings, stage_callback=progress)
        _status_set('prep', state='waiting_preview', signature=signature, phase=7,
                    started_at=started_at, message='PNG saved. Loading Blender preview...', report=report)
        _PENDING_PREVIEW.put((str(target), signature, report))
    except Exception as exc:
        _prep_log('ERROR: %s (preparation phase %s)' % (type(exc).__name__, _status_get('prep').get('phase', 'unknown')))
        _status_set('prep', state='error', signature=signature, phase=0,
                    started_at=started_at, message=str(exc))


def _normalize_base(raw):
    raw = (raw or '').strip().rstrip('/')
    if raw.endswith('/v1'):
        raw = raw[:-3]
    parsed = urlparse.urlsplit(raw)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Use http://tiinyhost.local or http://<LAN-IP>')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Tiiny URL must contain only protocol and host (no credentials or path)')
    return raw


def _identity(base, key):
    try:
        base = _normalize_base(base)
    except ValueError:
        base = str(base).strip()
    return hashlib.sha256((base + '\x00' + (key or '')).encode('utf-8')).hexdigest()


def _data(body):
    if not isinstance(body, dict):
        raise RuntimeError('Unexpected Tiiny JSON response')
    if body.get('success') is False or body.get('status') == 'error':
        raise RuntimeError('Tiiny returned an error: ' + str(body.get('error') or body.get('message'))[:300])
    result = body.get('data', body)
    if not isinstance(result, dict):
        raise RuntimeError('Unexpected Tiiny response.data')
    return result


def _multipart(fields, files):
    """Build multipart/form-data with Python stdlib; no requests/PyTorch/uv required."""
    boundary = 'TiinyBlender' + uuid.uuid4().hex
    out = bytearray()
    for field, value in fields.items():
        out.extend(('--' + boundary + '\r\nContent-Disposition: form-data; name="%s"\r\n\r\n' % field).encode())
        out.extend(str(value).encode('utf-8'))
        out.extend(b'\r\n')
    for field, (filename, blob, mime) in files.items():
        safe_filename = re.sub(r'[\r\n"\\]', '_', str(filename))
        out.extend(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                    'Content-Type: %s\r\n\r\n' % (boundary, field, safe_filename, mime)).encode('utf-8'))
        out.extend(blob)
        out.extend(b'\r\n')
    out.extend(('--' + boundary + '--\r\n').encode())
    return bytes(out), 'multipart/form-data; boundary=' + boundary


def _request(method, base, key, path, model='', fields=None, files=None,
             timeout=40, raw=False):
    base = _normalize_base(base)
    if not (key or '').strip():
        raise ValueError('Enter your Tiiny API key')
    query = ('?model=' + urlparse.quote(model, safe='')) if model else ''
    data = None
    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}
    if fields is not None:
        data, content_type = _multipart(fields, files or {})
        headers['Content-Type'] = content_type
    request = urlrequest.Request(base + path + query, data=data, headers=headers, method=method)
    # Tiiny is LAN-only. Do not accidentally send API credentials through a
    # configured external HTTP proxy.
    class _NoRedirect(urlrequest.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener = urlrequest.build_opener(urlrequest.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            content = response.read()
    except urlerror.HTTPError as exc:
        try:
            code = exc.code
            if code in (401, 403):
                raise RuntimeError('Tiiny API key rejected (HTTP %s)' % code) from None
            if code == 502:
                raise RuntimeError('Tiiny HTTP 502: unlock TiinyOS after restart') from None
            if code == 503:
                raise RuntimeError('3D model unavailable (HTTP 503): load it in TiinyOS') from None
            msg = exc.read(420).decode('utf-8', 'replace').replace('\n', ' ')
            raise RuntimeError('Tiiny HTTP %s: %s' % (code, msg)) from None
        finally:
            # HTTPError owns a response stream too, including early 502/503 paths.
            exc.close()
    except (urlerror.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError('Cannot reach Tiiny: check LAN, address and device power (%s)' % str(exc.reason if isinstance(exc, urlerror.URLError) else exc)[:120]) from None
    if raw:
        return content
    try:
        return _data(json.loads(content.decode('utf-8')))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError('Tiiny returned non-JSON data (check device address)') from None


def _get_caps(base, key, model):
    caps = _request('GET', base, key, '/v1/3d/capabilities', model=model, timeout=25)
    stages = caps.get('stages') or []
    if not isinstance(stages, list) or 'shape' not in stages:
        raise RuntimeError('Selected 3D model does not expose the shape stage')
    return caps


def _status_set(kind, **values):
    with _LOCK:
        _STATUS[kind] = {**_STATUS.get(kind, {}), **values}


def _status_get(kind):
    with _LOCK:
        return dict(_STATUS.get(kind, {}))


def _caps_get(identity, model):
    with _LOCK:
        return _CAPABILITIES.get((identity, model))


def _probe_worker(kind, base, key, model, identity):
    if kind == 'connection':
        try:
            _request('GET', base, key, '/api/v1/sys/status', timeout=15)
            _status_set('connection', identity=identity, state='ok',
                        message='Connected; API key accepted', at=time.strftime('%H:%M:%S'))
        except Exception as exc:
            _status_set('connection', identity=identity, state='error',
                        message=str(exc), at=time.strftime('%H:%M:%S'))
            return
        # Checking an unloaded model must not turn a valid API key into an error.
        _status_set('model', identity=identity, model=model, state='checking',
                    message='Reading model capabilities...')
    try:
        caps = _get_caps(base, key, model)
        with _LOCK:
            _CAPABILITIES[(identity, model)] = {'caps': caps, 'checked_at': time.time()}
        stages = caps.get('stages') or []
        missing = [s for s in ('texture', 'export') if s not in stages]
        message = ('3D + PBR ready' if not missing else
                   'PBR unavailable: ' + ', '.join(missing))
        _status_set('model', identity=identity, model=model,
                    state='warning' if missing else 'ok', message=message,
                    at=time.strftime('%H:%M:%S'))
        _status_set('connection', identity=identity, state='ok',
                    message='Connected; API key accepted', at=time.strftime('%H:%M:%S'))
    except Exception as exc:
        _status_set('model', identity=identity, model=model,
                    state='error', message=str(exc), at=time.strftime('%H:%M:%S'))


def _start_probe(kind, context):
    pref = context.preferences.addons[__name__].preferences
    model = pref.tiiny_model
    base, key = pref.tiiny_api_url, pref.tiiny_api_key
    fingerprint = _identity(base, key)
    if not key.strip():
        _status_set(kind, identity=fingerprint, model=model, state='error', message='Enter your API key')
        return
    _status_set(kind, identity=fingerprint, model=model,
                state='checking', message='Checking local Tiiny API...')
    threading.Thread(target=_probe_worker, args=(kind, base, key, model, fingerprint), daemon=True).start()


def _draw_status(layout, kind, pref, model=''):
    state = _status_get(kind)
    if not state or state.get('identity') != _identity(pref.tiiny_api_url, pref.tiiny_api_key) or (
            kind == 'model' and model and state.get('model') != model):
        layout.label(text='Not checked', icon='QUESTION')
        return
    icon = {'ok': 'CHECKMARK', 'checking': 'TIME', 'error': 'ERROR', 'warning': 'INFO'}.get(state.get('state'), 'QUESTION')
    msg = state.get('message') or ''
    # Show short status, full details in info status after clicking the button.
    for i, line in enumerate(_ui_message_lines(msg)):
        layout.label(text=line, icon=icon if i == 0 else 'NONE')
    if state.get('state') not in ('checking', '') and state.get('at'):
        layout.label(text='Checked %s (not live)' % state['at'], icon='TIME')


def _on_pref_model_change(self, context):
    """One model selector in Preferences, shared with the Image-to-3D sidebar."""
    try:
        if context is not None and getattr(context, 'scene', None):
            props = context.scene.tiiny_settings
            name = 'trellis_quality' if 'TRELLIS' in self.tiiny_model else 'hunyuan_quality'
            props.quality = getattr(props, name, 'STANDARD') or 'STANDARD'
            _invalidate_prepared(props)
            _queue_auto_prepare(context)  # Only when the user selected a source this session.
        if context is not None and self.tiiny_api_key.strip():
            _start_probe('model', context)
    except (AttributeError, RuntimeError, KeyError, ReferenceError):
        pass


def _on_output_folder_change(self, context):
    """Invalidate old prepared previews whenever the destination directory changes."""
    try:
        if context is not None and getattr(context, 'scene', None):
            props = context.scene.tiiny_settings
            _invalidate_prepared(props)
            _queue_auto_prepare(context)  # No source => no directory created.
    except (AttributeError, RuntimeError, KeyError, ReferenceError):
        pass


def _enum_choices(entry, context):
    key = entry.choices_json or ''
    if key not in _ENUM_CACHE:
        try:
            choices = json.loads(key)
            _ENUM_CACHE[key] = tuple((str(c), str(c), str(c)) for c in choices)
        except (ValueError, TypeError):
            _ENUM_CACHE[key] = (('none', '(no options)', ''),)
    return _ENUM_CACHE[key]


# ----------- Tiiny model-specific quality schema inspection ----------------

def _enum_values(schema):
    if not isinstance(schema, dict):
        return []
    for field in ('enum', 'choices', 'values', 'options', 'allowed_values', 'allowed'):
        raw = schema.get(field)
        if isinstance(raw, dict):
            raw = list(raw.keys())
        if isinstance(raw, (tuple, list)) and raw:
            options = []
            for value in raw:
                if isinstance(value, (str, int, float, bool)):
                    options.append(value)
                elif isinstance(value, dict) and 'value' in value:
                    options.append(value['value'])
                else:
                    options = []
                    break
            if options:
                return options
    return []


def _normalize_schema_entry(key, schema):
    if isinstance(schema, (list, tuple)):
        schema = {'choices': schema}
    schema = schema if isinstance(schema, dict) else {}
    nested = schema.get('schema') if isinstance(schema.get('schema'), dict) else {}
    fields = {**nested, **schema}
    # Tiiny TRELLIS uses nullable Pydantic schemas: anyOf:[{type:'integer', ...},{type:'null'}].
    # The old parser called those 'unknown' and asked users to type arbitrary JSON.
    for combiner in ('anyOf', 'oneOf'):
        alternatives = fields.get(combiner)
        if isinstance(alternatives, list):
            concrete = [v for v in alternatives if isinstance(v, dict) and v.get('type') != 'null']
            if len(concrete) == 1:
                fields = {**concrete[0], **{k:v for k,v in fields.items() if k not in ('anyOf','oneOf')}}
                break
    default = fields.get('default', fields.get('default_value'))
    dtype = str(fields.get('type', fields.get('data_type', ''))).lower()
    options = _enum_values(fields)
    if options:
        kind = 'enum'
    elif dtype in ('int', 'integer') or (isinstance(default, int) and not isinstance(default, bool)):
        kind = 'int'
    elif dtype in ('float', 'number', 'double') or isinstance(default, float):
        kind = 'float'
    elif dtype in ('bool', 'boolean') or isinstance(default, bool):
        kind = 'bool'
    elif dtype in ('str', 'string', 'text') or isinstance(default, str):
        kind = 'string'
    else:
        kind = 'unknown'
    label = fields.get('title') or fields.get('label') or key.replace('_', ' ').title()
    bounds = fields.get('range') or []
    minimum = fields.get('minimum', fields.get('min'))
    maximum = fields.get('maximum', fields.get('max'))
    if isinstance(bounds, (tuple, list)) and len(bounds) == 2:
        if minimum is None:
            minimum = bounds[0]
        if maximum is None:
            maximum = bounds[1]
    return {'key': key, 'kind': kind, 'label': label, 'default': default,
            'choices': options, 'min': minimum, 'max': maximum,
            'help': fields.get('description') or fields.get('help') or ''}


def _top_quality_options(caps):
    """Authoritative top-level quality choices, not guesses from original model GitHub."""
    result = {}
    prec = caps.get('output_precisions')
    if isinstance(prec, dict):
        result['output_precision'] = list(prec)
    for key, source in [('inference_quality', 'inference_qualities'),
                        ('asset_quality', 'asset_qualities')]:
        options = caps.get(source)
        if isinstance(options, (list, tuple)):
            result[key] = [v for v in options if isinstance(v, (str, int, float))]
    return {k: v for k, v in result.items() if v}


def _extract_stage_controls(caps):
    """User-friendly typed controls from real Tiiny capabilities.

    Top-level model-wide quality controls are included once, not repeated in
    every stage. Controls without type/values/range are omitted rather than
    forcing users to enter undocumented JSON.
    """
    parsed = []
    global_options = _top_quality_options(caps)
    for key, options in global_options.items():
        label = {'output_precision':'Geometry precision',
                 'inference_quality':'Inference quality',
                 'asset_quality':'Asset processing quality'}[key]
        item = _normalize_schema_entry(key, {'title': label, 'enum': options})
        parsed.append({'stage': 'quality', **item})
    specs = caps.get('stage_specs') or {}
    if not isinstance(specs, dict):
        specs = {}
    # Tiiny Hunyuan publishes only a list of allowed parameter names, without
    # types/ranges. Fill *select* types from upstream Tencent docs, but never
    # invent server support for fields absent from its own advertised list.
    if _is_hunyuan_caps(caps):
        published = caps.get('params') or {}
        for stage, hints in HUNYUAN_UPSTREAM_HINTS.items():
            raw = published.get(stage, []) if isinstance(published, dict) else []
            names = set(raw) if isinstance(raw, (list, tuple)) else set(raw) if isinstance(raw, dict) else set()
            # If stage_specs exists, its parameter schemas take precedence.
            stage_spec = specs.get(stage) or {}
            described = stage_spec.get('params') or {}
            described = set(described) if isinstance(described, (dict, list, tuple)) else set()
            for key, hint in hints.items():
                if key in names and key not in described:
                    parsed.append({'stage': stage, **_normalize_schema_entry(key, hint)})
    for stage in ('shape','simplify','texture','export'):
        spec = specs.get(stage)
        if not isinstance(spec, dict):
            continue
        definitions = {}
        for section_name in ('params', 'controls', 'parameters', 'properties'):
            section = spec.get(section_name)
            if isinstance(section, dict):
                entries = list(section.items())
            elif isinstance(section, (tuple, list)):
                entries = []
                for element in section:
                    if isinstance(element, str):
                        entries.append((element, {}))
                    elif isinstance(element, dict):
                        key = element.get('name') or element.get('key') or element.get('id')
                        if isinstance(key, str):
                            entries.append((key, element))
            else:
                continue
            for key, definition in entries:
                if isinstance(key, str):
                    if isinstance(definition, (tuple, list)):
                        definition = {'choices': definition}
                    definitions.setdefault(key, {}).update(definition if isinstance(definition, dict) else {})
        for key, definition in definitions.items():
            # seed and face count have their own existing controls; output_name
            # is managed automatically to avoid overwriting existing files.
            if key in ('seed','target_faces','output_name') or key in global_options:
                continue
            item = _normalize_schema_entry(key, definition)
            if item['kind'] == 'unknown':
                continue
            parsed.append({'stage': stage, **item})
    return parsed


def _allowed_names(caps, stage):
    specs = caps.get('stage_specs') or {}
    spec = specs.get(stage)
    if not isinstance(spec, dict):
        return None
    names = set()
    for field in ('params', 'controls', 'parameters', 'properties'):
        section = spec.get(field)
        if isinstance(section, dict):
            names.update(section)
        elif isinstance(section, (tuple, list)):
            for value in section:
                if isinstance(value, str):
                    names.add(value)
                elif isinstance(value, dict):
                    key = value.get('name') or value.get('key') or value.get('id')
                    if isinstance(key, str):
                        names.add(key)
    return names


def _quality_direction(options, preset):
    """Use only enum choices whose order is semantically clear or numeric."""
    if not options:
        return None
    scored = []
    for value in options:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            score = float(value)
        else:
            text = str(value).strip().lower()
            if text in QUALITY_ORDER:
                score = QUALITY_ORDER[text]
            elif text.isdecimal():
                score = int(text)
            else:
                score = None
        if score is None:
            return None
        scored.append((score, value))
    return (min if preset == 'DRAFT' else max)(scored, key=lambda item: item[0])[1]


def _global_preset(caps, preset):
    if preset == 'STANDARD' and _is_trellis_caps(caps):
        # Make this recipe reproducible. Tiiny's own capabilities map
        # standard -> 512; no assumption about the native cascade is made.
        choices = _top_quality_options(caps)
        preferred = {'output_precision': 'standard',
                     'inference_quality': 'balance', 'asset_quality': 'balance'}
        return {key: value for key, value in preferred.items() if value in choices.get(key, [])}
    if preset not in ('DRAFT', 'MAXIMUM'):
        return {}
    result = {}
    for key, choices in _top_quality_options(caps).items():
        chosen = _quality_direction(choices, preset)
        if chosen is not None:
            result[key] = chosen
    return result


def _stage_global_quality(caps, values, stage):
    """Route model-wide Tiiny controls to stages using advertised stage inputs.

    Models with stage_specs explicitly list controls for each stage.
    Older Hunyuan without stage_specs uses Tiiny Studio's documented approach:
    include supported global quality keys in a stage params object.
    """
    allowed = _allowed_names(caps, stage)
    if allowed is None:
        return dict(values)
    return {k:v for k,v in values.items() if k in allowed}


def _preset_stage_params(caps, preset, stage):
    if preset not in ('DRAFT', 'MAXIMUM', 'STANDARD'):
        return {}
    result = _stage_global_quality(caps, _global_preset(caps, preset), stage)
    # When the server advertises quality tiers, do not force raw numeric
    # maxima such as texture_size=8192 merely because an API bound exists.
    # Those limits are editable in Custom and may exceed practical NPU memory.
    if _top_quality_options(caps):
        return result
    if preset == 'STANDARD':
        return result
    # Fallback for a backend exposing only stage-scoped quality settings.
    for spec in _extract_stage_controls(caps):
        key = spec['key']
        if spec['stage'] != stage or key not in QUALITY_KEYS or key in result:
            continue
        chosen = _quality_direction(spec['choices'], preset)
        if chosen is None and spec['kind'] in ('int', 'float'):
            border = spec['min'] if preset == 'DRAFT' else spec['max']
            if isinstance(border, (int, float)) and not isinstance(border, bool):
                chosen = int(border) if spec['kind'] == 'int' else float(border)
        if chosen is not None:
            result[key] = chosen
    return result


def _available_quality_modes(caps, use_texture=True):
    if not isinstance(caps, dict):
        return ('STANDARD',)
    active = ['shape', 'simplify'] + (['texture', 'export'] if use_texture else [])
    draft = {s:v for s in active if (v:=_preset_stage_params(caps,'DRAFT',s))}
    maximum = {s:v for s in active if (v:=_preset_stage_params(caps,'MAXIMUM',s))}
    modes = ['STANDARD']
    if draft and draft != maximum:
        modes.append('DRAFT')
    if maximum and maximum != draft:
        modes.append('MAXIMUM')
    if any(c['stage'] in (['quality'] + active) for c in _extract_stage_controls(caps)):
        modes.append('CUSTOM')
    return tuple(modes)


def _effective_quality(caps, requested, use_texture=True):
    """Guard even bookmarked or saved old enum values against changed TiinyOS."""
    return requested if requested in _available_quality_modes(caps, use_texture) else 'STANDARD'


def _quality_summary(caps, mode, use_texture=True):
    stages = ['shape'] + (['texture', 'export'] if use_texture else [])
    return {stage: params for stage in stages
            if (params := _preset_stage_params(caps, mode, stage))}


def _cast_custom(entry):
    if entry.datatype == 'enum':
        value = entry.value_enum
        allowed = json.loads(entry.choices_json)
        for candidate in allowed:
            if str(candidate) == value:
                return candidate
        raise ValueError('Unsupported option %s for %s' % (value, entry.param_name))
    if entry.datatype == 'int':
        value = int(entry.value_int)
    elif entry.datatype == 'float':
        value = float(entry.value_float)
    elif entry.datatype == 'bool':
        value = entry.value_bool_choice == 'TRUE'
    elif entry.datatype == 'string':
        value = entry.value_text
    else:
        # Unknown metadata: only use explicit JSON input with an opt-in.
        value = json.loads(entry.value_text)
    minimum = json.loads(entry.min_json) if entry.min_json else None
    maximum = json.loads(entry.max_json) if entry.max_json else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(minimum, (int, float)) and value < minimum:
            raise ValueError('%s must be >= %s' % (entry.param_name, minimum))
        if isinstance(maximum, (int, float)) and value > maximum:
            raise ValueError('%s must be <= %s' % (entry.param_name, maximum))
    return value


def _parameter_schema(caps, stage, key):
    """Prefer explicit stage constraints over the model-wide quality list.

    A stage may accept fewer choices than the overall model. Empty/name-only
    stage entries still fall back to the published global choices.
    """
    spec = (caps.get('stage_specs') or {}).get(stage) or {}
    for section in ('params', 'controls', 'parameters', 'properties'):
        values = spec.get(section)
        if isinstance(values, dict) and isinstance(values.get(key), dict) and values[key]:
            return values[key]
    if key in _top_quality_options(caps):
        return {'enum': _top_quality_options(caps)[key]}
    return {}


def _validate_stage_params(caps, stage, params):
    """Validate all final values against the newly fetched device capabilities.

    In particular, never send stale enum choices or out-of-range numbers after
    the user changes a model/firmware. This runs before the first task POST.
    Unknown server bounds stay unknown; this is not a native-model API schema.
    """
    allowed = _allowed_names(caps, stage)
    for key, value in params.items():
        if allowed is not None and key not in allowed:
            raise ValueError('%s.%s is not advertised by this Tiiny model' % (stage, key))
        raw = _parameter_schema(caps, stage, key)
        spec = _normalize_schema_entry(key, raw)
        kind = spec['kind']
        name = '%s.%s' % (stage, key)
        if kind == 'enum' and value not in spec['choices']:
            raise ValueError('%s no longer accepts %r; refresh model settings' % (name, value))
        if kind == 'int' and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(name + ' requires an integer')
        if kind == 'float' and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise ValueError(name + ' requires a number')
        if kind == 'bool' and not isinstance(value, bool):
            raise ValueError(name + ' requires true or false')
        if kind == 'string' and not isinstance(value, str):
            raise ValueError(name + ' requires text')
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                raise ValueError(name + ' must be finite')
            for bound, op in ((spec['min'], 'min'), (spec['max'], 'max')):
                if isinstance(bound, (int, float)) and ((op == 'min' and value < bound) or (op == 'max' and value > bound)):
                    raise ValueError('%s must be %s %s (current Tiiny schema)' % (name, '>=' if op == 'min' else '<=', bound))
    return params


def _face_limits(caps):
    spec = _normalize_schema_entry('target_faces', _parameter_schema(caps, 'simplify', 'target_faces'))
    return spec['min'], spec['max']


def _geometry_profile(settings):
    if 'TRELLIS' not in settings.get('model', ''):
        return 'OFF'
    mode = settings.get('trellis_postprocess', 'OFF')
    if mode not in ('OFF', 'DEFAULT', 'REMESH256', 'REMESH512', 'PRESERVE512'):
        raise ValueError('Unknown TRELLIS surface mode: ' + str(mode))
    return mode


def _manual_overrides(settings, preset):
    return settings.get('custom', []) if preset == 'CUSTOM' or settings.get('manual_overrides', False) else []


def _published_stage_names(caps, stage):
    names = _allowed_names(caps, stage)
    if names is not None:
        return names
    declared = (caps.get('params') or {}).get(stage)
    return set(declared) if isinstance(declared, (dict, list, tuple)) else set()


def _stage_params(caps, settings, stage, preset):
    allowed = _allowed_names(caps, stage)
    params = _preset_stage_params(caps, _base_preset(settings, preset), stage)
    if stage == 'simplify':
        params['simplify'] = True
        if int(settings.get('faces',0)):
            params['target_faces'] = int(settings['faces'])
        # TRELLIS option: enable a device-side geometry-processing stage that
        # would otherwise be skipped when Target faces is 0. Unlike Blender
        # modifiers this runs BEFORE texture/export and can supply a
        # geometry_artifact reference to the export stage.
        cleanup = _geometry_profile(settings)
        if 'TRELLIS' in settings.get('model','') and cleanup in ('REMESH256', 'REMESH512'):
            # Only schema-advertised controls are sent (filter at end).
            params['remesh_resolution'] = 256 if cleanup == 'REMESH256' else 512
            params['remesh_closing_iterations'] = 1
        elif cleanup == 'PRESERVE512':
            # Candidate based on the archive's decimation confound. This does
            # not claim equivalence to Microsoft's remesh_project parameter.
            params.update(simplify=False, remesh_resolution=512,
                          remesh_closing_iterations=1, project_geometry=False)
            if int(settings.get('faces', 0)):
                params['simplify'] = True  # An explicit polygon budget wins.
    overrides = _manual_overrides(settings, preset)
    if overrides:
        global_overrides = {item['param']:item['value'] for item in overrides
                            if item['stage'] == 'quality' and item['enabled']}
        params.update(_stage_global_quality(caps, global_overrides, stage))
        known_stage = caps.get('params') or {}
        declared = known_stage.get(stage) if isinstance(known_stage, dict) else None
        if isinstance(declared, dict):
            declared = set(declared)
        elif isinstance(declared, (list, tuple)):
            declared = set(declared)
        else:
            declared = None
        for item in overrides:
            if item['stage'] == stage and item['enabled']:
                if declared is not None and item['param'] not in declared:
                    continue  # Tiiny no longer advertises this custom parameter
                params[item['param']] = item['value']
        if stage == 'shape' and 'pipeline_type' in params and 'output_precision' in params:
            # An explicit pipeline overrides the preset's precision alias.
            # Two explicit, contradictory overrides are an input error.
            mapping = (caps.get('output_precisions') or {}).get(params['output_precision'], {})
            mapped = mapping.get('pipeline_type') if isinstance(mapping, dict) else None
            if 'output_precision' in global_overrides and mapped and str(mapped) != str(params['pipeline_type']):
                raise ValueError('Pipeline type conflicts with the manual geometry precision; disable one override')
            params.pop('output_precision')
    seed = int(settings.get('seed', -1))
    if seed >= 0 and (allowed is None or 'seed' in allowed):
        params['seed'] = seed
    if allowed is not None:
        params = {k:val for k,val in params.items() if k in allowed}
    return _validate_stage_params(caps, stage, params)


def _execution_plan(caps, settings, preset):
    """Resolve and validate the whole job before generating any geometry."""
    cleanup = _geometry_profile(settings)
    overrides = _manual_overrides(settings, preset)
    # Saved UI controls can be older than the schema fetched for this job.
    # Do not silently replace an explicit user choice with a device default.
    for item in overrides:
        if not item['enabled'] or (item['stage'] in ('texture', 'export') and not settings.get('texture')):
            continue
        names = (_top_quality_options(caps) if item['stage'] == 'quality'
                 else _published_stage_names(caps, item['stage']))
        if item['param'] not in names:
            raise ValueError('Enabled override %s.%s is no longer advertised; refresh model settings' %
                             (item['stage'], item['param']))
    geometry_names = _published_stage_names(caps, 'simplify')
    if settings.get('faces', 0) and 'target_faces' not in geometry_names:
        raise ValueError('This Tiiny model no longer advertises a target polygon budget; set it to 0 or refresh settings')
    need_simplify = bool(settings.get('faces', 0)) or cleanup != 'OFF' or any(
        item['stage'] == 'simplify' and item['enabled'] and item['param'] in geometry_names
        for item in overrides)
    if cleanup in ('REMESH256', 'REMESH512', 'PRESERVE512'):
        required = {'remesh_resolution', 'remesh_closing_iterations'}
        if cleanup == 'PRESERVE512':
            required |= {'simplify', 'project_geometry'}
        allowed = _allowed_names(caps, 'simplify')
        if allowed is None or not required <= allowed:
            raise ValueError('The selected surface mode is not supported by the current Tiiny schema')
    plan = ['shape'] + (['simplify'] if need_simplify else [])
    if settings.get('texture'):
        plan += ['texture', 'export']
    stages = caps.get('stages') or []
    for stage in plan:
        if stage not in stages:
            raise ValueError('Stage %s is not supported by this Tiiny model' % stage)
    params = {stage: _stage_params(caps, settings, stage, preset) for stage in plan}
    if settings.get('faces', 0) and 'simplify' in params and params['simplify'].get('simplify') is False:
        raise ValueError('A target polygon count requires Simplify enabled; clear the count or its override')
    return plan, params


def _caps_digest(caps):
    return hashlib.sha256(json.dumps(caps, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def _sync_controls(scene, identity, model):
    """Copy model schemas into per-engine editable Blender controls (main thread)."""
    if not scene or not hasattr(scene, 'tiiny_settings'):
        return
    props = scene.tiiny_settings
    record = _caps_get(identity, model)
    if not record:
        return
    digest = _caps_digest(record['caps'])
    schema_key = 'v030:' + identity + ':' + model + ':' + digest
    if props.last_schema == schema_key:
        return
    valid = {(model, spec['stage'], spec['key']) for spec in _extract_stage_controls(record['caps'])}
    for i in range(len(props.controls)-1, -1, -1):
        item=props.controls[i]
        if item.model_id == model and (item.model_id,item.stage,item.param_name) not in valid:
            props.controls.remove(i)
    seen = {(p.model_id, p.stage, p.param_name): p for p in props.controls}
    for spec in _extract_stage_controls(record['caps']):
        key = (model, spec['stage'], spec['key'])
        fresh = key not in seen
        if fresh:
            item = props.controls.add()
            item.model_id, item.stage, item.param_name = key
            item.enabled = False
        else:
            item = seen[key]
        item.datatype = spec['kind']
        if spec['kind'] == 'bool':
            if fresh:
                item.value_bool_choice = 'DEFAULT'
            elif item.enabled:
                # Legacy boolean overrides had two checkboxes; migrate once.
                if item.value_bool_choice == 'DEFAULT':
                    item.value_bool_choice = 'TRUE' if item.value_bool else 'FALSE'
                item.enabled = False
        item.label = str(spec['label'])
        item.choices_json = json.dumps(spec['choices'], ensure_ascii=False)
        item.default_json = json.dumps(spec['default'])
        item.min_json = json.dumps(spec['min']) if spec['min'] is not None else ''
        item.max_json = json.dumps(spec['max']) if spec['max'] is not None else ''
        item.help_text = str(spec['help'])[:1023]
        if not fresh and spec['kind'] == 'enum':
            try:
                if item.value_enum not in [str(v) for v in spec['choices']]:
                    item.enabled = False
                    item.value_enum = str(spec['choices'][0])
            except (ValueError, AttributeError):
                item.enabled = False
        if fresh:
            default = spec['default']
            if spec['kind'] == 'int':
                fallback = spec['min'] if isinstance(spec['min'],int) else 0
                item.value_int = int(default if isinstance(default,(int,float)) else fallback)
            elif spec['kind'] == 'float':
                fallback = spec['min'] if isinstance(spec['min'],(int,float)) else 0.0
                item.value_float = float(default if isinstance(default,(int,float)) else fallback)
            elif spec['kind'] == 'bool' and isinstance(default,bool):
                item.value_bool = default
            elif spec['kind'] == 'enum' and spec['choices']:
                item.value_enum = str(default) if default in spec['choices'] else str(spec['choices'][0])
            elif default is not None:
                item.value_text = str(default)
        # Normalize previously stored invalid numbers when the schema changes.
        if spec['kind'] == 'int':
            if isinstance(spec['min'], (int, float)) and item.value_int < spec['min']:
                item.value_int = int(spec['min'])
            if isinstance(spec['max'], (int, float)) and item.value_int > spec['max']:
                item.value_int = int(spec['max'])
        elif spec['kind'] == 'float':
            if isinstance(spec['min'], (int, float)) and item.value_float < spec['min']:
                item.value_float = float(spec['min'])
            if isinstance(spec['max'], (int, float)) and item.value_float > spec['max']:
                item.value_float = float(spec['max'])
    props.last_schema = schema_key


def _custom_snapshot(props, model):
    custom = []
    for entry in props.controls:
        if entry.model_id != model or entry.param_name in ('seed', 'target_faces'):
            continue
        if entry.datatype == 'bool':
            if entry.value_bool_choice == 'DEFAULT':
                continue
        elif not entry.enabled:
            continue
        custom.append({'stage': entry.stage, 'param': entry.param_name,
                       'enabled': True, 'value': _cast_custom(entry)})
    return custom


def _glb_counts(content):
    if not isinstance(content, bytes) or len(content) < 20 or content[:4] != b'glTF':
        return {'materials': 0, 'images': 0, 'textures': 0}
    size, chunk_type = struct.unpack_from('<II', content, 12)
    if chunk_type != 0x4E4F534A or 20 + size > len(content):
        return {'materials': 0, 'images': 0, 'textures': 0}
    try:
        doc = json.loads(content[20:20 + size].decode('utf-8'))
        return {k: len(doc.get(k) or []) for k in ('materials', 'images', 'textures')}
    except (ValueError, TypeError, UnicodeDecodeError):
        return {'materials': 0, 'images': 0, 'textures': 0}

# ---------------------- Tiiny 3D worker (no Blender API) -------------------

def _job_set(jid, **values):
    with _LOCK:
        if jid in _JOBS:
            if _JOBS[jid].get('cancel'):
                # A late network/preparation result cannot resurrect a stopped job.
                values.pop('progress', None)
                if values.get('state') in ('queued', 'running', 'importing', 'completed', 'failed'):
                    values['state'] = 'cancelled'
                    values['message'] = 'Stopped locally'
                elif values.get('state') != 'cancelled':
                    values.pop('message', None)
            _JOBS[jid].update(values)


def _job_get(jid):
    with _LOCK:
        return dict(_JOBS.get(jid, {}))


def _cancel_event(jid):
    with _LOCK:
        return _JOB_CANCEL_EVENTS.setdefault(jid, threading.Event())


def _check_cancelled(jid):
    if jid and (_job_get(jid).get('cancel') or _cancel_event(jid).is_set()):
        raise InterruptedError('Stopped locally by user')


def _bounded_call(function, timeout, jid=None, on_result=None):
    """Bound caller waiting, including DNS and blocked reads, without using bpy.

    Python cannot forcibly kill a thread inside a network call. An abandoned
    request may finish later, but it cannot resume the generation worker.
    A small shared limit prevents accumulating unlimited blocked requests.
    """
    if jid:
        _check_cancelled(jid)
    if not _NETWORK_SLOTS.acquire(blocking=False):
        raise RuntimeError('Cannot reach Tiiny: earlier network requests are still finishing')
    done = threading.Event()
    abandoned = threading.Event()
    result = {}

    def run():
        try:
            if jid:
                _check_cancelled(jid)
            if abandoned.is_set():
                raise RuntimeError('Cannot reach Tiiny: caller already stopped waiting')
            value = function()
            result['value'] = value
            if on_result:
                on_result(value, abandoned.is_set())
        except Exception as exc:
            result['error'] = exc
        finally:
            _NETWORK_SLOTS.release()
            done.set()

    thread = threading.Thread(target=run, daemon=True, name='Tiiny network request')
    try:
        thread.start()
    except Exception:
        _NETWORK_SLOTS.release()
        raise
    deadline = time.monotonic() + max(0.05, float(timeout))
    while not done.wait(0.05):
        if jid:
            try:
                _check_cancelled(jid)
            except InterruptedError:
                abandoned.set()
                raise
        if time.monotonic() >= deadline:
            abandoned.set()
            raise RuntimeError('Cannot reach Tiiny: request deadline exceeded')
    if jid:
        _check_cancelled(jid)
    if 'error' in result:
        raise result['error']
    return result.get('value')


def _remote_cancel_worker(jid, base, key, model, task_id):
    """Best effort only: local cancellation never waits for Tiiny to respond."""
    try:
        result = _bounded_call(
            lambda: _request('POST', base, key,
                             '/v1/3d/tasks/%s/cancel' % urlparse.quote(str(task_id), safe=''),
                             model=model, timeout=5), timeout=6)
        state = str((result or {}).get('status') or '').lower()
        remote = 'confirmed' if state in ('cancelled', 'canceled') else 'accepted'
        _job_set(jid, remote_cancel=remote)
    except Exception:
        _job_set(jid, remote_cancel='unconfirmed')
    _refresh_cancel_report(jid)


def _start_remote_cancel(jid, base, key, model, task_id):
    if not task_id:
        return
    with _LOCK:
        token = (jid, str(task_id))
        if token in _REMOTE_CANCEL_TASKS:
            return
        _REMOTE_CANCEL_TASKS.add(token)
        if jid in _JOBS:
            _JOBS[jid]['remote_cancel'] = 'pending'
    threading.Thread(target=_remote_cancel_worker,
                     args=(jid, base, key, model, task_id),
                     daemon=True, name='Tiiny cancellation').start()


def _job_request(jid, method, base, key, path, **kwargs):
    """Cancellable wrapper; a stage-creation POST is never retried."""
    if not jid:
        return _request(method, base, key, path, **kwargs)
    creating = method == 'POST' and path == '/v1/3d/tasks'
    if creating:
        _job_set(jid, submission_pending=True, remote_task_status='unknown')
    model = kwargs.get('model', '')

    def completed(value, abandoned):
        if creating:
            tid = value.get('task_id') if isinstance(value, dict) else None
            _job_set(jid, submission_pending=False, task_id=tid or '',
                     remote_task_status='running' if tid else 'unknown')
            # A delayed accepted POST must not silently leave a task running
            # after the user stopped waiting or the submission deadline expired.
            if tid and (abandoned or _job_get(jid).get('cancel')):
                _start_remote_cancel(jid, base, key, model, tid)
                _refresh_cancel_report(jid)

    invoked = threading.Event()
    request_kwargs = dict(kwargs)
    if request_kwargs.get('raw'):
        # Permit a long transfer overall, but do not retain a dead socket for
        # ten minutes after local cancellation. This is an inactivity timeout.
        request_kwargs['timeout'] = min(30, float(request_kwargs.get('timeout', 40)))

    def invoke():
        invoked.set()
        try:
            return _request(method, base, key, path, **request_kwargs)
        except Exception:
            if creating:
                _job_set(jid, submission_pending=False)
            raise

    try:
        return _bounded_call(invoke,
                             timeout=float(kwargs.get('timeout', 40)) + 1.0,
                             jid=jid, on_result=completed if creating else None)
    except Exception:
        if creating and not invoked.is_set():
            _job_set(jid, submission_pending=False)
        raise


def _stop_job(jid):
    """Immediately stop local waiting. Never perform network I/O on the UI thread."""
    job = _job_get(jid)
    if not job or job.get('state') not in ('queued', 'running', 'importing'):
        return False
    tid = job.get('task_id')
    remote = ('pending' if tid and job.get('remote_task_status') != 'completed' else
              'unknown' if job.get('submission_pending') else 'not_needed')
    _job_set(jid, cancel=True, state='cancelled', message='Stopped locally',
             remote_cancel=remote)
    _cancel_event(jid).set()
    connection = job.get('_connection')
    if connection and remote == 'pending':
        _start_remote_cancel(jid, *connection, tid)
    threading.Thread(target=_refresh_cancel_report, args=(jid,), daemon=True).start()
    return True


def _context_job_id(context):
    current = getattr(getattr(context.scene, 'tiiny_settings', None), 'job_id', '')
    if current and _job_get(current).get('state') in ('queued', 'running', 'importing'):
        return current
    # Jobs are process-wide, while Blender's current scene may have changed.
    with _LOCK:
        for jid, job in reversed(list(_JOBS.items())):
            if job.get('state') in ('queued', 'running', 'importing'):
                return jid
    return current


def _cancel_all_jobs():
    with _LOCK:
        ids = list(_JOBS)
    for jid in ids:
        _stop_job(jid)


def _safe_diagnostic_text(value, settings):
    result = str(value or '')
    for private in (settings.get('key'), settings.get('base'),
                    settings.get('image'), settings.get('output_dir')):
        if private:
            result = result.replace(str(private), '[redacted]')
    return ' '.join(result.split())[:1000]


def _cancel_report_fields(job):
    return {
        'local_wait_stopped': bool(job.get('cancel') or job.get('local_wait_stopped')),
        'remote_cancel': job.get('remote_cancel', 'not_requested'),
        'last_known_task_id': job.get('task_id') or None,
        'submission_result_pending': bool(job.get('submission_pending')),
        'note': 'Stopping local waiting does not prove the device task stopped.',
    }


def _save_job_report(jid, path, manifest):
    """Serialize snapshots under a separate lock so Cancel stays responsive."""
    with _REPORT_LOCK:
        snapshot = copy.deepcopy(manifest)
        job = _job_get(jid)
        if job.get('cancel'):
            snapshot['status'] = 'cancelled'
        if job.get('cancel') or job.get('remote_cancel'):
            snapshot['cancellation'] = _cancel_report_fields(job)
        _write_manifest(path, snapshot)
        _JOB_REPORTS[jid] = (path, snapshot)


def _refresh_cancel_report(jid):
    with _REPORT_LOCK:
        record = _JOB_REPORTS.get(jid)
        if not record:
            return
        path, manifest = record
        job = _job_get(jid)
        if job.get('cancel'):
            manifest['status'] = 'cancelled'
        manifest['cancellation'] = _cancel_report_fields(job)
        try:
            _write_manifest(path, manifest)
        except (OSError, ValueError, TypeError):
            pass


def _resolved_trellis_resolution(caps, params):
    """Use explicit effective shape controls, not the selected preset label."""
    shape = params.get('shape', {})
    pipeline = shape.get('pipeline_type')
    if pipeline is None:
        precision = shape.get('output_precision')
        if precision is not None:
            mapping = (caps.get('output_precisions') or {}).get(precision)
            if isinstance(mapping, dict):
                pipeline = mapping.get('pipeline_type')
    if pipeline is None:
        return None
    match = re.match(r'^(\d+)(?:_|$)', str(pipeline))
    return int(match.group(1)) if match else None


def _check_trellis_resolution(caps, settings, params):
    if 'TRELLIS' not in settings.get('model', '') and not _is_trellis_caps(caps):
        return
    resolution = _resolved_trellis_resolution(caps, params)
    if resolution and resolution > 512 and not settings.get('allow_trellis_1024', False):
        raise ValueError(
            'TRELLIS %s is experimental on Tiiny. Use Standard (512), or enable '
            'Allow experimental 1024 in Advanced model settings for this session.' % resolution)


def _artifact_output(output, stage, final_stage, use_refs, job_id, base, key, model, refs, have, local_job_id=None):
    downloaded = []
    single = {
        'artifact_type': output.get('artifact_type') or 'mesh_glb',
        'filename': output.get('filename'), 'mime_type': output.get('mime_type'),
        'artifact_id': output.get('artifact_id'),
        'payload_key': next((k for k in ('glb', 'artifact', 'image', 'mesh')
                             if isinstance(output.get(k), str)), ''),
    }
    for art in output.get('artifacts') or [single]:
        _check_cancelled(local_job_id)
        kind = str(art.get('artifact_type') or '')
        if kind.endswith('_preview') and stage != final_stage:
            continue
        artifact_id = art.get('artifact_id')
        if artifact_id and kind:
            # PRECISE: TRELLIS uses input_refs; keep intermediates on Tiiny.
            refs[kind] = refs[kind + '_artifact'] = {
                'task_id': job_id, 'artifact_id': artifact_id}
        payload = output.get(art.get('payload_key') or '')
        if isinstance(payload, str) and payload:
            try:
                content = base64.b64decode(payload)
            except (ValueError, TypeError) as exc:
                raise RuntimeError('Invalid base64 artifact: %s' % kind) from exc
        elif use_refs and kind != 'mesh_glb' and not kind.endswith('_preview'):
            continue
        elif artifact_id:
            path = '/v1/3d/tasks/%s/artifacts/%s' % (
                urlparse.quote(str(job_id), safe=''), urlparse.quote(str(artifact_id), safe=''))
            content = _job_request(local_job_id, 'GET', base, key, path, model=model,
                               timeout=600, raw=True)
        else:
            continue
        value = (art.get('filename') or kind + '.bin', content,
                 art.get('mime_type') or 'application/octet-stream')
        downloaded.append({'kind': kind, 'artifact_id': artifact_id, 'value': value})
        if kind == 'mesh_glb':
            have['mesh'] = have['mesh_glb'] = value
        elif kind.startswith('material'):
            have['material'] = have['material_artifact'] = value
        elif kind.startswith('image') or value[2].startswith('image/'):
            have['image'] = value
        elif kind.endswith('_preview'):
            have['preview'] = value
        elif kind:
            have[kind] = have[kind + '_artifact'] = value
    return downloaded


def _portable_basename(value):
    return str(value or '').replace('\\', '/').rsplit('/', 1)[-1]


def _validate_glb(blob):
    if not isinstance(blob, bytes) or len(blob) < 20:
        raise ValueError('The returned GLB is empty or truncated')
    magic, version, declared = struct.unpack_from('<4sII', blob)
    if magic != b'glTF' or version != 2 or declared != len(blob):
        raise ValueError('The returned GLB has an invalid header or length')
    offset = 12
    document = None
    while offset < len(blob):
        if offset + 8 > len(blob):
            raise ValueError('The returned GLB has a truncated chunk header')
        length, kind = struct.unpack_from('<II', blob, offset)
        offset += 8
        if length % 4 or offset + length > len(blob):
            raise ValueError('The returned GLB has an invalid chunk length')
        if document is None:
            if kind != 0x4E4F534A:
                raise ValueError('The returned GLB must start with a JSON chunk')
            document = json.loads(blob[offset:offset + length].decode('utf-8'))
        offset += length
    if not isinstance(document, dict) or document.get('asset', {}).get('version') != '2.0':
        raise ValueError('The returned GLB has no glTF 2.0 asset metadata')
    return document


def _glb_geometry_counts(document):
    """Counts only; topology analysis belongs to the separate diagnostic tool."""
    accessors = document.get('accessors', [])
    triangles, vertices = 0, 0
    for mesh in document.get('meshes', []):
        for primitive in mesh.get('primitives', []):
            position = primitive.get('attributes', {}).get('POSITION')
            if isinstance(position, int) and 0 <= position < len(accessors):
                count = int(accessors[position].get('count', 0))
                vertices += count
                if primitive.get('mode', 4) == 4:
                    index = primitive.get('indices')
                    triangles += (int(accessors[index].get('count', 0)) if isinstance(index, int)
                                  and 0 <= index < len(accessors) else count) // 3
    return {'triangles': triangles, 'vertices_with_seams': vertices}


def _reported_controls(state):
    """Keep allowlisted server metadata separately from the request.

    These values are merely server-reported, not proof of actual execution.
    Never serialize the whole response, which may contain embedded assets.
    """
    allowed = {'seed', 'resolved_seed', 'effective_seed', 'output_precision',
               'inference_quality', 'asset_quality', 'pipeline_type',
               'resolution', 'grid_size', 'remesh_resolution', 'simplify',
               'remesh_closing_iterations', 'project_geometry', 'target_faces',
               'texture_size', 'bake_projection'}
    result = {}
    containers = [('task', state), ('result', state.get('result') or {})]
    containers.append(('output', (state.get('result') or {}).get('output') or {}))
    for name, container in containers:
        if not isinstance(container, dict):
            continue
        candidates = [(name, container)] + [
            (name + '.' + key, container.get(key)) for key in
            ('metadata', 'parameters', 'params', 'effective_params', 'resolved_params')]
        for location, values in candidates:
            if not isinstance(values, dict):
                continue
            selected = {key: value for key, value in values.items()
                        if key in allowed and isinstance(value, (str, int, float, bool, type(None)))}
            if selected:
                result[location] = selected
    return result


def _save_stage_previews(output, stage, tid, base, key, model, directory, local_job_id=None):
    """Optional diagnostic copies only; never change the generated geometry."""
    records = []
    for index, artifact in enumerate(output.get('artifacts') or []):
        _check_cancelled(local_job_id)
        kind = str(artifact.get('artifact_type') or '')
        if not kind.endswith('_preview'):
            continue
        record = {'artifact_type': kind, 'artifact_id': artifact.get('artifact_id')}
        try:
            payload = output.get(artifact.get('payload_key') or '')
            if isinstance(payload, str) and payload:
                blob = base64.b64decode(payload, validate=True)
            elif artifact.get('artifact_id'):
                path = '/v1/3d/tasks/%s/artifacts/%s' % (
                    urlparse.quote(str(tid), safe=''), urlparse.quote(str(artifact['artifact_id']), safe=''))
                blob = _job_request(local_job_id, 'GET', base, key, path, model=model, timeout=60, raw=True)
            else:
                record['status'] = 'no_downloadable_payload'
                records.append(record)
                continue
            document = _validate_glb(blob)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / ('%s_%02d.glb' % (stage, index))
            path.write_bytes(blob)
            record.update(status='saved', file=path.name, sha256=hashlib.sha256(blob).hexdigest(),
                          geometry=_glb_geometry_counts(document))
        except InterruptedError:
            raise
        except Exception as exc:
            # A failed optional download must not discard a successful model.
            record.update(status='unavailable', error_type=type(exc).__name__)
        records.append(record)
    return records


def _write_manifest(path, manifest):
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=True, allow_nan=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _generate_worker(jid, settings):
    base, key, model = settings['base'], settings['key'], settings['model']
    manifest_path, manifest = None, {}
    started_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    try:
        _job_set(jid, _connection=(base, key, model), worker_active=True)
        _check_cancelled(jid)
        output_dir = Path(settings['output_dir']).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / ('tiiny_%s_%s.glb' % (
            'trellis' if 'TRELLIS' in model else 'hunyuan', jid[:12]))
        manifest_path = target.with_suffix('.json')
        manifest = {'report_version': 3, 'addon_version': '.'.join(map(str, EXTENSION_VERSION)),
                    'development_build': DEVELOPMENT_BUILD, 'started_at_utc': started_at,
                    'model': model, 'quality_requested': settings.get('quality', 'STANDARD'),
                    'status': 'running', 'stage_diagnostics': [], 'stages': [],
                    'network_grace_seconds': settings.get('network_grace_seconds', _NETWORK_GRACE_SECONDS)}
        _save_job_report(jid, manifest_path, manifest)
        _job_set(jid, state='running', stage='capabilities', progress=0,
                 message='Fetching fresh capabilities for selected model')
        # Fetch on every generation, but permit Stop during DNS/connect/read.
        caps = _bounded_call(lambda: _get_caps(base, key, model), timeout=26, jid=jid)
        identity = _identity(base, key)
        with _LOCK:
            _CAPABILITIES[(identity, model)] = {'caps': caps, 'checked_at': time.time()}
        stages = caps.get('stages') or []
        requested_quality = settings.get('quality', 'STANDARD')
        effective_quality = _effective_quality(caps, requested_quality, settings['texture'])
        settings['quality'] = effective_quality
        if requested_quality != effective_quality:
            _job_set(jid, message='Preset %s unavailable on Tiiny; using Standard' % requested_quality)
        if settings['texture'] and any(s not in stages for s in ('texture', 'export')):
            raise RuntimeError('PBR requested, but model has no texture/export stage')
        cleanup = _geometry_profile(settings)
        plan, params_by_stage = _execution_plan(caps, settings, effective_quality)
        manifest.update(capabilities=caps, capabilities_sha256=_caps_digest(caps),
                        params_by_stage=params_by_stage, stages=plan)
        _save_job_report(jid, manifest_path, manifest)
        _check_trellis_resolution(caps, settings, params_by_stage)
        need_simplify = 'simplify' in plan
        specs = caps.get('stage_specs') or {}
        stage_inputs = caps.get('inputs') or {}
        use_refs = bool(caps.get('input_refs'))
        image_path = Path(settings['image'])
        prep_report = None
        if settings.get('auto_prepare'):
            _job_set(jid, stage='prepare', message='Preparing reference image before 3D generation')
            path, signature, prep_report = _bounded_call(
                lambda: _prepare_image(settings, lambda msg: _job_set(jid, stage='prepare', message=msg)),
                timeout=1500, jid=jid)
            _check_cancelled(jid)
            image_path = path
            _PENDING_PREVIEW.put((str(path), signature, prep_report))
        source_data = image_path.read_bytes()
        mimetype = mimetypes.guess_type(str(image_path))[0] or 'image/png'
        have = {'image': (image_path.name, source_data, mimetype)}
        refs = {}
        output_dir = Path(settings['output_dir']).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / ('tiiny_%s_%s.glb' % (
            'trellis' if 'TRELLIS' in model else 'hunyuan', jid[:12]))
        manifest_path = target.with_suffix('.json')
        preview_dir = output_dir / 'diagnostics' / target.stem
        prep_summary = dict(prep_report) if prep_report else None
        if prep_summary and prep_summary.get('mask'):
            prep_summary['mask'] = _portable_basename(prep_summary['mask'])
        manifest = {
            'report_version': 3, 'addon_version': '.'.join(map(str, EXTENSION_VERSION)),
            'development_build': DEVELOPMENT_BUILD, 'started_at_utc': started_at,
            'network_grace_seconds': settings.get('network_grace_seconds', _NETWORK_GRACE_SECONDS),
            'allow_trellis_1024': bool(settings.get('allow_trellis_1024', False)),
            'status': 'running', 'model': model,
            'quality': effective_quality, 'quality_requested': requested_quality,
            'base_preset': _base_preset(settings, effective_quality),
            'quality_source': ('Tiiny API capabilities + explicit client recipe'
                               if _global_preset(caps, _base_preset(settings, effective_quality))
                               else 'Tiiny server defaults + explicit overrides'),
            'pbr_textures_requested': settings['texture'],
            'seed': settings['seed'], 'seed_sent': settings['seed'] if settings['seed'] >= 0 else None,
            'seed_note': 'A missing seed is server-selected; no effective seed is assumed.',
            'trellis_geometry_cleanup': cleanup,
            'target_faces': settings['faces'], 'manual_overrides': _manual_overrides(settings, effective_quality),
            'params_by_stage': params_by_stage, 'stages': plan,
            'stage_diagnostics': [],
            'capabilities_sha256': _caps_digest(caps), 'capabilities': caps,
            'source_image': _portable_basename(settings['image']),
            'source_sha256': hashlib.sha256(Path(settings['image']).read_bytes()).hexdigest(),
            'prepared_image': image_path.name if prep_report else None,
            'input_image_sha256': hashlib.sha256(source_data).hexdigest(),
            'input_image_bytes': len(source_data), 'preparation': prep_summary,
            'stage_previews_requested': bool(settings.get('save_stage_previews')),
        }
        _save_job_report(jid, manifest_path, manifest)
        # Geometry cleanup is a potentially expensive server task. Give it
        # a visible share of the stage-weighted UI progress when enabled.
        weights = ({'shape': 37, 'simplify': 23, 'texture': 32, 'export': 8}
                   if need_simplify else {'shape': 45, 'simplify': 4, 'texture': 45, 'export': 6})
        weight_total = sum(weights[s] for s in plan)
        finished = 0
        stage_trace = manifest['stage_diagnostics']
        final_downloads = []
        for stage in plan:
            stage_started_at = time.monotonic()
            transient_poll_failures = 0
            _check_cancelled(jid)
            params = params_by_stage[stage]
            files, input_refs = {}, {}
            for name in (stage_inputs.get(stage) or STAGE_INPUTS[stage]):
                if use_refs and name in refs:
                    input_refs[name] = refs[name]
                elif name in have:
                    files[STAGE_FIELDS.get(name, name)] = have[name]
            if stage == 'shape' and 'image' not in files and 'image' not in input_refs:
                raise RuntimeError('Device shape stage does not accept image input')
            required = (specs.get(stage) or {}).get('required_inputs') or []
            for name in required:
                if name not in input_refs and STAGE_FIELDS.get(name, name) not in files:
                    raise RuntimeError('Missing required input %s for %s stage' % (name, stage))
            fields = {'stage': stage, 'params': json.dumps(params)}
            if input_refs:
                fields['input_refs'] = json.dumps(input_refs)
            _job_set(jid, stage=stage, message='Starting %s stage' % stage,
                     progress=int(finished * 97 / weight_total))
            trace = {'stage': stage, 'status': 'submitting', 'sent_params': dict(params),
                     'input_refs': dict(input_refs),
                     'file_inputs': {name: {'filename': _portable_basename(value[0]),
                                           'bytes': len(value[1]), 'sha256': hashlib.sha256(value[1]).hexdigest()}
                                     for name, value in files.items()}}
            stage_trace.append(trace)
            _save_job_report(jid, manifest_path, manifest)
            task = _job_request(jid, 'POST', base, key, '/v1/3d/tasks', model=model,
                            fields=fields, files=files, timeout=180)
            tid = task.get('task_id')
            if not tid:
                raise RuntimeError('No task_id returned for stage %s' % stage)
            trace.update(task_id=tid, status='running')
            _job_set(jid, task_id=tid, remote_task_status='running')
            _save_job_report(jid, manifest_path, manifest)
            last_response_at = time.monotonic()
            grace = max(0.05, float(settings.get('network_grace_seconds', _NETWORK_GRACE_SECONDS)))
            while True:
                _check_cancelled(jid)
                try:
                    state = _job_request(jid, 'GET', base, key,
                                     '/v1/3d/tasks/%s' % urlparse.quote(str(tid), safe=''),
                                     model=model, timeout=min(35, max(0.05, grace - (time.monotonic() - last_response_at))))
                    last_response_at = time.monotonic()
                    _job_set(jid, connection_lost=False, last_response_at=last_response_at)
                except RuntimeError as exc:
                    msg = str(exc)
                    if ('Cannot reach Tiiny:' in msg or 'HTTP 502' in msg or
                            'HTTP 503' in msg or 'HTTP 504' in msg):
                        transient_poll_failures += 1
                        silence = time.monotonic() - last_response_at
                        trace.update(status='waiting_for_connection',
                                     elapsed_seconds=round(time.monotonic() - stage_started_at, 1),
                                     transient_poll_failures=transient_poll_failures,
                                     seconds_without_response=round(silence, 1),
                                     last_network_error=_safe_diagnostic_text(msg, settings))
                        _save_job_report(jid, manifest_path, manifest)
                        if silence >= grace:
                            _start_remote_cancel(jid, base, key, model, tid)
                            raise RuntimeError('%s: no response for %d seconds. Local waiting stopped; '
                                               'the device task state is unknown. Check Tiiny before restarting.'
                                               % (stage, int(silence))) from exc
                        _job_set(jid, connection_lost=True, message='No response from Tiiny (%ds); Stop is available' % int(silence))
                        _cancel_event(jid).wait(min(_POLL_INTERVAL, max(0.0, grace - silence)))
                        continue
                    raise
                _check_cancelled(jid)
                progress = max(0, min(100, float(state.get('progress') or 0)))
                trace.update(status=state.get('status') or 'running',
                             elapsed_seconds=round(time.monotonic() - stage_started_at, 1),
                             transient_poll_failures=transient_poll_failures,
                             last_server_progress=progress,
                             last_server_message=_safe_diagnostic_text(state.get('message'), settings),
                             last_response_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                             server_reported_controls=_reported_controls(state))
                _save_job_report(jid, manifest_path, manifest)
                _job_set(jid, progress=int((finished + weights[stage] * progress / 100) * 97 / weight_total),
                         message='%s: %s' % (stage, state.get('message') or state.get('status')))
                if state.get('status') in ('completed', 'failed', 'error', 'cancelled'):
                    break
                _cancel_event(jid).wait(_POLL_INTERVAL)
            if state.get('status') != 'completed':
                trace.update(status=state.get('status'), elapsed_seconds=round(time.monotonic() - stage_started_at, 1))
                raise RuntimeError('%s: %s' % (stage, state.get('error') or state.get('message') or state.get('status')))
            output = (state.get('result') or {}).get('output') or {}
            _job_set(jid, remote_task_status='completed')
            final_downloads = _artifact_output(output, stage, plan[-1], use_refs, tid, base, key, model, refs, have, local_job_id=jid)
            # Minimal non-sensitive diagnostic trace, especially for stages
            # whose processing on Tiiny may stall before a successful export.
            reported_artifacts = output.get('artifacts') or []
            trace.update({
                'status': 'completed',
                'elapsed_seconds': round(time.monotonic() - stage_started_at, 1),
                'transient_poll_failures': transient_poll_failures,
                'artifact_types': [str(v.get('artifact_type')) for v in reported_artifacts
                                   if isinstance(v, dict)],
                'artifacts': [{'artifact_type': a.get('artifact_type'), 'artifact_id': a.get('artifact_id')}
                              for a in reported_artifacts if isinstance(a, dict)],
                'server_reported_controls': _reported_controls(state),
            })
            if settings.get('save_stage_previews'):
                trace['saved_previews'] = _save_stage_previews(output, stage, tid, base, key, model, preview_dir, local_job_id=jid)
            finished += weights[stage]
            _job_set(jid, stage=stage, progress=int(finished * 97 / weight_total), task_id='')
            _save_job_report(jid, manifest_path, manifest)
        candidates = [a for a in final_downloads if a['kind'] == 'mesh_glb']
        if not candidates and not settings['texture']:
            candidates = [a for a in final_downloads if a['kind'].endswith('_preview')]
        if not candidates:
            raise RuntimeError('The final stage returned no requested GLB; an earlier mesh will not be substituted')
        chosen = candidates[0]
        blob = chosen['value'][1]
        document = _validate_glb(blob)
        _check_cancelled(jid)
        target.write_bytes(blob)
        manifest.update({
            'status': 'saved',
            'glb_counts': _glb_counts(blob),
            'geometry_counts': _glb_geometry_counts(document),
            'output_sha256': hashlib.sha256(blob).hexdigest(),
            'selected_output': {'stage': plan[-1], 'task_id': stage_trace[-1].get('task_id'),
                                'artifact_id': chosen['artifact_id'], 'artifact_type': chosen['kind']},
        })
        _save_job_report(jid, manifest_path, manifest)
        _check_cancelled(jid)
        _job_set(jid, state='importing', stage='import', progress=99,
                 message='GLB saved: importing in Blender', filename=str(target),
                 glb_counts=_glb_counts(blob), params_by_stage=manifest['params_by_stage'])
        _PENDING_IMPORT.put((jid, str(target)))
    except InterruptedError as exc:
        job = _job_get(jid)
        if job.get('task_id') and job.get('remote_task_status') != 'completed':
            _start_remote_cancel(jid, base, key, model, job['task_id'])
        if manifest_path:
            manifest.update(status='cancelled', failure_stage=_job_get(jid).get('stage'))
            try:
                _save_job_report(jid, manifest_path, manifest)
            except OSError:
                pass
        _job_set(jid, state='cancelled', message='Stopped locally', error=str(exc))
    except Exception as exc:
        job = _job_get(jid)
        _job_set(jid, local_wait_stopped=True)
        if job.get('task_id') and job.get('remote_task_status') not in ('completed', 'failed', 'cancelled'):
            _start_remote_cancel(jid, base, key, model, job['task_id'])
        if manifest_path:
            manifest.update(status='failed', failure_stage=_job_get(jid).get('stage'), error_type=type(exc).__name__,
                            error=_safe_diagnostic_text(exc, settings))
            try:
                _save_job_report(jid, manifest_path, manifest)
            except (OSError, ValueError, TypeError):
                pass
        _job_set(jid, state='failed', message=str(exc), error=str(exc))
    finally:
        _job_set(jid, worker_active=False)


def _begin_job(settings):
    settings = dict(settings)
    base = _normalize_base(settings['base'])
    if not settings['key'].strip():
        raise ValueError('Enter Tiiny API key')
    src = Path(bpy.path.abspath(settings['image']))
    if not src.is_file():
        raise ValueError('Select an existing reference image')
    if src.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError('Supported images: PNG / JPG / WEBP')
    if src.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('Image is too large: limit 25 MB')
    with _LOCK:
        if _status_get('prep').get('state') == 'working':
            raise RuntimeError('Image preparation is running; generate after it finishes')
        if any(j.get('submission_pending') for j in _JOBS.values()):
            raise RuntimeError('An earlier submission is still resolving. Check Tiiny before starting another job.')
        if any(j.get('state') in ('queued', 'running', 'importing') or j.get('worker_active')
               for j in _JOBS.values()):
            raise RuntimeError('A 3D generation task is already running')
        jid = uuid.uuid4().hex
        _JOBS[jid] = dict(state='queued', stage='queued', message='Queued',
                          progress=0, cancel=False, model=settings['model'])
    settings['image'] = str(src)
    settings['base'] = base
    threading.Thread(target=_generate_worker, args=(jid, settings), daemon=True).start()
    return jid


# ------------------------------ Blender UI --------------------------------

class TIINY_PG_Control(bpy.types.PropertyGroup):
    model_id: StringProperty(options={'HIDDEN'})
    stage: StringProperty(options={'HIDDEN'})
    param_name: StringProperty(options={'HIDDEN'})
    label: StringProperty()
    help_text: StringProperty()
    datatype: StringProperty()
    choices_json: StringProperty()
    default_json: StringProperty()
    min_json: StringProperty()
    max_json: StringProperty()
    enabled: BoolProperty(name='Override', default=False,
                          description='Replace the preset value with this advertised model parameter')
    value_enum: EnumProperty(name='Value', items=_enum_choices)
    value_int: IntProperty(name='Value', default=0)
    value_float: FloatProperty(name='Value', default=0.0)
    value_bool: BoolProperty(name='Value', default=False)  # retained for migration
    value_bool_choice: EnumProperty(name='Mode', items=(
        ('DEFAULT', 'Inherit', 'Use the selected preset or, when omitted by it, the server default'),
        ('TRUE', 'Enabled', 'Explicitly send true'),
        ('FALSE', 'Disabled', 'Explicitly send false'),
    ), default='DEFAULT')
    value_text: StringProperty(name='Value', default='')


def _invalidate_prepared(props):
    props.prepared_preview = None
    props.prepared_image = ''
    props.prepared_signature = ''
    _clear_thumbnail('prepared')
    _status_set('prep', state='not_ready', signature='', message='Prepare an image to inspect it')


def _queue_auto_prepare(context):
    global _AUTO_PREP_REQUEST
    try:
        if context is None or not getattr(context, 'scene', None):
            return
        props = context.scene.tiiny_settings
        if not _tools_enabled(context.preferences.addons[__name__].preferences) or not props.auto_prepare or not _accepted_image(context) or not Path(bpy.path.abspath(props.image)).is_file():
            _AUTO_PREP_REQUEST = None
            return
        settings = _settings_snapshot(context)
        # Debounce rapid GUI updates; the worker runs after a short idle period.
        _AUTO_PREP_REQUEST = (time.monotonic() + 0.6, settings)
        _status_set('prep', state='queued', signature=_prep_signature(settings), phase=1,
                    started_at=time.monotonic(), message='Preparing reference image queued...')
    except (RuntimeError, KeyError, AttributeError, OSError):
        pass


def _on_prep_option_change(self, context):
    _invalidate_prepared(self)
    _queue_auto_prepare(context)


def _load_source_preview(props, context):
    _invalidate_prepared(props)
    props.original_preview = None  # legacy PointerProperty is no longer used for thumbnails
    _clear_thumbnail('original')
    if props.image:
        try:
            _file_thumbnail('original', bpy.path.abspath(props.image))
        except (AttributeError, RuntimeError, ValueError, OSError):
            pass
    _queue_auto_prepare(context)


def _settings_snapshot(context):
    props = context.scene.tiiny_settings
    prefs = context.preferences.addons[__name__].preferences
    tools_enabled = _tools_enabled(prefs)
    return {
        'base': prefs.tiiny_api_url, 'key': prefs.tiiny_api_key,
        'model': prefs.tiiny_model, 'image': bpy.path.abspath(_accepted_image(context)) if _accepted_image(context) else '',
        'texture': props.texture, 'quality': props.quality,
        'faces': props.faces, 'seed': props.seed,
        'trellis_postprocess': (getattr(props, 'trellis_postprocess', 'OFF') if 'TRELLIS' in prefs.tiiny_model else 'OFF'),
        'custom_base': getattr(props, _model_property(prefs.tiiny_model, 'custom_base'), 'NATIVE'),
        'manual_overrides': _overrides_active(props, prefs.tiiny_model),
        'custom': _custom_snapshot(props, prefs.tiiny_model) if _overrides_active(props, prefs.tiiny_model) else [],
        'save_stage_previews': getattr(props, 'save_stage_previews', False),
        'allow_trellis_1024': bool(getattr(props, 'allow_trellis_1024', False)),
        'network_grace_seconds': getattr(prefs, 'network_grace_seconds', _NETWORK_GRACE_SECONDS),
        'output_dir': bpy.path.abspath(prefs.output_dir),
        'use_local_image_tools': tools_enabled,
        'auto_prepare': bool(tools_enabled and props.auto_prepare),
        'remove_bg': bool(tools_enabled and props.remove_bg),
        'clean_mask': bool(getattr(props, 'clean_mask', True)),
        'clean_existing_alpha': bool(getattr(props, 'clean_existing_alpha', False)),
        'segment_model': props.segment_model, 'smart_crop': props.smart_crop,
        'canvas': props.canvas, 'occupancy': props.occupancy,
        'upscale': props.upscale,
    }


def _draw_image_preview(layout, filepath, title, slot, context=None):
    """Draw a static image thumbnail without an on-click preview selector.

    UILayout.template_icon displays a large *passive* image. Blender does not
    expose a tooltip argument on that widget, so an adjacent unobtrusive info
    button provides the full path on hover (and copies the path on click).
    """
    col = layout.column(align=True)
    col.label(text=title)
    if not filepath or not Path(filepath).is_file():
        busy = _status_get('prep').get('state') in ('queued', 'working', 'waiting_preview')
        label = ('Preparing...' if busy else 'Not prepared') if slot == 'prepared' else 'Choose image'
        col.label(text=label, icon='TIME' if slot == 'prepared' and busy else 'IMAGE_DATA')
        return
    thumb = _file_thumbnail(slot, filepath)
    if thumb is not None and thumb.icon_id > 0:
        row = col.row(align=True)
        row.template_icon(thumb.icon_id, scale=5.0)
        info = row.column(align=True)
        op = info.operator('tiiny.copy_image_path', text='', icon='INFO', emboss=False)
        op.filepath = str(Path(filepath).resolve())
    else:
        col.label(text='Thumbnail loading...', icon='TIME')


class TIINY_OT_CopyImagePath(bpy.types.Operator):
    """Tooltip target next to the static thumbnail; never opens a preview."""
    bl_idname = 'tiiny.copy_image_path'
    bl_label = 'Image file location'
    bl_description = 'Show the full image file location; click to copy its path'
    bl_options = {'INTERNAL'}

    filepath: StringProperty(name='Image file path', default='', options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return 'File: ' + str(getattr(properties, 'filepath', '') or '(no file)') + '\nClick to copy path'

    def execute(self, context):
        if not self.filepath:
            return {'CANCELLED'}
        context.window_manager.clipboard = self.filepath
        self.report({'INFO'}, 'Image path copied to clipboard')
        return {'FINISHED'}


class TIINY_PG_Settings(bpy.types.PropertyGroup):
    allow_trellis_1024: BoolProperty(
        name='Allow experimental 1024', default=False, options={'SKIP_SAVE'},
        description='Permit TRELLIS shape resolutions above 512 for this session. 1024 caused a loss of device connectivity in testing. Maximum remains 1024; this switch does not change its parameters.')
    image: StringProperty(name='Source Image', default='', options={'SKIP_SAVE'},
                          description='Session-only source image; select it explicitly',
                          update=_load_source_preview)
    original_preview: PointerProperty(name='Source preview', type=bpy.types.Image)
    prepared_preview: PointerProperty(name='Prepared preview', type=bpy.types.Image)
    prepared_image: StringProperty(default='', options={'HIDDEN','SKIP_SAVE'})
    prepared_signature: StringProperty(default='', options={'HIDDEN','SKIP_SAVE'})
    auto_prepare: BoolProperty(name='Auto prepare before generation', default=True,
                               update=_on_prep_option_change,
                               description='Auto prepare on image selection and before 3D generation')
    remove_bg: BoolProperty(name='Remove background', default=True,
                            update=_on_prep_option_change,
                            description='Automatically skip segmentation if the image already has transparency')
    clean_mask: BoolProperty(name='Clean soft background', default=True,
                            update=_on_prep_option_change,
                            description='Remove weak residue from new AI masks while protecting edges and connected fine strands. Disable for glass or intentional broad transparency; no automatic mask is perfect.')
    clean_existing_alpha: BoolProperty(name='Clean existing alpha', default=False,
                            update=_on_prep_option_change,
                            description='Also clean an already transparent source PNG. Off preserves its supplied alpha; enable explicitly to clean an older prepared image.')
    segment_model: EnumProperty(name='Local background remover',items=(
        ('isnet-general-use','ISNet general (recommended)','CPU, good general objects'),
        ('u2netp','U2NetP fast','Small local model, less detail on edges'),
        ('birefnet-general-lite','BiRefNet Lite','Better edge fidelity at higher CPU cost'),
        ('birefnet-general','BiRefNet General','Larger model, slower CPU segmentation'),
    ), default='isnet-general-use', update=_on_prep_option_change)
    smart_crop: BoolProperty(name='Crop to object', default=True,
                             update=_on_prep_option_change,
                             description='Crop to alpha-mask bounding box; never guess object bounds without a mask')
    canvas: EnumProperty(name='Image canvas size',items=(
        ('AUTO','Auto (recommended)','512 for Hunyuan, 1024 for TRELLIS; preprocessing only'),
        ('512','512 x 512','Client-side output PNG canvas size'),
        ('768','768 x 768','Client-side output PNG canvas size'),
        ('1024','1024 x 1024','Client-side output PNG canvas size'),
    ),default='AUTO', update=_on_prep_option_change)
    occupancy: FloatProperty(name='Object size in frame', min=0.5,max=0.95,default=0.85,
                             subtype='FACTOR', update=_on_prep_option_change,
                             description='Keep object about 85% of image width/height')
    upscale: BoolProperty(name='Upscale small images', default=True,
                          update=_on_prep_option_change,
                          description='Fill chosen canvas with interpolation; cannot invent missing details')
    texture: BoolProperty(name='Generate PBR textures', default=True,
                          description='Generate full color materials; uncheck for shape-only GLB')
    quality: EnumProperty(name='Quality', items=(
        ('STANDARD', 'Standard', 'TRELLIS: advertised 512/balance tier. Hunyuan: Tiiny defaults'),
        ('DRAFT', 'Draft', 'Select fastest supported quality controls (if advertised by model)'),
        ('MAXIMUM', 'Maximum', 'Highest advertised generation tier; slower and not guaranteed to look better'),
        ('CUSTOM', 'Custom', 'Choose a base preset and edit advertised controls in Advanced'),
    ), default='STANDARD')
    hunyuan_quality: StringProperty(default='STANDARD', options={'HIDDEN'})
    trellis_quality: StringProperty(default='STANDARD', options={'HIDDEN'})
    hunyuan_overrides: BoolProperty(name='Enable manual overrides', default=False,
                                   description='Apply the checked Hunyuan controls on top of any quality preset')
    trellis_overrides: BoolProperty(name='Enable manual overrides', default=False,
                                   description='Apply the checked TRELLIS controls on top of any quality preset')
    hunyuan_custom_base: EnumProperty(name='Custom base', items=CUSTOM_BASE_ITEMS, default='NATIVE')
    trellis_custom_base: EnumProperty(name='Custom base', items=CUSTOM_BASE_ITEMS, default='NATIVE')
    seed: IntProperty(name='Seed', min=-1, default=-1,
                      description='Use a fixed value such as 42 for comparisons. -1 omits the seed; the server chooses and may not report it')
    faces: IntProperty(name='Target polygons', min=0, max=2000000, default=0,
                       description='Mesh triangle budget, not human faces. 0 omits the budget; an active surface mode may still process geometry. Device limits are checked before generation')
    trellis_postprocess: EnumProperty(name='TRELLIS surface', items=(
        ('OFF', 'Off (original)', 'Skip the geometry stage unless a polygon budget or manual override requires it'),
        ('PRESERVE512', 'Preserve detail 512 (experimental)', 'Remesh 512, one closing pass, no target decimation. Geometry-stage projection is disabled; Tiiny export may independently enable it. Closed open edges in one test, but surface rings remained'),
        ('DEFAULT', 'Tiiny cleanup (legacy)', 'Run the geometry stage with decimation enabled and server defaults'),
        ('REMESH256', 'Remesh 256 + decimate (legacy)', 'Previous experimental recipe: remesh 256, one closing pass, decimation enabled'),
        ('REMESH512', 'Remesh 512 + decimate (legacy)', 'Previous experimental recipe: remesh 512, one closing pass, decimation enabled'),
    ), default='OFF', description='Independent of generation quality. Remeshing changes shape; no mode guarantees closed geometry')
    save_stage_previews: BoolProperty(name='Save intermediate meshes', default=False,
                                     description='Download advertised shape/geometry previews into a diagnostics subfolder to locate defects before export; increases transfer size')
    show_request_preview: BoolProperty(name='Show effective request', default=False,
                                      description='Inspect the final stage parameters after presets and manual overrides are combined')
    controls: CollectionProperty(type=TIINY_PG_Control)
    last_schema: StringProperty(default='', options={'HIDDEN'})
    job_id: StringProperty(default='', options={'HIDDEN','SKIP_SAVE'})


def _draw_tool_management(layout, enabled=True):
    """Never hide Install, Remove or Clean Uninstall when setup reaches 100%."""
    busy = _image_tools_busy()
    actions = layout.row(align=True)
    install = actions.row(align=True)
    install.enabled = bool(enabled and not busy)
    install.operator('tiiny.install_tools', text='Install / Retry', icon='FILE_REFRESH')
    remove = actions.row(align=True)
    remove.enabled = not busy
    remove.operator('tiiny.remove_tools', text='Remove tools', icon='TRASH')
    clean = layout.row(align=True)
    clean.enabled = not busy
    clean.operator('tiiny.clean_uninstall',
                   text='Clean Uninstall (add-on + tools)', icon='TRASH')
    layout.label(text='Your images and GLB files are kept.', icon='INFO')


class TIINY_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    tiiny_api_url: StringProperty(name='Tiiny Address', default='http://tiinyhost.local',
                                  description='Local Tiiny base URL, without /v1')
    tiiny_api_key: StringProperty(name='Tiiny API Key', default='', subtype='PASSWORD',
                                  description='Saved in Blender preferences locally (unencrypted)')
    tiiny_model: EnumProperty(name='3D Engine', items=MODELS, default=MODELS[0][0],
                             update=_on_pref_model_change)
    network_grace_seconds: IntProperty(
        name='Lost connection limit (seconds)', default=_NETWORK_GRACE_SECONDS, min=30, max=3600,
        description='Stop local waiting after this long without a successful task-status response. A responding task is not stopped merely for taking a long time. Stop is always available.')
    use_local_image_tools: BoolProperty(
        name='Use local image tools', default=True, update=_on_local_tools_toggle,
        description='Install and use local background removal, crop and resize. Disable to send your image directly to Tiiny without local processing.')
    input_dir: StringProperty(name='Input image folder', subtype='DIR_PATH',
                              default=os.path.join(os.path.expanduser('~'),'Documents','Tiiny_3D'),
                              description='Starting directory for Choose Image; not created until needed')
    output_dir: StringProperty(name='Output models folder', subtype='DIR_PATH',
                               default=os.path.join(os.path.expanduser('~'),'Documents','Tiiny_3D'),
                               update=_on_output_folder_change,
                               description='Prepared PNG subfolder and final GLB will be saved here, not elsewhere')

    def draw(self, context):
        box = self.layout.box()
        box.label(text='Pocket Lab connection',icon='NETWORK_DRIVE')
        box.prop(self,'tiiny_api_url',text='Address')
        box.prop(self,'tiiny_api_key',text='API Key')
        box.operator('tiiny.check_connection',text='Check connection / API key',icon='LINKED')
        _draw_status(box,'connection',self)
        box.prop(self, 'network_grace_seconds', text='Lost connection limit (s)')
        modelbox=self.layout.box()
        modelbox.label(text='3D model on Tiiny',icon='OUTLINER_OB_MESH')
        modelbox.prop(self,'tiiny_model',text='Model')
        modelbox.operator('tiiny.check_model',text='Refresh selected model settings',icon='FILE_REFRESH')
        _draw_status(modelbox,'model',self,self.tiiny_model)
        paths=self.layout.box()
        paths.label(text='Input and output folders',icon='FILE_FOLDER')
        paths.prop(self,'input_dir',text='Incoming photos')
        paths.prop(self,'output_dir',text='Generated models')
        paths.label(text='Folders are created when needed.',icon='INFO')
        prepinfo = self.layout.box()
        prepinfo.label(text='Optional local image tools', icon='IMAGE_DATA')
        prepinfo.prop(self, 'use_local_image_tools', text='Use local image tools')
        if self.use_local_image_tools:
            if _setup_ready() and not _setup_in_progress() and _status_get('setup').get('state') != 'error':
                prepinfo.label(text='Installed and cached', icon='CHECKMARK')
            else:
                _draw_local_setup(prepinfo, compact=True)
        else:
            prepinfo.label(text='Direct image mode', icon='INFO')
            prepinfo.label(text='No local preparation is used.')
            if _setup_in_progress():
                prepinfo.label(text='Previous install is finishing.', icon='TIME')
        _draw_tool_management(prepinfo, enabled=self.use_local_image_tools)
        installed = _prep_install_status()
        if installed['log'].is_file():
            prepinfo.operator('tiiny.open_prep_log', text='View local setup log', icon='TEXT')
        self.layout.label(text='Local Tiiny API only.',icon='INFO')
        self.layout.label(text='API key is stored unencrypted.',icon='INFO')


def _image_tools_busy():
    setup = _status_get('setup').get('state') in ('working','queued') or (
        _SETUP_THREAD is not None and _SETUP_THREAD.is_alive())
    prep = _status_get('prep').get('state') in ('working','queued','waiting_preview')
    with _LOCK:
        jobs = any(v.get('state') in ('queued','running','importing') for v in _JOBS.values())
    return setup or prep or jobs


def _remove_private_tools():
    """Only remove our own fixed directory; never delete generic rembg data."""
    directory = _image_prep_home()
    if directory.name != 'TiinyAIForBlender' or directory.is_symlink():
        raise RuntimeError('Unsafe local tools location; refusing removal')
    if _image_tools_busy():
        raise RuntimeError('Finish active setup, image preparation and generation first')
    # Do not erase a user's input/output folder even if they configured it
    # inside the directory reserved for private tools.
    try:
        preferences = bpy.context.preferences.addons[__name__].preferences
        base = directory.resolve()
        for name in ('input_dir', 'output_dir'):
            user_dir = str(getattr(preferences, name, '') or '').strip()
            if user_dir:
                selected = Path(bpy.path.abspath(user_dir)).expanduser().resolve()
                if selected == base or base in selected.parents:
                    raise RuntimeError('%s is inside the local tools directory. Move your images/models and change that folder before cleanup.' % name)
    except (AttributeError, KeyError, TypeError):
        pass  # No Blender preference context in standalone offline tests.
    if directory.exists():
        shutil.rmtree(directory)
    _status_set('setup', state='not_ready', phase=0, message='Local image tools removed; reinstall is available')


class TIINY_OT_InstallTools(bpy.types.Operator):
    bl_idname = 'tiiny.install_tools'
    bl_label = 'Install local image tools'
    bl_description = 'Install or repair the private Python/rembg/ISNet environment in the background'

    def execute(self, context):
        if not _tools_enabled(context.preferences.addons[__name__].preferences):
            self.report({'WARNING'}, 'Enable local image tools in Preferences before installing')
            return {'CANCELLED'}
        _begin_background_setup()
        return {'FINISHED'}


class TIINY_OT_RemoveTools(bpy.types.Operator):
    bl_idname = 'tiiny.remove_tools'
    bl_label = 'Remove private image tools'
    bl_description = 'Delete only this add-on private Python and ISNet files (not images or shared model caches). Confirm first.'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        try:
            _remove_private_tools()
        except (OSError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, 'Private image tools removed. To test a first install, press Install / Retry tools.')
        return {'FINISHED'}


class TIINY_OT_CleanUninstall(bpy.types.Operator):
    bl_idname = 'tiiny.clean_uninstall'
    bl_label = 'Uninstall add-on and remove local tools'
    bl_description = 'Uninstall the add-on and delete only its private Python/rembg/ONNX directory; never remove reference photos or output models'

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if context.area is None or context.area.type != 'PREFERENCES':
            self.report({'ERROR'}, 'Use Clean Uninstall from Add-on Preferences')
            return {'CANCELLED'}
        try:
            _remove_private_tools()
        except (OSError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        # Blender extensions have a separate uninstall API. Resolve the
        # installed repository from the current module namespace instead of
        # assuming that the user's local repository has a fixed index.
        try:
            module_id = __name__
            if module_id.startswith('bl_ext.'):
                parts = module_id.split('.')
                if len(parts) != 3:
                    raise RuntimeError('Unexpected Blender extension namespace')
                repo_module, package_id = parts[1], parts[2]
                repos = context.preferences.extensions.repos
                repo_index = next((index for index, item in enumerate(repos)
                                   if item.module == repo_module), None)
                if repo_index is None:
                    raise RuntimeError('Cannot find the installed extension repository')
                result = bpy.ops.extensions.package_uninstall(
                    repo_index=repo_index, pkg_id=package_id)
            else:
                # Keep compatibility with the legacy module during manual tests.
                result = bpy.ops.preferences.addon_remove(module=module_id)
            if 'FINISHED' not in result and 'RUNNING_MODAL' not in result:
                raise RuntimeError('Blender did not confirm add-on removal')
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            self.report({'WARNING'},
                        'Local tools removed; finish uninstalling from Get Extensions: %s' % exc)
        return {'FINISHED'}


class TIINY_OT_OpenPrepLog(bpy.types.Operator):
    bl_idname = 'tiiny.open_prep_log'
    bl_label = 'Open local setup log'
    bl_description = 'Open the local image-preparation setup log; it contains no API key or image contents'

    def execute(self, context):
        log = _prep_setup_log_path()
        if not log.is_file():
            self.report({'INFO'}, 'No local preparation log yet. It is created on first setup.')
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=str(log))
        return {'FINISHED'}


class TIINY_OT_CopyJobMessage(bpy.types.Operator):
    """Provide the complete Tiiny status in a hover tooltip and clipboard."""
    bl_idname = 'tiiny.copy_job_message'
    bl_label = 'Full generation status'
    bl_description = 'Hover for full Tiiny job status; click to copy the message'
    bl_options = {'INTERNAL'}

    message: StringProperty(name='Message', default='', options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        detail = str(getattr(properties, 'message', '') or '')
        return ('Tiiny status: ' + detail[:900] + '\nClick to copy') if detail else 'No detailed status'

    def execute(self, context):
        if not getattr(context, 'window_manager', None):
            self.report({'WARNING'}, 'Clipboard is not available')
            return {'CANCELLED'}
        context.window_manager.clipboard = self.message
        self.report({'INFO'}, 'Full Tiiny status copied to clipboard')
        return {'FINISHED'}


class TIINY_OT_CheckConnection(bpy.types.Operator):
    bl_idname = 'tiiny.check_connection'
    bl_label = 'Check Pocket Lab API key'
    bl_description = 'Test TiinyOS authentication; automatically check the selected 3D engine afterwards'

    def execute(self, context):
        _start_probe('connection', context)
        return {'FINISHED'}


class TIINY_OT_CheckModel(bpy.types.Operator):
    bl_idname = 'tiiny.check_model'
    bl_label = 'Refresh 3D capabilities'
    bl_description = 'Fetch supported stages, parameter names, choices and limits from the selected Tiiny 3D model'

    def execute(self, context):
        _start_probe('model', context)
        return {'FINISHED'}


class TIINY_OT_SaveCaps(bpy.types.Operator):
    bl_idname = 'tiiny.save_capabilities'
    bl_label = 'Export model capabilities JSON'
    bl_description = 'Save advertised 3D stage/quality schema to a local JSON file (no API key included)'

    def execute(self, context):
        pref = context.preferences.addons[__name__].preferences
        props = context.scene.tiiny_settings
        record = _caps_get(_identity(pref.tiiny_api_url, pref.tiiny_api_key), pref.tiiny_model)
        if not record:
            self.report({'ERROR'}, 'Refresh selected model capabilities first')
            return {'CANCELLED'}
        try:
            destination = Path(bpy.path.abspath(pref.output_dir)).expanduser()
            destination.mkdir(parents=True, exist_ok=True)
            safe = 'trellis2' if 'TRELLIS' in pref.tiiny_model else 'hunyuan3d'
            path = destination / ('tiiny_capabilities_%s.json' % safe)
            path.write_text(json.dumps(record['caps'], indent=2, ensure_ascii=False), encoding='utf-8')
            self.report({'INFO'}, 'Saved capabilities: ' + str(path))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc)[:240])
            return {'CANCELLED'}


class TIINY_OT_SelectQuality(bpy.types.Operator):
    bl_idname = 'tiiny.select_quality'
    bl_label = 'Select Tiiny quality mode'
    bl_description = 'Choose only modes supported by currently advertised Tiiny model capabilities'
    mode: EnumProperty(items=(
        ('STANDARD', 'Standard', 'TRELLIS 512/balance; Hunyuan server defaults'),
        ('DRAFT', 'Draft', 'Use lowest confirmed quality controls'),
        ('MAXIMUM', 'Maximum', 'Request the highest advertised tier; visual quality is not guaranteed'),
        ('CUSTOM', 'Custom', 'Start from the current preset and edit advertised parameters'),
    ))

    def execute(self, context):
        props = context.scene.tiiny_settings
        pref = context.preferences.addons[__name__].preferences
        rec = _caps_get(_identity(pref.tiiny_api_url, pref.tiiny_api_key), pref.tiiny_model)
        allowed = _available_quality_modes(rec['caps'] if rec else None, props.texture)
        if self.mode not in allowed:
            self.report({'WARNING'}, 'This Tiiny backend does not advertise parameters for ' + self.mode)
            return {'CANCELLED'}
        if self.mode == 'CUSTOM' and props.quality in ('DRAFT', 'STANDARD', 'MAXIMUM'):
            setattr(props, _model_property(pref.tiiny_model, 'custom_base'), props.quality)
        props.quality = self.mode
        if 'TRELLIS' in pref.tiiny_model:
            props.trellis_quality = self.mode
        else:
            props.hunyuan_quality = self.mode
        return {'FINISHED'}


class TIINY_OT_SelectImage(bpy.types.Operator):
    bl_idname = 'tiiny.select_image'
    bl_label = 'Choose reference image'
    bl_description = 'Browse the input folder selected in Add-on Preferences; no photo is loaded automatically'
    filepath: StringProperty(name='Image',subtype='FILE_PATH')
    directory: StringProperty(name='Directory',subtype='DIR_PATH',options={'HIDDEN'})
    filter_glob: StringProperty(default='*.png;*.jpg;*.jpeg;*.webp',options={'HIDDEN'})

    def invoke(self, context, event):
        pref=context.preferences.addons[__name__].preferences
        folder=bpy.path.abspath(pref.input_dir)
        if not folder or not Path(folder).is_dir():
            folder=str(Path.home())
        self.directory=folder
        self.filepath=os.path.join(folder,'')
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        source=Path(bpy.path.abspath(self.filepath)).expanduser()
        if not source.is_file() or source.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):
            self.report({'ERROR'},'Choose an existing PNG, JPG or WEBP image')
            return {'CANCELLED'}
        _IMAGE_SELECTIONS[_scene_token(context.scene)] = str(source)
        context.scene.tiiny_settings.image = str(source)
        _load_source_preview(context.scene.tiiny_settings, context)
        return {'FINISHED'}


class TIINY_OT_ClearImage(bpy.types.Operator):
    bl_idname = 'tiiny.clear_image'
    bl_label = 'Clear reference image'
    bl_description = 'Forget the selected reference image; do not delete files on disk'

    def execute(self, context):
        _IMAGE_SELECTIONS.pop(_scene_token(context.scene), None)
        props = context.scene.tiiny_settings
        props.image = ''
        props.prepared_image = ''
        props.prepared_signature = ''
        _clear_thumbnail('original')
        _clear_thumbnail('prepared')
        _status_set('prep', state='not_ready', message='Select an image to start')
        return {'FINISHED'}


class TIINY_OT_PrepareImage(bpy.types.Operator):
    bl_idname = 'tiiny.prepare_image'
    bl_label = 'Prepare reference image'
    bl_description = 'Asynchronously mask, crop, center and resize the image; save a prepared PNG for inspection'

    def execute(self, context):
        settings = _settings_snapshot(context)
        if not settings.get('use_local_image_tools', True):
            self.report({'WARNING'}, 'Local image tools are disabled in Add-on Preferences')
            return {'CANCELLED'}
        image = Path(settings['image'])
        if not image.is_file():
            self.report({'ERROR'}, 'Choose an existing image first')
            return {'CANCELLED'}
        if _status_get('prep').get('state') == 'working':
            self.report({'WARNING'}, 'Image preparation is already in progress')
            return {'CANCELLED'}
        global _AUTO_PREP_REQUEST
        _AUTO_PREP_REQUEST = None
        _status_set('prep', state='working', phase=1, started_at=time.monotonic(),
                    message='Preparing reference image...')
        threading.Thread(target=_prep_worker,args=(settings,),daemon=True).start()
        self.report({'INFO'}, 'Preparing image in the background')
        return {'FINISHED'}


class TIINY_OT_RefreshThumbnails(bpy.types.Operator):
    bl_idname = 'tiiny.refresh_thumbnails'
    bl_label = 'Reload image thumbnails'
    bl_description = 'Reload image previews from disk without running segmentation or contacting Tiiny'

    def execute(self, context):
        props = context.scene.tiiny_settings
        source = _accepted_image(context)
        _clear_thumbnail('original')
        _clear_thumbnail('prepared')
        if source and Path(bpy.path.abspath(source)).is_file():
            _file_thumbnail('original', bpy.path.abspath(source))
        if props.prepared_image and Path(props.prepared_image).is_file():
            _file_thumbnail('prepared', props.prepared_image)
            message = 'Reloaded saved image previews; no new processing required'
        elif _status_get('prep').get('state') in ('queued', 'working', 'waiting_preview'):
            message = 'Preparation is still running. The preview appears automatically when ready.'
        else:
            message = 'No prepared PNG yet. Choose an image and run Prepare first.'
        self.report({'INFO'}, message)
        return {'FINISHED'}


class TIINY_OT_OpenPrepared(bpy.types.Operator):
    bl_idname = 'tiiny.open_prepared'
    bl_label = 'Open prepared PNG'
    bl_description = 'Open the prepared image in the default image viewer for full-size inspection'

    def execute(self, context):
        props = context.scene.tiiny_settings
        if not props.prepared_image or not Path(props.prepared_image).is_file():
            self.report({'ERROR'}, 'Prepare the image first')
            return {'CANCELLED'}
        bpy.ops.wm.path_open(filepath=props.prepared_image)
        return {'FINISHED'}


class TIINY_OT_Generate(bpy.types.Operator):
    bl_idname = 'tiiny.generate_3d'
    bl_label = 'Generate 3D and import GLB'
    bl_description = 'Run Tiiny shape/simplify/texture/export stages in the background and import GLB'

    def execute(self, context):
        pref = context.preferences.addons[__name__].preferences
        props = context.scene.tiiny_settings
        try:
            jid = _begin_job(_settings_snapshot(context))
            props.job_id = jid
            self.report({'INFO'}, 'Tiiny 3D started: ' + jid[:12])
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc)[:240])
            return {'CANCELLED'}


class TIINY_OT_Cancel(bpy.types.Operator):
    bl_idname = 'tiiny.cancel_3d'
    bl_label = 'Cancel generation'
    bl_description = 'Stop waiting immediately and request cancellation on Tiiny; an offline device cannot confirm cancellation'

    def execute(self, context):
        jid = _context_job_id(context)
        if not _stop_job(jid):
            self.report({'INFO'}, 'No active generation to stop')
        return {'FINISHED'}



def _job_progress_fraction(job):
    """Normalized 0..1 progress from the device's stage-weighted percentage."""
    try:
        value = float(job.get('progress') or 0)
    except (ValueError, TypeError, OverflowError):
        return 0.0
    if value != value:  # NaN
        return 0.0
    return max(0.0, min(1.0, value / 100.0))


def _compact_job_message(job, max_chars=24):
    """One-line human-friendly Tiiny status; raw text remains in the job record."""
    message = ' '.join(str(job.get('message') or '').split())
    stage = str(job.get('stage') or '').strip().lower()
    if stage and message.lower().startswith(stage + ':'):
        message = message[len(stage) + 1:].strip()
    low = message.lower()
    steps = re.search(r'(?<![0-9])([0-9]+/[0-9]+)(?![0-9])', message)
    counter = steps.group(1) if steps else ''
    patterns = (
        ('volume decoding', 'Decode volume'),
        ('volume refinement', 'Refine volume'),
        ('shape diffusion', 'Shape diffusion'),
        ('paint diffusion', 'PBR diffusion'),
        ('preparing internal paint', 'Preparing PBR'),
        ('projecting material', 'Exporting GLB'),
        ('exporting glb', 'Exporting GLB'),
        ('preparing texture', 'Preparing PBR'),
        ('waiting for busy tiiny', 'Waiting for Tiiny'),
        ('starting shape', 'Starting shape'),
        ('starting texture', 'Starting texture'),
        ('starting simplify', 'Starting cleanup'),
        ('starting export', 'Starting export'),
    )
    title = next((short for phrase, short in patterns if phrase in low), None)
    if title is None:
        title = re.sub(r'(?<![0-9])[0-9]+/[0-9]+(?![0-9])', '', message).strip(' :-')
        if title.lower().startswith(('shape:', 'texture:', 'export:')):
            title = title.split(':', 1)[-1].strip()
    if counter and len(title) + len(counter) + 1 <= max_chars:
        title = title + ' ' + counter
    if len(title) > max_chars:
        parts = title[:max_chars - 3].rsplit(' ', 1)
        title = (parts[0] if len(parts) > 1 and parts[0] else title[:max_chars - 3]) + '...'
    return title or 'Processing...'


def _draw_job_progress(layout, job):
    """Native Blender progress bar, updated through the redraw timer."""
    percent = round(100 * _job_progress_fraction(job))
    stage = str(job.get('stage') or '').replace('_', ' ').title()
    label = f'{percent}%  |  {stage}' if stage else f'{percent}%'
    layout.progress(factor=_job_progress_fraction(job), type='BAR', text=label)

def caps_for_cleanup_is_available(pref):
    record = _caps_get(_identity(pref.tiiny_api_url, pref.tiiny_api_key), pref.tiiny_model)
    caps = record['caps'] if record else None
    return caps is None or 'simplify' in (caps.get('stages') or [])


def _draw_job_status(layout, context):
    job = _job_get(_context_job_id(context))
    if not job:
        return
    status = layout.box()
    active = job.get('state') in ('running', 'queued', 'importing')
    status.label(text='Job: ' + (job.get('state') or '').title(),
                 icon='TIME' if active else 'ERROR' if job.get('state') == 'failed' else
                 'CANCEL' if job.get('state') == 'cancelled' else 'CHECKMARK')
    _draw_job_progress(status, job)
    msg = str(job.get('message') or '')
    if msg:
        detail = status.operator('tiiny.copy_job_message', text=_compact_job_message(job),
                                 icon='INFO', emboss=False)
        detail.message = msg
    if active:
        stop = status.row()
        stop.enabled = True
        stop.operator('tiiny.cancel_3d', text='Stop generation', icon='CANCEL')
        if job.get('connection_lost'):
            status.label(text='No device response', icon='ERROR')
            status.label(text='You can stop waiting now.')
    remote = job.get('remote_cancel')
    if remote in ('pending', 'accepted', 'confirmed', 'unconfirmed', 'unknown'):
        status.label(text={
            'pending': 'Requesting remote stop',
            'accepted': 'Stop request accepted',
            'confirmed': 'Tiiny confirmed stop',
            'unconfirmed': 'Remote stop unconfirmed',
            'unknown': 'Device task state unknown',
        }[remote], icon='INFO')
        if remote in ('unconfirmed', 'unknown'):
            status.label(text='Check Tiiny before retrying.')
    if job.get('state') == 'completed':
        counts = job.get('glb_counts') or {}
        status.label(text='Materials %s, Textures %s' % (
            counts.get('materials', '?'), counts.get('textures', '?')), icon='CHECKMARK')
        if context.scene.tiiny_settings.texture and not counts.get('textures'):
            status.label(text='GLB has no textures', icon='ERROR')


class TIINY_PT_Main(bpy.types.Panel):
    bl_label = 'Tiiny AI | Image to 3D'
    bl_idname = 'TIINY_PT_Main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tiiny AI'

    def draw(self, context):
        layout = self.layout
        pref = context.preferences.addons[__name__].preferences
        props = context.scene.tiiny_settings
        conn = layout.box()
        row = conn.row(align=True)
        row.label(text='Pocket Lab', icon='NETWORK_DRIVE')
        row.operator('tiiny.check_connection', text='', icon='FILE_REFRESH')
        _draw_status(conn, 'connection', pref)
        tools_enabled = _tools_enabled(pref)
        setup_running = tools_enabled and _setup_in_progress()
        setup_ready = (tools_enabled and _setup_ready() and not setup_running
                       and _status_get('setup').get('state') != 'error')
        # Model settings remain visible; image controls appear only when ready.
        box = layout.box()
        box.prop(pref, 'tiiny_model', text='Engine')
        row = box.row(align=True)
        row.operator('tiiny.check_model', text='Read model settings', icon='FILE_REFRESH')
        _draw_status(box, 'model', pref, pref.tiiny_model)
        if tools_enabled and (setup_running or not setup_ready):
            # A single shared setup state is shown in Preferences and the sidebar.
            # Hide the image picker and previews as well as preparation buttons.
            installer = layout.box()
            installer.label(text='Preparing image tools', icon='IMAGE_DATA')
            _draw_local_setup(installer, compact=True)
            if _status_get('setup').get('state') == 'error':
                installer.label(text='Retry in Preferences', icon='ERROR')
            else:
                installer.label(text='Image tools are not ready.', icon='INFO')
            _draw_job_status(layout, context)
            return
        choose = box.row(align=True)
        active_image = _accepted_image(context)
        filename = Path(active_image).name
        choose.label(text=('Image: ' + filename[:18] + ('...' if len(filename)>18 else '')) if active_image else 'Image: none selected')
        choose.operator('tiiny.select_image', text='', icon='FILE_FOLDER')
        if active_image:
            choose.operator('tiiny.clear_image', text='', icon='X')
        source_path = bpy.path.abspath(active_image) if active_image else ''
        if not tools_enabled:
            _draw_image_preview(box, source_path, 'Original', 'original', context)
            box.label(text='Direct image mode', icon='INFO')
            box.label(text='Use a centered transparent PNG.')
            box.label(text=('TRELLIS: 1024x1024' if 'TRELLIS' in pref.tiiny_model
                            else 'Hunyuan: 512x512'))
            box.label(text='Object ~85% of square frame.')
            box.label(text='No local masking or resizing.')
        else:
            previews = box.row(align=True)
            _draw_image_preview(previews, source_path, 'Original', 'original', context)
            prepared_path = props.prepared_image if props.prepared_image else ''
            _draw_image_preview(previews, prepared_path, 'Prepared', 'prepared', context)
            box.prop(props, 'auto_prepare')
            box.prop(props, 'remove_bg')
            prep = _status_get('prep')
            preparing = prep.get('state') in ('queued', 'working', 'waiting_preview')
            row = box.row(align=True)
            action = row.row(align=True)
            action.enabled = not preparing
            action.operator('tiiny.prepare_image', text=('Preparing...' if preparing else 'Prepare / Refresh Preview'), icon='TIME' if preparing else 'IMAGE_DATA')
            reload_button = row.row(align=True)
            reload_button.enabled = not preparing
            reload_button.operator('tiiny.refresh_thumbnails', text='', icon='FILE_REFRESH')
            if props.prepared_image and Path(props.prepared_image).is_file():
                row.operator('tiiny.open_prepared', text='', icon='FILE_IMAGE')
            # Do not present status from an earlier input/engine as current.
            try:
                signature_now = _prep_signature(_settings_snapshot(context))
            except (KeyError, OSError, AttributeError, ValueError):
                signature_now = None
            if prep.get('signature') and prep['signature'] != signature_now:
                prep = {'state': 'queued', 'message': 'Image/options changed; awaiting new preparation'}
            if prep.get('state') in ('queued','working','waiting_preview','ok','error','preview_delayed'):
                icon = {'queued':'TIME', 'working':'TIME', 'waiting_preview':'TIME',
                        'ok':'CHECKMARK', 'error':'ERROR', 'preview_delayed':'INFO'}[prep['state']]
                if prep['state'] in ('queued', 'working', 'waiting_preview'):
                    phase = max(0, min(_PREP_TOTAL_STEPS, int(prep.get('phase') or 0)))
                    box.progress(factor=max(0., min(.99, phase/_PREP_TOTAL_STEPS)),
                                 type='BAR', text='Preparation: stage %d/%d' % (phase, _PREP_TOTAL_STEPS))
                    started = prep.get('started_at')
                    if isinstance(started, (float, int)):
                        elapsed = max(0, int(time.monotonic() - started))
                        box.label(text='Elapsed: %d:%02d (no ETA)' % divmod(elapsed, 60), icon='TIME')
                    if phase in (2, 3, 4):
                        box.label(text='First use: downloads possible', icon='INFO')
                        box.label(text='Keep Blender open', icon='INFO')
                for i, line in enumerate(_ui_message_lines(prep.get('message'))):
                    box.label(text=line, icon=icon if i == 0 else 'NONE')
                report = prep.get('report') or {}
                if prep['state'] == 'ok':
                    if report.get('segmentation_applied'):
                        box.label(text='Background removed: ' + str(report.get('segmentation_model') or 'AI'), icon='CHECKMARK')
                    elif report.get('already_transparent'):
                        box.label(text='Source alpha used; AI skipped', icon='INFO')
                    elif props.remove_bg:
                        box.label(text='No AI mask applied; inspect PNG', icon='ERROR')
                    else:
                        box.label(text='Background removal disabled', icon='INFO')
                    if report.get('mask'):
                        box.label(text='Alpha mask saved', icon='CHECKMARK')
                    cleanup = report.get('mask_cleanup') or {}
                    if cleanup.get('status') == 'cleaned':
                        box.label(text='Soft background cleaned', icon='CHECKMARK')
                    elif cleanup.get('status') == 'skipped_uncertain_foreground':
                        box.label(text='Soft alpha kept: uncertain mask', icon='INFO')
                if report.get('warning'):
                    box.label(text='Upscaling adds no source detail', icon='ERROR')
        box.prop(props, 'texture', text='PBR color and materials')
        if 'TRELLIS' in pref.tiiny_model and caps_for_cleanup_is_available(pref):
            box.prop(props, 'trellis_postprocess', text='Surface')
            if props.trellis_postprocess == 'OFF':
                box.label(text='Surface: off', icon='INFO')
            elif props.trellis_postprocess == 'PRESERVE512':
                box.label(text='Remesh without decimation', icon='INFO')
                box.label(text='Export may project geometry')
                if props.faces:
                    box.label(text='Polygon target: decimation', icon='INFO')
            elif props.trellis_postprocess in ('REMESH256','REMESH512'):
                box.label(text='Legacy remesh + decimate', icon='INFO')
        rec = _caps_get(_identity(pref.tiiny_api_url, pref.tiiny_api_key), pref.tiiny_model)
        caps = rec['caps'] if rec else None
        modes = _available_quality_modes(caps, props.texture)
        if len(modes) == 1:
            box.label(text='Quality: Standard', icon='INFO')
            if caps is None:
                box.label(text='Read model settings first.')
            else:
                box.label(text='No verified quality controls.')
        else:
            box.label(text='Generation preset:')
            row = box.row(align=True)
            for mode in modes:
                btn = row.operator('tiiny.select_quality', text={
                    'STANDARD': 'Standard', 'DRAFT': 'Draft',
                    'MAXIMUM': 'Maximum', 'CUSTOM': 'Custom',
                }[mode], depress=(props.quality == mode))
                btn.mode = mode
            effective = _effective_quality(caps, props.quality, props.texture)
            if props.quality != effective:
                box.label(text='Using Standard preset instead.', icon='INFO')
            elif effective == 'DRAFT':
                box.label(text='Draft: faster generation', icon='INFO')
            elif effective == 'STANDARD' and 'TRELLIS' in pref.tiiny_model:
                box.label(text='Standard: 512 / balance', icon='INFO')
            elif effective == 'MAXIMUM':
                if 'TRELLIS' in pref.tiiny_model:
                    box.label(text='1024: experimental', icon='INFO')
                    if not getattr(props, 'allow_trellis_1024', False):
                        box.label(text='Enable 1024 in Advanced.')
                else:
                    box.label(text='Higher-quality tier', icon='INFO')
            elif effective == 'CUSTOM':
                box.label(text='Custom: see Advanced', icon='INFO')
            if _overrides_active(props, pref.tiiny_model):
                box.label(text='Manual overrides enabled', icon='PREFERENCES')
        row = box.row()
        row.operator('tiiny.generate_3d', text='Generate 3D + Import GLB', icon='OUTLINER_OB_MESH')
        _draw_job_status(layout, context)


class TIINY_PT_Advanced(bpy.types.Panel):
    bl_label = 'Advanced model settings'
    bl_idname = 'TIINY_PT_Advanced'
    bl_parent_id = 'TIINY_PT_Main'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        pref = context.preferences.addons[__name__].preferences
        props = context.scene.tiiny_settings
        record = _caps_get(_identity(pref.tiiny_api_url, pref.tiiny_api_key), pref.tiiny_model)
        caps = record['caps'] if record else None
        if _tools_enabled(pref) and _setup_ready() and not _setup_in_progress():
            prepbox = layout.box()
            prepbox.label(text='Reference image preparation',icon='IMAGE_DATA')
            prepbox.prop(props, 'canvas', text='Canvas')
            prepbox.prop(props, 'smart_crop')
            prepbox.prop(props, 'occupancy', text='Object coverage')
            prepbox.prop(props, 'upscale')
            if props.remove_bg:
                prepbox.prop(props, 'segment_model', text='Segmentation')
                prepbox.label(text='CPU masking available',icon='INFO')
            prepbox.prop(props, 'clean_mask')
            source_alpha = prepbox.row()
            source_alpha.enabled = bool(getattr(props, 'clean_mask', True))
            source_alpha.prop(props, 'clean_existing_alpha')
            prepbox.label(text='Auto: Hunyuan 512, TRELLIS 1024')
        layout.separator()
        if 'TRELLIS' in pref.tiiny_model:
            geometry_box = layout.box()
            geometry_box.label(text='Surface diagnostics', icon='MOD_REMESH')
            geometry_box.label(text='Surface and quality separate')
            geometry_box.prop(props, 'save_stage_previews')
            geometry_box.prop(props, 'allow_trellis_1024')
            geometry_box.label(text='1024: experimental on Tiiny', icon='INFO')
        layout.prop(props, 'seed', text='Seed (-1 = server)')
        col = layout.column()
        col.enabled = bool(caps and 'simplify' in (caps.get('stages') or []))
        col.prop(props, 'faces', text='Target polygons (0 = no budget)')
        if caps:
            lower, upper = _face_limits(caps)
            if lower is not None or upper is not None:
                col.label(text='Device budget range: %s to %s' % (lower if lower is not None else '?', upper if upper is not None else '?'))
        if not caps:
            layout.label(text='Read model settings first.', icon='INFO')
            layout.operator('tiiny.check_model', text='Read model settings', icon='FILE_REFRESH')
            return
        layout.label(text='Stages: ' + ', '.join(caps.get('stages') or [])[:70], icon='INFO')
        layout.label(text='Artifact refs: %s' % ('Yes' if caps.get('input_refs') else 'No'))
        available = {(c['stage'],c['key']) for c in _extract_stage_controls(caps)}
        controls = [e for e in props.controls if e.model_id == pref.tiiny_model
                    and (e.stage,e.param_name) in available]
        if props.quality == 'CUSTOM':
            layout.prop(props, _model_property(pref.tiiny_model, 'custom_base'), text='Custom base')
        else:
            layout.prop(props, _model_property(pref.tiiny_model, 'overrides'), text='Enable manual overrides')
        base = _base_preset({'custom_base': getattr(props, _model_property(pref.tiiny_model, 'custom_base'), 'NATIVE')}, props.quality)
        if _global_preset(caps, base):
            quality_box = layout.box()
            quality_box.label(text='Base preset: ' + base.title(), icon='CHECKMARK')
            choices = _global_preset(caps, base)
            titles = {'output_precision':'Geometry precision',
                      'inference_quality':'Inference quality',
                      'asset_quality':'Asset quality'}
            for key, value in choices.items():
                quality_box.label(text='%s: %s' % (titles.get(key, key), value))
            tier = (caps.get('output_precisions') or {}).get(choices.get('output_precision'))
            if isinstance(tier, dict):
                for key in ('octree_resolution', 'pipeline_type'):
                    if key in tier:
                        quality_box.label(text='%s: %s' % (key.replace('_', ' ').title(), tier[key]))
        if not _overrides_active(props, pref.tiiny_model):
            layout.label(text='Enable overrides to edit',icon='INFO')
        elif not controls:
            layout.label(text='No controls published by Tiiny',icon='INFO')
        else:
            layout.label(text='Checked values override preset',icon='PREFERENCES')
            if _is_hunyuan_caps(caps):
                layout.label(text='Tiiny bounds are unverified.', icon='INFO')
            stage_titles={'quality':'Quality overrides','shape':'Geometry',
                          'simplify':'Simplification','texture':'Materials / texture',
                          'export':'GLB export'}
            for stage in ('quality','shape','simplify','texture','export'):
                group=[x for x in controls if x.stage == stage]
                if not group or (stage in ('texture','export') and not props.texture):
                    continue
                section=layout.box()
                section.label(text=stage_titles[stage],icon='PREFERENCES')
                for entry in group:
                    if entry.datatype == 'bool':
                        section.prop(entry, 'value_bool_choice', text=entry.label)
                    else:
                        row=section.row(align=True)
                        row.prop(entry,'enabled',text='')
                        row.label(text=entry.label)
                        val=section.row()
                        val.enabled=entry.enabled
                        propname={'enum':'value_enum','int':'value_int','float':'value_float',
                                  'string':'value_text'}.get(entry.datatype)
                        if propname:
                            val.prop(entry,propname,text='Value')
                    details=[]
                    if entry.default_json and entry.default_json != 'null':
                        details.append('default '+entry.default_json[:22])
                    if entry.min_json or entry.max_json:
                        details.append('range '+(entry.min_json or '?')+'..'+(entry.max_json or '?'))
                    if details:
                        section.label(text=' | '.join(details)[:70],icon='INFO')
                    if entry.help_text:
                        section.label(text=entry.help_text[:70])
        layout.prop(props, 'show_request_preview')
        if getattr(props, 'show_request_preview', False):
            preview = layout.box()
            try:
                settings = _settings_snapshot(context)
                effective = _effective_quality(caps, props.quality, props.texture)
                plan, params = _execution_plan(caps, settings, effective)
                for stage in plan:
                    preview.label(text=stage.title(), icon='PREFERENCES')
                    if not params[stage]:
                        preview.label(text='Server defaults')
                    for key, value in params[stage].items():
                        preview.label(text='%s: %s' % (key, str(value)))
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                preview.label(text=str(exc)[:68], icon='ERROR')
        layout.operator('tiiny.save_capabilities', text='Export capabilities JSON', icon='FILE_TICK')
        layout.label(text='Only confirmed Tiiny controls', icon='INFO')
        layout.separator()
        layout.prop(pref, 'output_dir', text='Save GLB to')
        layout.label(text='Input folder: Preferences',icon='INFO')


def _main_tick():
    global _AUTO_PREP_REQUEST
    if not _ACTIVE:
        return None
    # Detect manually removed private weights/packages after a prior success.
    # Retry once automatically; subsequent failures are left visible for manual Retry.
    if _tools_enabled() and _status_get('setup').get('state') == 'ok':
        checks = _prep_install_status()
        if not (checks['python'] and checks['rembg'] and checks['weights'] and checks['validated']):
            _status_set('setup', state='not_ready', phase=0,
                        message='Local tools were removed; reinstalling in the background')
            _begin_background_setup()
    if _AUTO_PREP_REQUEST and not _tools_enabled():
        _AUTO_PREP_REQUEST = None
    if (_AUTO_PREP_REQUEST and time.monotonic() >= _AUTO_PREP_REQUEST[0]
            and _setup_ready() and not _setup_in_progress()
            and _status_get('setup').get('state') != 'error'):
        active = (_status_get('prep').get('state') == 'working')
        with _LOCK:
            active = active or any(j.get('state') in ('queued','running','importing') for j in _JOBS.values())
        if not active:
            _, settings = _AUTO_PREP_REQUEST
            _AUTO_PREP_REQUEST = None
            _status_set('prep', state='working', phase=1, started_at=time.monotonic(),
                        message='Preparing image automatically...')
            threading.Thread(target=_prep_worker,args=(settings,),daemon=True).start()
    did_import = False
    try:
        while True:
            path, signature, report = _PENDING_PREVIEW.get_nowait()
            props = bpy.context.scene.tiiny_settings
            valid = False
            if props and Path(path).is_file():
                try:
                    current = _settings_snapshot(bpy.context)
                    valid = _prep_signature(current) == signature
                except (OSError, KeyError, ValueError, AttributeError):
                    valid = False
            if valid:
                props.prepared_preview = None  # old data-block preview is no longer used
                props.prepared_image = path
                props.prepared_signature = signature
                _clear_thumbnail('prepared')
                thumb = _file_thumbnail('prepared', path)
                _status_set('prep', state='ok' if thumb is not None and thumb.icon_id > 0 else 'waiting_preview',
                            signature=signature, phase=_PREP_TOTAL_STEPS, preview_started_at=time.monotonic(),
                            message=('Prepared %sx%s' % tuple(report['canvas'])) if thumb is not None and thumb.icon_id > 0 else
                            'PNG saved. Blender is loading the thumbnail...', report=report)
            did_import = True
    except queue.Empty:
        pass
    try:
        while True:
            jid, filename = _PENDING_IMPORT.get_nowait()
            if _job_get(jid).get('cancel'):
                continue
            did_import = True
            try:
                previous = set(bpy.data.objects)
                bpy.ops.import_scene.gltf(filepath=filename)
                created = [obj.name for obj in bpy.data.objects if obj not in previous]
                _job_set(jid, state='completed', stage='done', progress=100,
                         message='Imported %d Blender objects' % len(created), objects=created)
            except Exception as exc:
                _job_set(jid, state='failed', message='GLB saved, Blender import failed: %s' % exc,
                         error=str(exc))
    except queue.Empty:
        pass
    try:
        prep = _status_get('prep')
        if prep.get('state') in ('waiting_preview', 'preview_delayed'):
            current = bpy.context.scene.tiiny_settings
            if current.prepared_image and Path(current.prepared_image).is_file():
                thumb = _file_thumbnail('prepared', current.prepared_image)
                if thumb is not None and thumb.icon_id > 0:
                    report = prep.get('report') or {}
                    _status_set('prep', state='ok', phase=_PREP_TOTAL_STEPS,
                                message='Prepared %sx%s' % tuple(report.get('canvas', [0, 0])))
                elif time.monotonic() - prep.get('preview_started_at', time.monotonic()) > 15:
                    _status_set('prep', state='preview_delayed',
                                message='PNG is ready. Thumbnail delayed: use reload or open PNG.')
    except (RuntimeError, AttributeError, ReferenceError, OSError):
        pass
    try:
        prefs = bpy.context.preferences.addons[__name__].preferences
        identity = _identity(prefs.tiiny_api_url, prefs.tiiny_api_key)
        scene = bpy.context.scene
        _sync_controls(scene, identity, prefs.tiiny_model)
        if bpy.context.window_manager:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type in {'VIEW_3D', 'PREFERENCES'}:
                        area.tag_redraw()
    except (RuntimeError, AttributeError, KeyError, ReferenceError):
        pass
    with _LOCK:
        running = any(j.get('state') in ('queued', 'running', 'importing') for j in _JOBS.values())
        probing = any(x.get('state') in ('checking','working','queued') for x in _STATUS.values())
    return 0.5 if (running or probing or did_import or _AUTO_PREP_REQUEST) else 2.0


def _clear_session_images(*args):
    """Never inherit an image from a prior installation/startup file/.blend."""
    global _AUTO_PREP_REQUEST
    _AUTO_PREP_REQUEST=None
    _IMAGE_SELECTIONS.clear()
    _clear_thumbnail('original')
    _clear_thumbnail('prepared')
    for scene in getattr(getattr(bpy,'data',None),'scenes',[]):
        if not hasattr(scene,'tiiny_settings'):
            continue
        props=scene.tiiny_settings
        # Do not create directories or start preprocessing here.
        props.image=''
        props.original_preview=None
        props.prepared_preview=None
        props.prepared_image=''
        props.prepared_signature=''
        props.job_id=''
        props.allow_trellis_1024=False
    _status_set('prep',state='not_ready',message='Select an image to start')


try:
    from bpy.app.handlers import persistent
except (ImportError,AttributeError):
    def persistent(fn): return fn


@persistent
def _on_file_loaded(_dummy):
    _cancel_all_jobs()
    _clear_session_images()


_CLASSES = (
    TIINY_PG_Control, TIINY_PG_Settings, TIINY_Preferences,
    TIINY_OT_InstallTools, TIINY_OT_RemoveTools, TIINY_OT_CleanUninstall, TIINY_OT_OpenPrepLog, TIINY_OT_CopyJobMessage, TIINY_OT_CopyImagePath, TIINY_OT_CheckConnection, TIINY_OT_CheckModel, TIINY_OT_SaveCaps,
    TIINY_OT_SelectQuality, TIINY_OT_SelectImage, TIINY_OT_ClearImage, TIINY_OT_PrepareImage, TIINY_OT_RefreshThumbnails, TIINY_OT_OpenPrepared,
    TIINY_OT_Generate, TIINY_OT_Cancel, TIINY_PT_Main, TIINY_PT_Advanced,
)


def register():
    global _ACTIVE
    _ACTIVE = True
    _thumbnail_collection()
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.tiiny_settings = PointerProperty(type=TIINY_PG_Settings)
    _clear_session_images()
    handlers=getattr(getattr(bpy.app,'handlers',None),'load_post',None)
    if handlers is not None and _on_file_loaded not in handlers:
        handlers.append(_on_file_loaded)
    if not bpy.app.timers.is_registered(_main_tick):
        bpy.app.timers.register(_main_tick, first_interval=0.5, persistent=True)
    # Do not block Blender startup or the user's API-key entry.
    if not bpy.app.timers.is_registered(_automatic_setup_start):
        bpy.app.timers.register(_automatic_setup_start, first_interval=1.0, persistent=False)


def unregister():
    global _ACTIVE, _THUMBNAILS
    _ACTIVE = False
    _cancel_all_jobs()
    if _THUMBNAILS is not None:
        bpy.utils.previews.remove(_THUMBNAILS)
        _THUMBNAILS = None
        _THUMBNAIL_KEYS.clear()
        _THUMBNAIL_NAMES.clear()
        _THUMBNAIL_ATTEMPTS.clear()
    handlers=getattr(getattr(bpy.app,'handlers',None),'load_post',None)
    if handlers is not None and _on_file_loaded in handlers:
        handlers.remove(_on_file_loaded)
    if bpy.app.timers.is_registered(_main_tick):
        bpy.app.timers.unregister(_main_tick)
    if bpy.app.timers.is_registered(_automatic_setup_start):
        bpy.app.timers.unregister(_automatic_setup_start)
    # Blender calls unregister() on disable as well as on uninstall.
    # Never destroy user data or private model files here.
    if hasattr(bpy.types.Scene, 'tiiny_settings'):
        del bpy.types.Scene.tiiny_settings
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)

