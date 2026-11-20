# Technical Installation Notes

> **New to this project?** Start with the [Complete Illustrated User Guide](USER_GUIDE.md), which covers installation, configuration, generation, materials and removal with screenshots.

For additional technical detail, see the existing installation notes below.

---


This guide covers a new installation, connecting a Tiiny Pocket Lab, and generating the first image-to-3D model. **No external Blender MCP bridge or Claude account is required.**

> **Package version:** `0.1.0` (pre-release development snapshot). **Blender:** 4.3 or newer; developed with Blender 5.3 in mind. This is an independent community extension, not an official Tiiny or Blender product.

## 1. Choose the correct download

The GitHub source project contains two different kinds of files:

- **Installable Blender Extension:** [`releases/tiiny_ai_for_blender-0.1.0.zip`](../releases/tiiny_ai_for_blender-0.1.0.zip) or the identically named ZIP attached to a future GitHub Release. This ZIP contains **`blender_manifest.toml`**, **`__init__.py`** and **`LICENSE`** at its root. Install this file **without extracting it**.
- **Source project:** The complete repository or GitHub's automatic **Source code (zip)** download. Use this to read the code, documentation or run tests. **Do not** install the entire source project as an extension.

The three-file installer is intentionally small: optional Python dependencies and neural-network weights are installed separately on the user's own computer when enabled.

## 2. Prerequisites

- Blender 4.3+ installed (the development target is Blender 5.3).
- A Tiiny Pocket Lab reachable on your local network, and its API key.
- At least one of the supported 3D models installed and **running** on the Tiiny device:
  - `Tencent/Hunyuan3d-2.1`
  - `microsoft/TRELLIS.2-4B`
- On Windows, `uv` is recommended if you want optional local image preparation (for example, `winget install --id=astral-sh.uv -e` in PowerShell). It manages an isolated Python environment; it is **not** required to generate 3D when local image tools are disabled.
- Internet access for the first optional `rembg`/ISNet installation, if those tools are enabled. Image-to-3D requests themselves go to your Tiiny device.

The Tiiny API is normally available at `http://tiinyhost.local`. Use the actual address from your device if this name does not resolve. Do not publish your API key or include it in GitHub files.

## 3. Install in Blender

1. Close any active generation tasks in Blender.
2. If you installed an older **legacy** Tiiny add-on as `addon.py`, remove it first through **Edit > Preferences > Add-ons** using the regular **Uninstall** action. **Do not** use **Clean Uninstall** if you want to keep cached ISNet and Python tools. Restart Blender.
3. Open Blender > **Edit > Preferences > Get Extensions** (sometimes the install command is also accessible from the **Add-ons** page).
4. Open the **down-arrow menu** in the top-right area and select **Install from Disk**.
5. Select **`tiiny_ai_for_blender-0.1.0.zip`** as a ZIP file. Do not select `__init__.py` and do not extract the ZIP.
6. Enable the extension if Blender offers an enable checkbox. Search for **Tiiny AI** under Preferences > Add-ons.
7. Open its preferences. It should identify itself as **Tiiny AI**, version **0.1.0**, not the generic `addon.py`.

The extension has the unique module ID `tiiny_ai_for_blender` and should be installed inside Blender's Extensions repository, not directly as `scripts/addons/addon.py`.

## 4. Configure Tiiny in Preferences

1. In **Pocket Lab connection**, enter **Address** (for example, `http://tiinyhost.local`) and **API Key**.
2. Click **Check connection / API key**. A successful result says **Connected; API key accepted**. This check does not require an active 3D model.
3. Under **3D model on Tiiny**, select Hunyuan3D 2.1 or TRELLIS.2 4B.
4. Make sure that same model is running on your Tiiny Pocket Lab, then click **Refresh selected model settings**. You should see a result such as **3D + PBR ready** if all required stages are available.
5. Set **Incoming photos** (the initial directory shown in the source-file picker) and **Generated models** (where GLBs, reports, and prepared PNGs will be saved). The same directory can be used for both.
6. Leave **Use local image tools** checked if you want automatic background removal, cropping and resizing. Uncheck it for direct input using a photo or transparent PNG you have prepared yourself.

The API key is saved locally in Blender preferences **without encryption**. Do not copy your Blender preferences into public repositories or upload logs containing private information.

## 5. Optional local image tools — first run

When **Use local image tools** is enabled, the extension sets up the optional image-processing components on the computer running Blender:

