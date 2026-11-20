# First-use local image preparation

When **Use local image tools** is enabled in Add-on Preferences (the default), the add-on prepares a reference photo before sending it to the selected Tiiny 3D model. **3D generation takes place on Tiiny; foreground segmentation takes place on the computer running Blender.** Both operations are separate. When the option is disabled, the original photo is sent directly to Tiiny, unchanged, and the local image-preparation pipeline is not used.

## What happens when you select your first image

1. **Source check.** The add-on validates the image and looks for an existing prepared image in the selected output directory.
2. **Local Python tools.** If needed, `uv` creates a reusable isolated Python 3.12 environment and installs Pillow. This is not the Blender-bundled Python environment.
3. **Background removal dependencies.** If background removal is enabled and the image has no useful transparency, `rembg[cpu]` is installed once. Already-transparent PNGs skip this step.
4. **Model loading and possible weight download.** `rembg` loads the selected segmentation model, such as `isnet-general-use`. Its ONNX weight file may be downloaded on the first use. The weights normally remain in the user's `.u2net` cache, independent of the Blender project folder. Deleting or moving your `prepared` output folder does not remove those model weights.
5. **CPU foreground mask.** Once the model has loaded, it computes the alpha mask. For a large photo or slower CPU, this step can take longer than simple resizing.
6. **Canvas and saved files.** The subject is cropped/centered/resized according to the chosen settings and a PNG, mask and `.prep.json` are written to `Generated models/prepared`.
7. **Blender preview.** Blender loads the saved PNG as a thumbnail. A temporary placeholder during this step is **not** evidence of a failed segmentation.

The preparation bar reports **workflow stages, not bytes downloaded, inference percentage, or expected completion time**. It can remain on one stage while a network download or CPU inference is in progress. The elapsed-time display helps establish that a job is still underway. On completion, the regular image preview and `Prepared WxH` status replace it.

## Distinguishing normal waiting from errors

- `Installing local Python ...`: one-time setup; internet access is required.
- `Installing CPU background removal tools ...`: one-time installation of `rembg` dependencies when needed.
- `Loading background model (first use may download weights)`: the local ONNX model is being opened and may download if it is not yet cached. **There is no reliable byte-level progress indicator exposed by the current `rembg` call.**
- `Computing foreground mask on CPU`: the segmentation model is running locally.
- `PNG saved. Blender is loading the thumbnail ...`: the prepared file exists; Blender's preview renderer has not finished.
- `PNG is ready. Thumbnail delayed`: the file is usable. Try the thumbnail-only Reload button or the Open PNG icon.
- `Image preparation failed`: a genuine error. Check the message, your internet access for first use, the available disk space, and the optional local setup log.

When preparation is active, Prepare and Reload are disabled to avoid duplicate jobs and misleading `No prepared PNG` toasts. Do not delete or move the working output folder while a preparation is running.

## Local caches and logs

On Windows, the reusable image-preparation environment is stored in:

```text
%LOCALAPPDATA%\TiinyAIForBlender\image-prep-py312\
```

The add-on's private model-weights cache is separate:

```text
%LOCALAPPDATA%\TiinyAIForBlender\rembg-models\
```

Existing shared weights under `%USERPROFILE%\.u2net` or `%USERPROFILE%\.rembg` may be copied once, but are not modified or deleted by the add-on.

The optional local setup log is:

```text
%LOCALAPPDATA%\TiinyAIForBlender\image-prep-setup.log
```

Use **Edit > Preferences > Add-ons > Tiiny AI for Blender > Optional local image tools** to check setup, toggle direct-image mode or open the diagnostic log. The log is local and does not intentionally include the Tiiny API key, prompts or source image contents, but you should still review it before sharing publicly.

You do **not** need to delete any of these directories to update the add-on. Reinstallation normally reuses the existing environment and weights. An invalid or partially deleted environment may require additional investigation; do not repeatedly uninstall Blender to repair it.

## Useful checks for a bug report

- Add-on and Blender versions, Windows build, selected segmentation model.
- Whether the image already has alpha or is an opaque JPG.
- Whether the first-use model-weight file is already cached, according to Preferences.
- The exact stage that stayed active, elapsed time, and full error message if one appeared.
- The saved prepared PNG and `.prep.json` if present (do not share private photos without permission).

The connection/API key check only tests Tiiny authentication and is independent of local image-preparation setup. `Not checked` after a fresh install does not mean that the local mask failed.
