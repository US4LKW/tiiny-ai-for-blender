"""Verify namespaced Blender Extension registration and uninstall migration offline."""
from pathlib import Path
import importlib.util
import sys
import types
import tomllib

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'tiiny_ai_for_blender'
manifest = tomllib.loads((EXT / 'blender_manifest.toml').read_text('utf8'))
assert manifest['schema_version'] == '1.0.0'
assert manifest['id'] == 'tiiny_ai_for_blender'
assert manifest['version'] == '0.1.0'
assert manifest['type'] == 'add-on'
assert manifest['license'] == ['SPDX:MIT']
assert (EXT / '__init__.py').is_file()
assert not (EXT / 'addon.py').exists()
assert 'bl_info' not in (EXT / '__init__.py').read_text('utf8')

# Reuse the existing offline Blender stub, then import the extension using
# the full namespaced module name Blender assigns to local extension packages.
sp = importlib.util.spec_from_file_location('package_fixture', Path(__file__).with_name('test_offline.py'))
fixture = importlib.util.module_from_spec(sp)
sys.modules['package_fixture'] = fixture
sp.loader.exec_module(fixture)
bpy = sys.modules['bpy']
module_name = 'bl_ext.user_default.tiiny_ai_for_blender'
spec = importlib.util.spec_from_file_location(module_name, EXT / '__init__.py', submodule_search_locations=[str(EXT)])
package = importlib.util.module_from_spec(spec)
sys.modules[module_name] = package
spec.loader.exec_module(package)
assert package.EXTENSION_VERSION == (0, 1, 0)
assert package.TIINY_Preferences.bl_idname == module_name
assert package._image_prep_home().name == 'TiinyAIForBlender'

# The extension ID must be used to look up its *own* preferences, not the
# generic legacy 'addon' module.
bpy.context = types.SimpleNamespace(preferences=types.SimpleNamespace(addons={
    module_name: types.SimpleNamespace(preferences=types.SimpleNamespace(use_local_image_tools=False))
}))
assert package._tools_enabled() is False

# Clean Uninstall must identify the correct extension repository by module,
# even if the user's repository order differs from another Blender install.
called = []
package._remove_private_tools = lambda: called.append('private-tools')
bpy.ops = types.SimpleNamespace(extensions=types.SimpleNamespace(
    package_uninstall=lambda **kwargs: (called.append(kwargs) or {'FINISHED'})
))
ctx = types.SimpleNamespace(
    area=types.SimpleNamespace(type='PREFERENCES'),
    preferences=types.SimpleNamespace(extensions=types.SimpleNamespace(repos=[
        types.SimpleNamespace(module='blender_org'),
        types.SimpleNamespace(module='third_party'),
        types.SimpleNamespace(module='user_default'),
    ]))
)
messages = []
operator = types.SimpleNamespace(report=lambda levels, msg: messages.append((levels, msg)))
result = package.TIINY_OT_CleanUninstall.execute(operator, ctx)
assert result == {'FINISHED'}, result
assert called == ['private-tools', {'repo_index': 2, 'pkg_id': 'tiiny_ai_for_blender'}], called
assert not messages, messages
print('PASS: manifest, extension package namespace, own preferences and correct repo-aware uninstall')