1. Create or verify an isolated Python environment.
2. Install Pillow and `rembg` as needed.
3. Download/cache ISNet weights if they are not already present.
4. Verify that image preparation is ready.

During first-time installation, the progress appears both in Preferences and in the Blender sidebar. **Stage percentages reflect completed setup steps, not exact network download percentages.** The first download may take several minutes. Once ready, dependencies are reused on subsequent launches; local 3D inference still runs on the Tiiny device.

Image selection/preparation controls are hidden while image tools are being installed. If you disable optional tools, the source-image picker is available for direct image-to-3D generation instead. Use the Preferences buttons **Install / Retry**, **Remove local tools** and **Clean Uninstall** only when needed. Regular extension upgrades should **not** remove the local tools.

### Automatic foreground-mask cleanup

For an ordinary photo, leave **Remove background** and **Auto prepare before generation** enabled. Under **Advanced model settings > Reference image preparation**, **Clean soft background** is enabled by default. It processes the newly generated mask before cropping and centering, reducing broad low-opacity background residue while protecting a narrow soft boundary and thin attached features.

If the selected source is already transparent, its alpha is preserved by default. Enable **Clean existing alpha** only when you deliberately want the same cleanup applied to that supplied mask. Both cleanup controls are local preparation settings; they do not change TRELLIS or Hunyuan generation presets.

The source image is never overwritten. Review **Prepared** before generation, particularly for hair, transparent parts or delicate edges. If cleanup removes a wanted faint feature, disable **Clean soft background** and prepare again. See [Mask cleanup](IMAGE_MASK_CLEANUP.md) for details.

## 6. Generate your first model

1. In Blender's **3D Viewport**, press **N** to open the right sidebar, then select the **Tiiny AI** tab.
2. Choose the engine (Hunyuan3D or TRELLIS.2). Read model settings if you have not done so already.
3. Select a source image with the folder button. If optional image tools are enabled, wait for the **Prepared** thumbnail and review it before generation. The **Original** and **Prepared** thumbnails are static; **hover the small information icon beside either thumbnail to read its full file path**. Clicking the information icon copies the path to the clipboard. Clicking the image itself does not open a second preview.
4. Keep **PBR color and materials** checked to request textured output, or uncheck it to generate geometry without the texture stage.
5. Use **Standard** quality for a first test. Draft and Maximum use parameters advertised by the Tiiny API; Maximum does not guarantee better results. Custom overrides are available for advanced users.
6. Click **Generate 3D + Import GLB**. The panel reports the current stage (Shape / Texture / Export) and job progress. Long exports may temporarily stop reporting new percentages without necessarily failing.
7. When the job finishes, the GLB is saved to **Generated models** and imported into the Blender scene. Switch the viewport to **Material Preview** to inspect PBR color and textures (Solid mode does not show those textures in the same way).
8. Keep the companion JSON report with the GLB if you need to troubleshoot, compare presets or ask for help.

Recommended inputs with local image tools enabled: one object, uncluttered scene, clear edges, preferably transparent background. The automatic preparation uses a square PNG (currently 512x512 for Hunyuan3D and 1024x1024 for TRELLIS.2); these sizes are preprocessing recommendations, not guaranteed model limits. The object should occupy roughly 85% of the square with visible margins.

If you disable image tools, prepare a centered transparent image yourself. The extension will send the original image without local segmentation, cropping or scaling.

## 7. Troubleshooting

| Symptom | First thing to check |
| --- | --- |
| **Can't connect to Tiiny** | Confirm the device and computer share a network, check the device IP/hostname and test again in Preferences. |
| **Unauthorized / 401 / 403** | Check the API key; no valid key means requests will be rejected. |
| **502 after restarting Tiiny** | The device may need to be unlocked in TiinyOS before serving API requests. |
| **Model is not ready** | Check that the selected model is **running**, not merely installed. Then refresh model settings. |
| **First image preparation seems slow** | Look at **Local image tools** setup stages. Initial ISNet weights need downloading, and CPU masking may take time. |
| **Prepared preview is missing** | Confirm local image tools are enabled and ready. Use **Prepare / Refresh Preview**, then **Reload image thumbnails** if the PNG exists but the thumbnail is stale. |
| **Model is grey in Blender** | Switch to **Material Preview** and confirm PBR was enabled for this generation. |
| **TRELLIS mesh contains holes** | Compare Draft/Standard, Surface Off and experimental repair modes. See `docs/TRELLIS_DIAGNOSTICS.md`. |
| **Wrong folder is used** | Update **Generated models** in Preferences, then reselect or prepare the image so new outputs use the current destination. |
| **Blender reports an already-installed extension** | Remove the earlier Tiiny AI extension using ordinary **Uninstall**, restart Blender, then install the new ZIP. Keep your local tools cache. |

