# Preview and local background removal troubleshooting (v0.3.4)

## When a prepared image has no thumbnail

1. Check that the selected Generated models folder still exists and that `prepared/tiiny_prepared_*.png` is present.
2. If the prepared file **exists**, press **Reload image thumbnails** (the small refresh icon next to Prepare / Refresh Preview). This does not run rembg or the Tiiny 3D models.
3. If the file **does not exist** after moving/deleting a folder, first set the intended Generated models location in Add-on Preferences, then press **Prepare / Refresh Preview**. This actually prepares the PNG at that destination.
4. For visual inspection without Blender's thumbnail subsystem, use **Open prepared PNG** next to the refresh button.
5. Avoid moving the active output folder during an ongoing preparation or model generation. Existing tasks may finish at the path they captured when started.

## Local segmentation environment

- The add-on never installs packages into Blender's built-in Python.
- Windows environment directory: `%LOCALAPPDATA%\TiinyAIForBlender\image-prep-py312\`.
- The installed Python is at `%LOCALAPPDATA%\TiinyAIForBlender\image-prep-py312\Scripts\python.exe`.
- Pillow and `rembg[cpu]` are installed during the automatic first-run setup after the add-on is enabled.
- The default ISNet model weights are kept in the private `%LOCALAPPDATA%\TiinyAIForBlender\rembg-models` directory. An older shared `.u2net`/`.rembg` copy may be copied into this private directory on first setup; subsequent runs use the private copy without re-downloading. Other rembg models require their own one-time retrieval.
- If the isolated environment is damaged, use the confirmed **Remove local tools** action in Add-on Preferences, followed by **Install / Retry tools**. This intentionally repeats setup but does not modify Blender Python or user data.

## Prepared ZIP example inspected

The user-provided example contained a valid RGBA PNG (512x512), a compatible alpha mask, and a prep JSON report showing `segmentation_applied: true` and `segmentation_model: isnet-general-use`. The thumbnail could be missing despite all these files being valid. Its old prep report included an absolute Windows mask path; the fix stores a relative filename instead.

## Verification scope

The change was tested using a mock Blender thumbnail collection and a simulated persistent environment. It has not yet been reproduced in the user's real Blender 5.3 installation. The Tiiny 3D API and generation presets were not modified.

## Native image preview tooltip (v0.3.6)

The redundant filename label beneath each thumbnail has been removed. The regular Blender icon-view widget exposes the complete absolute file path in its item tooltip when hovered. If a Blender build does not support that icon-view widget, the add-on falls back to the previous large image icon. The source picker still displays a short filename. Hovering the preview never starts image preparation or an API request.
