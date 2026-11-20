# Migrating from the legacy `addon.py` installation

## Why the packaging changed

Before this migration, Blender installed the generic file `%APPDATA%\Blender Foundation\Blender\5.3\scripts\addons\addon.py`. Two unrelated scripts with the same name could collide. Modern Blender Extensions are versioned packages with unique IDs, manifests and repository namespaces.

## Recommended migration

1. Finish active generation and preparation tasks.
2. In Blender Preferences > Add-ons, remove **Tiiny AI for Blender v0.3.6** with regular Uninstall. Do **not** use Clean Uninstall if you want to reuse the image-processing environment.
3. Close Blender and start it again.
4. Install `tiiny_ai_for_blender-0.1.0.zip` using Preferences > Get Extensions > Install from Disk; do not use the GitHub source ZIP and do not install an individual `.py` file.
5. Enable **Tiiny AI**. Open its preferences, enter URL/key and choose model and folders. The new package has a distinct preferences namespace and does not automatically import the old API key.
6. Verify the local tools readiness, API authentication, model capabilities and original/processed previews before running a new 3D job.

## What remains

- Input photos, prepared PNGs, GLBs and diagnostics remain in user-chosen folders.
- The optional isolated local tools under `%LOCALAPPDATA%\TiinyAIForBlender` are reused following a regular legacy uninstall.
- User data is not cleaned up when disabling/uninstalling an extension with standard Blender controls.
- Old `__pycache__\addon.cpython-313.pyc` can be removed manually with Blender closed after verifying it belonged to the old add-on; it does not affect the new package and does not require cleaning to migrate.

## Clean uninstall

The extension's Clean Uninstall button first deletes only its private image tools (not source images/GLBs) and then attempts to invoke Blender's `extensions.package_uninstall` with the correct repository ID. Blender may restrict package-removal operations from within the active Preferences context; if this happens use **Get Extensions > Uninstall** to finish removing the extension manually. Do not assume the fallback automatically uninstalled the package.

## Initial-release numbering

The new manifest specifies `0.1.0`. This is a pre-1.0 development version suitable as the starting version for the future GitHub repository. The *v0.3.8* source archive prefix is an internal development iteration to distinguish test packages. If release assets are published and revised, use new SemVer patch versions for updates rather than silently replacing an already released version.