Local setup logs can be viewed through **Preferences > Local image tools > View local setup log**. See [Local tools setup](LOCAL_TOOLS_SETUP.md) and [Preview/background troubleshooting](PREVIEW_BACKGROUND_TROUBLESHOOTING.md).

## 8. Updates and removal

- To update while retaining downloaded image tools, use ordinary **Uninstall**, restart Blender, then install the new extension ZIP. Recheck preferences afterward.
- **Remove local tools** only when you want to delete the extension's isolated Python packages and its private ISNet cache. Your reference images and generated models are separate.
- **Clean Uninstall** attempts to remove both the package and its local tools; depending on Blender context, you may have to finish uninstalling the extension in **Get Extensions**. Never use Clean Uninstall for a routine upgrade.
- Do not delete the entire `scripts/addons` or Extensions repository: they may contain unrelated add-ons.

### This same-version mask update

The package still shows **0.1.0** and **dev-0.3.9**. There is no automatic update detection based on a higher version number. Use the newly supplied installer ZIP.

1. Finish or stop active preparation and generation, then install the new ZIP through **Install from Disk**.
2. If Blender rejects the same installed version, remove Tiiny AI with ordinary **Uninstall**, restart Blender, and use **Install from Disk** again. Do not use **Clean Uninstall**.
3. Restart Blender after replacement, enable Tiiny AI and check its API, model and folder preferences.
4. Select the original reference photo again. Leave automatic preparation enabled, or click **Prepare / Refresh Preview** to inspect the new preparation.
5. Review the fresh Prepared image before generating with the same model preset.

The new processing revision invalidates the old prepared-image cache entry even though the extension version is unchanged. The updated PNG is generated once and then reused. Previously prepared files remain on disk. The cached Python environment and segmentation weights are reused; this update does not require clearing or reinstalling them.

## 9. Building a release installer from the GitHub source

Developers with Python 3.11+ can build an installable ZIP locally:

```sh
python tools/build_extension.py
python -m pip install Pillow numpy
python tests/run_tests.py
```

The build script uses the Python standard library. Pillow and NumPy are test-only dependencies in this development environment; do not install them into Blender's Python manually. The resulting file is `dist/tiiny_ai_for_blender-0.1.0.zip`. To regenerate the included release-style installer:

```sh
python tools/build_extension.py --output releases/tiiny_ai_for_blender-0.1.0.zip
```

Only the installer ZIP is passed to Blender. The entire GitHub repository is a source distribution containing tests and developer documentation. Offline tests exercise API shapes and UI logic; they do **not** replace a real Blender 5.3/Windows first-run test or a live Tiiny generation test.

## 10. Notes for GitHub releases

The package currently identifies itself as **0.1.0**, a pre-1.0 development version. Our development archive name is separate from this public-facing version. Before publishing a tagged GitHub Release, test the exact ZIP on a fresh Blender installation. Once `v0.1.0` is publicly released, publish fixes as `0.1.1` or later rather than silently substituting different bytes under the same tag.

The official Blender Extensions website has additional packaging/dependency rules beyond installation from a local ZIP. This project currently targets manual GitHub distribution.


## Stopping a task and recovering from disconnection

In development build **dev-0.3.9**, **Stop generation** immediately ends local waiting. A separate request asks Tiiny to stop the known task. If Tiiny is offline, the interface reports that remote cancellation is unconfirmed; check the device before another run. Preferences has **Lost connection limit (s)**, initially 300. This limits missing task-status responses, not the total model-generation time. See [Network recovery](NETWORK_AND_CANCELLATION.md).

TRELLIS Maximum continues to use the advertised 1024/high recipe. After an observed device-wide connection loss in this mode, it requires **Allow experimental 1024** in Advanced for the current session. Keep it disabled for the [next diagnostic tests](NEXT_TESTS.md); Hunyuan Maximum is unaffected.

For an update that still identifies itself as version **0.1.0**, restart Blender and install the newly supplied development ZIP. If Blender refuses to replace the same version, use regular Uninstall, restart Blender, then Install from Disk. Use **Clean Uninstall** only if you deliberately want to remove the cached optional tools. The installer contains the manifest, Python entry point and MIT license.
