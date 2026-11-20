# Changelog

## 0.1.0 / dev-0.3.9 (same-version image-mask refresh)

- Retain both the public package version and development-build identifier.
- Add default-enabled **Clean soft background** for fresh segmentation masks, with a protected soft fringe and thin-feature handling. Do not discard every component except the largest or apply blanket erosion/closing.
- Preserve existing source transparency by default. Provide an explicit **Clean existing alpha** option for users who want to process a supplied mask.
- Request the segmentation mask separately and combine it with the original RGB, avoiding an extra dark composite at soft boundaries.
- Clean the mask before calculating the object crop. Save the mask from the final prepared PNG so that it matches the displayed and transmitted alpha channel.
- Derive the crop from all alpha retained by cleanup, preventing the older crop cutoff from clipping protected faint strands.
- Include a separate preparation revision, `mask-cleanup-1`, in the prepared-image cache identity and diagnostics. Old prepared files remain on disk; new preparation uses a new cache entry.
- Reuse the existing private Python/rembg/model cache. This refresh does not require downloading a different segmentation model.
- Retain the Hunyuan and TRELLIS generation recipes, supported manual overrides, PBR controls, network recovery and cancellation behavior.
- Document the same-version replacement workflow and the limits of automatic mask cleanup. A local mask improvement is not a demonstrated repair of TRELLIS geometry.
- Pass 22 offline test scripts plus Blender 4.3.2 registration/property checks (23 validation entries total); validate the rebuilt extension package. Add semantic mask and end-to-end crop fixtures, and synchronize cancellation-test teardown before deleting temporary files.

## 0.1.0 / dev-0.3.9 (cancellation and controlled test audit)

- Stop local generation waiting immediately, independently of remote cancellation; suppress late stage results and queued imports after Stop.
- Bound missing-response waiting to a configurable 300 seconds by default. Keep responsive long-running tasks alive and never automatically repeat a stage-creation POST.
- Handle delayed task IDs, release HTTP error streams, and keep Stop visible across scene changes and local-tool setup states.
- Create atomic version-3 reports before capability retrieval and update task IDs, last progress, network errors and cancellation outcomes during execution.
- Require a session-only opt-in for effective TRELLIS shape resolutions above 512. Maximum retains its original advertised 1024 recipe; Hunyuan presets are unchanged.
- Prefer detailed per-stage parameter schemas over broader top-level quality enums.
- Correct Preserve 512 descriptions: geometry-stage projection is disabled, but Tiiny export can independently enable projection. The controlled duck test closed boundary edges while retaining surface banding.
- Include the MIT license in the installer ZIP and add English analysis, follow-up test and network-recovery guides.
- Pass 21 test scripts plus real Blender 4.3.2 registration/property checks (22 checks total); validate the installer manifest with Blender. The updated client has not been tested on a real Tiiny or Windows/Blender 5.3 here.

## 0.1.0 / dev-0.3.8 (development source refresh, pre-release)

- Keep the extension ID and manifest version at `tiiny_ai_for_blender` / `0.1.0`.
- Use passive, non-clickable image thumbnails instead of clickable preview selectors. Remove captions under thumbnails.
- Show each image's full file path in a hover tooltip on the adjacent information icon; clicking that icon copies the path without opening an image popup.
- Bundle the installable extension in `releases/tiiny_ai_for_blender-0.1.0.zip` inside the GitHub source distribution.
- Expand English installation and first-use documentation; include dedicated `docs/INSTALLATION.md` and updated offline tests.
- No changes to Tiiny API contracts, generation profiles, local background-removal setup, PBR handling or GLB export.

## 0.1.0 (development packaging milestone)

- Switch from the generic legacy `addon.py` module to a uniquely named Blender Extension `tiiny_ai_for_blender`.
- Add `blender_manifest.toml` with a stable package ID and local network/file/clipboard permission declarations.
- Place the Blender entry point in the package's `__init__.py` and fix self-uninstall to use the modern Extensions API when appropriate.
- Separate GitHub source layout from the installable Blender extension ZIP; provide reproducible build script and automated tests.
- Preserve the existing v0.3.6 Hunyuan3D/TRELLIS.2 stages, PBR support, quality profiles, optional image tools, cache reuse, progress bars, and UI.
- No deliberate model-generation behavior changes. New packaged installation requires a real Blender 5.3 smoke test.

This is the first project version for future GitHub releases; v0.3.7, v0.3.8 and v0.3.9 in source ZIP names identify continuing development iterations. The extension's internal version remains 0.1.0. See [Development history](docs/DEVELOPMENT_HISTORY.md) for prior experimental snapshots.
