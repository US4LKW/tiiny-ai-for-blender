"""Portable headless Blender registration, real-RNA, and source-session checks.

Run: blender --background --factory-startup --python-exit-code 1 --python blender_smoke.py
No network requests, model generation, or visual interface screenshots are made.
"""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types

import bpy


ROOT = Path(__file__).resolve().parent
MODULE = "tiiny_smoke_addon"
spec = importlib.util.spec_from_file_location(MODULE, ROOT.parent / "tiiny_ai_for_blender" / "__init__.py")
addon = importlib.util.module_from_spec(spec)
sys.modules[MODULE] = addon
spec.loader.exec_module(addon)


def reject_network(*args, **kwargs):
    raise AssertionError("A Blender smoke test must not contact a device")


class LayoutProbe:
    """Execute panel code against real properties without pretending to render it."""
    def __init__(self):
        self.property_count = 0

    def row(self, *args, **kwargs):
        return self

    column = box = row

    def prop(self, owner, name, *args, **kwargs):
        assert name in owner.bl_rna.properties, (type(owner).__name__, name)
        getattr(owner, name)
        self.property_count += 1

    def label(self, *args, **kwargs):
        pass

    separator = template_icon = label

    def operator(self, *args, **kwargs):
        return types.SimpleNamespace()

    def progress(self, *, factor, type, text):
        assert hasattr(bpy.types.UILayout, "progress")
        assert 0 <= factor <= 1 and type == "BAR"


addon._request = reject_network
registered = False
entry = None
try:
    addon.register()
    registered = True
    entry = bpy.context.preferences.addons.new()
    entry.module = MODULE
    prefs = entry.preferences
    assert prefs is not None
    scene = bpy.context.scene
    props = scene.tiiny_settings
    assert props.image == "" and props.prepared_image == ""
    assert props.clean_mask is True and props.clean_existing_alpha is False
    initial_snapshot = addon._settings_snapshot(bpy.context)
    assert initial_snapshot["clean_mask"] is True
    assert initial_snapshot["clean_existing_alpha"] is False
    # Real RNA toggles must invalidate an old thumbnail without selecting a file.
    props.prepared_image = "old-preparation.png"
    props.clean_mask = False
    assert props.prepared_image == "" and addon._AUTO_PREP_REQUEST is None
    props.clean_mask = True
    assert props.bl_rna.properties["faces"].hard_max == 2000000
    trellis = "microsoft/TRELLIS.2-4B"
    hunyuan = "Tencent/Hunyuan3d-2.1"
    identity = addon._identity(prefs.tiiny_api_url, prefs.tiiny_api_key)
    for model, filename in ((trellis, "tiiny_capabilities_trellis2.json"),
                            (hunyuan, "tiiny_capabilities_hunyuan3d.json")):
        caps = json.loads((ROOT / "fixtures" / filename).read_text())
        addon._CAPABILITIES[(identity, model)] = {"caps": caps}
        addon._sync_controls(scene, identity, model)

    prefs.tiiny_model = trellis
    props.quality = "DRAFT"
    props.trellis_overrides = True
    props.hunyuan_overrides = False
    target = next(c for c in props.controls if c.model_id == trellis and c.param_name == "texture_size")
    target.enabled = True
    target.value_int = 1024
    trellis_snapshot = addon._settings_snapshot(bpy.context)
    assert trellis_snapshot["manual_overrides"] is True
    assert any(c["param"] == "texture_size" and c["value"] == 1024 for c in trellis_snapshot["custom"])
    assert bpy.ops.tiiny.select_quality(mode="CUSTOM") == {"FINISHED"}
    assert props.trellis_custom_base == "DRAFT"
    assert addon._settings_snapshot(bpy.context)["custom_base"] == "DRAFT"

    props.trellis_postprocess = "PRESERVE512"
    prefs.tiiny_model = hunyuan
    hunyuan_snapshot = addon._settings_snapshot(bpy.context)
    assert hunyuan_snapshot["manual_overrides"] is False
    assert hunyuan_snapshot["custom"] == []
    assert hunyuan_snapshot["trellis_postprocess"] == "OFF"
    props.hunyuan_overrides = True
    step = next(c for c in props.controls if c.model_id == hunyuan and c.stage == "shape" and c.param_name == "step")
    step.enabled = True
    step.value_int = 8
    hunyuan_snapshot = addon._settings_snapshot(bpy.context)
    assert all(c["param"] != "texture_size" for c in hunyuan_snapshot["custom"])
    assert any(c["param"] == "step" for c in hunyuan_snapshot["custom"])

    # Validate both panels' property accesses against real Blender RNA.
    for model in (hunyuan, trellis):
        prefs.tiiny_model = model
        props.show_request_preview = True
        for quality in ("DRAFT", "STANDARD", "MAXIMUM", "CUSTOM"):
            props.quality = quality
            for panel in (addon.TIINY_PT_Main, addon.TIINY_PT_Advanced):
                layout = LayoutProbe()
                panel.draw(types.SimpleNamespace(layout=layout), bpy.context)
                assert layout.property_count > 0

    # A restored file path is not an explicit image selection, even if it exists.
    with tempfile.TemporaryDirectory(prefix="tiiny-blender-smoke-") as temp:
        directory = Path(temp)
        source = directory / "old-reference.png"
        source.write_bytes(b"not decoded because it was never selected")
        output = directory / "must-not-be-created"
        prefs.output_dir = str(output)
        props.image = str(source)
        addon._queue_auto_prepare(bpy.context)
        assert addon._accepted_image(bpy.context) == ""
        assert addon._AUTO_PREP_REQUEST is None
        assert not output.exists()
        saved = directory / "session.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(saved))
        bpy.ops.wm.open_mainfile(filepath=str(saved))
        props = bpy.context.scene.tiiny_settings
        assert props.image == "" and props.prepared_image == ""
        assert not addon._IMAGE_SELECTIONS and addon._AUTO_PREP_REQUEST is None
        assert not output.exists()

    print("PASS: Blender %s registration, real RNA controls, model-isolated overrides, Custom inheritance, panel property accesses, and no restored image processing" % bpy.app.version_string)
finally:
    if entry is not None:
        current = bpy.context.preferences.addons.get(MODULE)
        if current is not None:
            bpy.context.preferences.addons.remove(current)
    if registered:
        addon.unregister()
    assert not hasattr(bpy.types.Scene, "tiiny_settings")
print("PASS: clean Blender unregister; no Tiiny inference or visual UI validation claimed")
