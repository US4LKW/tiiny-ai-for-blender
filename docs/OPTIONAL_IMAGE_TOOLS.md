# Optional image processing modes

The Tiiny AI for Blender add-on has two independent image-input workflows. Both submit a reference image to the same Tiiny Image-to-3D API and retain all supported geometry-quality and PBR controls.

## Local image tools (default: enabled)

Open **Edit > Preferences > Add-ons > Tiiny AI for Blender** and keep **Use local image tools** checked. The add-on prepares a private Python 3.12 environment with Pillow, CPU rembg and ISNet weights in the background. This setup is not tied to your Tiiny API key. During first installation the same progress is visible in Preferences and in the sidebar; image selection is hidden until tools are ready. Masking/centering controls appear only when setup is ready, and the installer progress block disappears thereafter.

When you select an opaque image, the optional local segmentation model can remove the background. Other settings support alpha-mask cropping, centering and client-side canvas sizing. Both source and prepared PNG are previewed. A separate phase-based progress indicator appears during each preparation; CPU ONNX inference does not expose a trustworthy percent-complete metric. If the image is already transparent, segmentation is skipped. Existing dependencies and weights are retained and reused across Blender sessions.

## Direct image mode (tools disabled)

Uncheck **Use local image tools**. No Python/Pillow/rembg installation is started for this mode, and generated requests use the original selected PNG/JPG/WEBP bytes. No masking, crop, or resize is run locally. The sidebar has a single source preview, without preparation controls or a Prepared preview. The advanced panel omits all preparation options but continues to offer Seed, Target polygons, model quality overrides, and TRELLIS geometry diagnostics.

For best results, prepare a centered, isolated object image in an external editor. Prefer transparent PNG, roughly 85% subject coverage with 10-15% free space. Suggested input sizes: Hunyuan3D 512 x 512 and TRELLIS.2 1024 x 1024. These are client-side recommendations only; Tiiny may accept other valid dimensions. If you use an opaque JPG with a detailed background, the 3D model may incorrectly reconstruct the background as geometry.

Disabling local processing does not delete already installed packages/models. A running setup subprocess is allowed to finish safely but its results remain unused until the option is enabled again. To reclaim disk space, use **Remove cached tools** in Preferences. Input photos, final GLBs, prepared PNGs and shared rembg caches are never deleted by the checkbox.

## Troubleshooting

- No local setup progress when direct mode is selected: expected.
- Setup takes time: leave Blender open until the stage-based progress completes. While active, model selection remains available; source image selection and processing controls are hidden until tools are ready.
- You switched local tools on after selecting a file: the add-on prepares the selected image once setup is ready, if Auto prepare is enabled.
- You switched local tools off after preparing a file: generation uses the original selected image instead of the previous prepared PNG.
- API authentication and Tiiny generation: independent of local preparation. The same API address/key and model selector work in both modes.
