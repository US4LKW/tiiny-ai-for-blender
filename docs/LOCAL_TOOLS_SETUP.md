# Local image tools — setup, cache and cleanup

## What happens when the add-on is installed or enabled?

With **Use local image tools** enabled (the default) the add-on starts a **background** check and (if required) installation of its private image processing dependencies about one second after registration. Installing the add-on does not wait for this process and does not require the Tiiny Pocket Lab to be connected. Uncheck the option in Add-on Preferences to use original images directly with no local preparation or automatic dependency installation.

1. Check the private image-preparation environment.
2. Install Python 3.12 with `uv` if missing.
3. Install Pillow if missing.
4. Install CPU `rembg` if missing.
5. Download/validate the default `isnet-general-use` ONNX model. If an existing *shared* copy is available, the add-on first copies it into its own cache, without modifying the original.
6. Mark tools ready only after validation. The bar reaches 100% and is then hidden from the 3D View sidebar. Preferences retain a compact installed indicator.

The progress bar is an *installation phase indicator*, **not** a byte-accurate download gauge or a remaining-time estimate. In v0.3.4, stage labels are intentionally short to fit both the sidebar and Preferences. The current step, elapsed time, and a note about unavailable download percentages are shown separately; full diagnostics remain in the setup log. Packages and model files can take longer during the first installation. If the model weights are already cached, the installation is faster. Re-enabling Blender does **not** reinstall the packages or re-download the default ISNet model when the private environment and validated weights are present. The setup panel is shown only during active setup, if tools are missing, or when setup fails. On-demand segmentation still loads those weights into RAM for each preparation process; this is not a network download.

During setup, the same progress appears in **Preferences → Add-ons → Tiiny AI for Blender → Optional local image tools** and the **N → Tiiny AI** sidebar. Image selection and all image-processing controls remain hidden while setup is running. Once setup finishes, select a reference image; automatic preparation then uses the installed tools. Once setup succeeds, the installer block disappears from the sidebar. Preferences continues to show Install / Retry, Remove tools and Clean Uninstall commands after successful installation. Do not close Blender in the middle of the first installation.

## Dependencies

Blender **Edit > Preferences > System > Network > Allow Online Access** must be enabled for any first-time dependency downloads.

`uv` (the Astral package manager) must be installed and accessible on the `PATH`. On Windows:

```powershell
winget install --id=astral-sh.uv -e
```

Restart Blender after installing uv if the add-on did not find it. Setup errors and recovery buttons appear in Preferences. The setup diagnostic log contains status messages; it never intentionally writes Tiiny API keys or image data.

## Where the files are stored

On Windows:

```text
%LOCALAPPDATA%\TiinyAIForBlender\
    image-prep-py312\      # Python and installed packages
    rembg-models\          # This add-on's private ONNX weights
    .tiiny-setup-complete    # Validation marker
    image-prep-setup.log     # Setup diagnostics
```

On Linux, use `~/.cache/TiinyAIForBlender` instead. Only the private folder above belongs to this add-on. If an old copy exists in `%USERPROFILE%\.u2net` or `%USERPROFILE%\.rembg\models`, it may be **read and copied**, but is never deleted by this add-on.

If the user selects an alternative segmentation model (for example, BiRefNet), it is fetched into the same private model directory when first used. The eager installer validates only the default ISNet model.

## Testing the first-run experience

After the add-on has completed installation, press **Remove local tools** in Preferences and confirm. This removes the add-on-owned Python environment and private model weights but retains the add-on and all generated models and input photos. Click **Install / Retry tools** to watch a fresh setup.

**Note:** an old shared rembg cache can be reused by copying it, so this test may omit the network download while still reinstalling and validating the private environment. To test a truly empty system, use a fresh Windows user profile or a test VM; do not delete shared caches of unrelated applications.

## Uninstalling safely

Use the confirmed **Clean Uninstall (add-on + local tools)** button in Preferences to clean the private folder and ask Blender to remove the add-on. If Blender's removal operator cannot finish, the message instructs you to click Blender's regular Uninstall button.

The standard Blender **Uninstall** button removes the add-on script but does *not* automatically delete files installed outside the script directory. The add-on cannot distinguish disabling from uninstalling in `unregister()`, therefore it never deletes caches just because it is disabled. If you already used the standard Uninstall button, remove only `%LOCALAPPDATA%\TiinyAIForBlender` manually if you no longer need it.

**Never delete** a user's configured `Incoming photos` or `Generated models` directory during cleanup; it contains user-owned files.

## Per-image preparation progress

Image preparation still displays its own progress stages and elapsed time in the sidebar. These stages cover mask computation, center/crop, PNG saving and thumbnail creation. `rembg` / ONNX Runtime do not expose a reliable percentage for the CPU mask itself through this interface, so the indicator is intentionally phase-based, not a fabricated progress estimate.
