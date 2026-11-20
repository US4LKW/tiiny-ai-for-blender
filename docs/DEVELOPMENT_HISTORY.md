# Development history

## 0.1.0 / dev-0.3.9 - Same-version image-mask refresh

Add conservative cleanup of broad weak-alpha residue before cropping, preserve supplied transparency by default, and combine the segmentation mask with original RGB without an extra dark composite. A separate preparation revision invalidates stale prepared-image cache entries while retaining the installed Python environment and model weights. Public and development version identifiers, generation recipes and networking remain unchanged. See [Mask cleanup](IMAGE_MASK_CLEANUP.md) and [CHANGELOG](../CHANGELOG.md).

## dev-0.3.9 / public version 0.1.0

Immediate local Stop, bounded network recovery, live diagnostic journals, experimental TRELLIS 1024 opt-in, and detailed-stage schema precedence. See [CHANGELOG](../CHANGELOG.md), [controlled test audit](TEST_FINDINGS_2026-11-20.md), and [follow-up tests](NEXT_TESTS.md). Hunyuan recipes and the actual TRELLIS preset parameter values are retained.

## v0.3.6 - Sidebar UX and maintenance regression fixes

- Restore **Install / Retry**, **Remove tools** and **Clean Uninstall** in Add-on Preferences even when the private ISNet environment is already installed and cached. Destructive actions remain disabled while setup, preparation or 3D generation is active.
- Hide the image picker, source thumbnail and all local image-preparation controls while the optional image tools are being installed. Show the same setup progress in the sidebar and Preferences. The normal image workflow appears only after the tools are ready; Direct Image mode remains available independently.
- Replace long Tiiny raw status messages with one-line human-readable activity labels (`Shape diffusion 13/50`, `Decode volume 96/887`, `Preparing PBR`, `Exporting GLB`). Keep the complete raw status accessible through the message tooltip, with a click-to-copy action.
- Remove the duplicate filename caption below the Original and Prepared thumbnails. Use Blender's native preview selector with an item tooltip containing the absolute path; fall back to the original large icon if the icon selector is not available.
- Shorten selected static sidebar messages that could be clipped. Keep per-stage percentage and timing information in the existing progress bar and generation JSON report.
- Add a regression suite covering six live Tiiny progress messages, setup-panel gating, all three Preferences maintenance actions after setup succeeds, tooltip metadata, and Direct Image mode.
- No changes to Hunyuan3D or TRELLIS.2 generation requests, quality presets, PBR stages, Tiiny API authentication, image-preparation algorithms or persistent local caches.

# v0.3.5 - Optional local image tools and direct-image mode

- Add **Use local image tools** in Add-on Preferences, on by default. Disabling it prevents automatic setup and any local foreground masking, cropping, centering, resizing or prepared-image generation. Private cached packages/models remain intact.
- Keep the model selector and source image picker accessible during first-time installation. Display shared installer progress in Preferences and the sidebar; hide regular preparation controls until setup is ready.
- Hide the persistent **Tools ready** block from the sidebar after installation, while keeping a compact installed indicator in Preferences. Continue showing per-photo preparation progress when it actually runs.
- Provide Direct image mode with a single source preview and input guidance: transparent square PNG recommended, 512 x 512 Hunyuan / 1024 x 1024 TRELLIS client canvas recommendations, object occupying about 85% of the frame. Retain PBR, presets, manual overrides, GLB generation and diagnostics.
- Hide all image-preparation settings in the sidebar and Advanced when local tools are disabled. Send original image bytes to the Tiiny API unchanged.
- Change successful model status to **3D + PBR ready** so it fits the narrow sidebar without wrapping.
- Add offline tests for both UI modes, live setup overlay, preference toggling and bypassing local processing on both models. No changes to the Tiiny 3D pipeline itself.

## v0.3.4 - Compact setup and progress messages

- Fix first-install status text that was cut in the middle of words in Blender's narrow sidebar or add-on preferences.
- Use concise stage labels (Python, Pillow, CPU packages, ISNet weights, validation), with separate elapsed time and an explicit note that download percentages are not reported.
- Apply whole-word, width-limited messages to API connection, model checks, photo preparation, and 3D job results. Keep complete setup diagnostics in the existing log.
- Prefer "ISNet ready (cached)" after successful setup. An already installed private environment and model weights are reused on subsequent Blender starts and on subsequent images; no automatic reinstall is introduced.
- Do not mask a failed setup with a misleading Ready status when stale readiness marker files remain.
- Shorten several excessively long static labels in Preferences and the sidebar. No changes to 3D model requests, quality presets, image segmentation algorithms, or output formats.
- Add a focused regression test for stage 5, narrow labels, cached readiness, and error visibility.

# Changelog

## 0.3.2 — First-run preparation clarity

- Explain the isolated Python/Pillow/rembg setup and the separate ISNet model-weight download with stage-by-stage status inside Blender.
- Show elapsed preparation time and a workflow-stage bar. This bar marks workflow stages, **not** downloaded bytes or predicted remaining time.
- Stream stage markers emitted by the local preparation subprocess without blocking Blender's UI, while safely reading both stdout and stderr.
- Display `Preparing...` instead of `Not prepared` before the output file exists; disable the second Prepare and thumbnail-refresh actions during active preparation.
- Distinguish a prepared PNG on disk from Blender's pending or delayed thumbnail. The saved PNG is still usable even if the thumbnail is delayed.
- Add a read-only local dependency/cache summary in Add-on Preferences and an optional setup log viewer. The log excludes API keys and image contents.
- Detect common network/download and dependency errors and show concise recovery hints instead of a raw traceback in the cramped sidebar.
- Keep existing Hunyuan3D / TRELLIS.2 request formation, quality presets, geometry diagnostics, PBR and output file paths unchanged.
- Add first-install simulations, streaming subprocess-stage tests, and existing-alpha regression checks.


## v0.3.1 - Persistent background remover and resilient file previews

- Fix stale preview icon handling when users delete, replace or move a prepared-output folder while Blender remains open. Generate unique Blender file-preview keys on reload instead of recycling the same icon ID, and retry a small number of unresolved thumbnails.
- Add a **Reload image thumbnails** button that does not rerun image preparation, download dependencies, contact Tiiny, or start generation.
- Replace one-off `uv run --with` calls on every image with a persistent and isolated Python 3.12 virtual environment. Install Pillow once, install the optional local CPU rembg package only when needed, and execute the local Python directly for all later preparations.
- Do not claim to be downloading dependencies during ordinary cached processing. A first installation of the persistent environment may still download packages; initial segmentation weights may still be retrieved once by rembg.
- Store mask filenames rather than machine-specific absolute paths in new `.prep.json` files; correct legacy mask path references in memory when reading cached results.
- Preserve both Tiiny models, generation quality presets, texture options, artifact handling and the established Image-to-3D request paths unchanged.
- Add regression tests for folder removal/replacement, thumbnail cache invalidation and one-time environment installation.

## v0.3.0 - Explicit TRELLIS presets and reproducible diagnostics

The surface profile remains experimental. Mesh-quality improvements require a real Tiiny comparison and are not claimed as proven.

- Separate TRELLIS generation tiers from geometry processing. Draft uses the advertised 512/fast path, Standard explicitly selects 512/balance, and Maximum selects 1024/quality when supported. Higher resolution is not a promise of better topology.
- Add an opt-in Preserve detail 512 candidate with remesh resolution 512 and one closing iteration, with decimation and geometry projection disabled. Preserve the original Off path and legacy comparison profiles.
- Keep advanced manual parameters for both models; support explicit overrides on top of a selected preset and a selectable Custom base.
- Validate enabled parameter values against refreshed device capabilities before submission. Correct the client face-target range to accommodate the published TRELLIS maximum of 2,000,000, while rejecting invalid explicit values below the device minimum.
- Improve generation diagnostics with image hashes and exact per-stage requests. A client request record is not a record of unpublished server internals.
- Add optional intermediate shape/geometry GLBs, complete capability snapshots, artifact lineage, final-output hashes, and geometry counts. Preserve partial reports when a job fails after report creation; exclude API keys and full local source paths.
- Reserve the last progress percentage for saving and Blender import, avoiding a 100-to-99 percent drop. Validate the GLB container and require an output from the final requested stage.
- Rename Target Faces to Target polygons. An explicit polygon budget enables decimation in Preserve detail 512; contradictory manual settings are rejected.
- Replace the Russian README files with English documentation. Add contribution guidance, issue-reporting structure, ignored local outputs, and preserved license notices for source publication.
- Retain the working Hunyuan generation path, PBR toggle, source previews, explicit photo selection, configurable folders, and direct Tiiny API workflow.

## v0.2.7 — Experimental TRELLIS geometry processing and diagnostic report

- Added `Geometry cleanup` field (TRELLIS only), with Off (original flow), Tiiny cleanup (server defaults), Remesh 256 and Remesh 512. Remesh parameters are dispatched to the Tiiny `simplify` stage and only if the model's actual capability schema advertises their names.
- Geometry cleanup is opt-in, default Off. No changes to working Hunyuan3D generation. PBR and both models remain available.
- If cleanup selected, shape → simplify → texture → export becomes the stage plan; intermediate `geometry_artifact` is forwarded by `input_refs` to the export stage.
- The progress-bar stage weights adapt to include the new geometry stage.
- Generation report records `trellis_geometry_cleanup`, stage durations, transient poll failures and returned artifact types for troubleshooting. No API keys are saved in this report.
- All effects are experimental until validated on real Tiiny Pocket Lab. 512/1024 pipeline and texture resolution remain separate concepts.

## v0.2.6 — Real sidebar progress bar + upstream-informed Hunyuan Custom

- Added Blender 5.3 built-in `UILayout.progress(factor, type="BAR")` under Generate, reading the existing stage-weighted Tiiny job percentage. No new network polling, heavy drawing, dependencies or MCP bridge.
- Kept numeric progress and stage context in one bar; retains progress on cancellation and reaches 100% after import.
- Examined Tencent Hunyuan3D-2.1 API documentation and PBR pipeline; identified upstream step/guidance parameters, but distinguished them from unverified Tiiny server bounds.
- Hunyuan **Custom** now optionally displays typed `shape.step`, `shape.guidance_scale`, `texture.paint_step` and `texture.guidance_scale`, only if that precise name appears in the real Tiiny `capabilities.params`. All are default-disabled.
- Added a second guard to avoid sending unpublished Custom parameter names if capabilities change.
- Preserved the original Tiiny-supported Standard, Draft and Maximum presets and both Hunyuan/TRELLIS generation pipelines.
- Added regression tests for source-gated optional controls and Blender native progress rendering.

## v0.2.5 — Source session guard, readable quality presets, boolean UX

- Removed truncated technical stage-parameter lines from the main Draft/Maximum selector. A compact label remains in the main panel; complete quality settings (and octree/pipeline hint when advertised) appear in Advanced.
- Fixed persistent reference photo: only a source explicitly picked in the current session can be previewed or auto-prepared. Restored .blend / stale Scene image properties are ignored. A Clear Image button is available.
- Changed optional boolean Custom parameters (TRELLIS Simplify, Project Geometry) from two checkboxes to a single Auto / Enabled / Disabled control. Existing v0.2.4 overrides are migrated on schema refresh.
- Clamped persisted invalid numeric controls to API bounds (notably TRELLIS texture_size 256–8192; 0 is not a valid explicit override).
- No MCP dependencies or paid services added. Hunyuan3D and TRELLIS.2 PBR pipelines remain as in v0.2.4.
- Added regression tests for session image consent, clear, tri-state booleans, and capabilities-based quality presets.

## v0.2.4 — Directories, Preferences, capability-aware controls

- Fixed prepared-image cache: output directory participates in signature and cache.
- Added Input and Output folder selectors to Add-on Preferences. Both default to Documents/Tiiny_3D; folders are not created at startup.
- Moved the 3D engine selector into persistent Add-on Preferences. Sidebar and model status use the same source of truth.
- Added explicit image picker starting from Incoming photos folder; source image selection is session-only and cleared on registration and `.blend` load.
- Parsed real Hunyuan and TRELLIS top-level quality capabilities. Draft/Maximum now affect actual Tiiny quality controls instead of empty presets.
- Fixed nullable Pydantic `anyOf` schemas. Converted TRELLIS fields to typed dropdowns, bools and integer fields with range validation.
- Hid extra stage controls except in Custom mode; skipped unsupported raw JSON-only parameters and automatic output_name.
- Maximum no longer forces undocumented/risky texture_size=8192 based solely on upper numeric bounds.
- Activated simplify stage when manually selecting simplify-specific Custom overrides.
- Added offline tests with the two actual exported capability schemas; validated path changes with an actual prepared image pipeline.
- No MCP, paid services or external cloud API integration.

## 0.3.3 — Eager local tools installer and explicit clean removal

- On enabling the add-on, start the local Python/Pillow/rembg/ISNet setup in a background worker without blocking Blender, Preferences, or API-key entry.
- Show the same installation state, stage-based progress bar and elapsed time in both Add-on Preferences and the 3D Viewport sidebar. Show 100% only after the private ISNet model is downloaded and validated.
- Keep the image-preparation progress bar for per-photo masking, cropping and thumbnail generation; setup progress represents *stages*, not an inaccurate network download percentage.
- Store downloaded rembg model weights in `%LOCALAPPDATA%\\TiinyAIForBlender\\rembg-models` (or `~/.cache/TiinyAIForBlender/rembg-models` on Linux). The add-on does not modify or delete rembg model caches belonging to other applications.
- Reuse already-downloaded shared ISNet weights by copying them into the private cache once when available; the original shared file is preserved.
- Add **Install / Retry tools**, **Remove local tools**, and **Clean Uninstall (add-on + local tools)** actions in Preferences, each non-destructive to source images, prepared PNGs, GLBs and user-chosen output directories. Removal is blocked during active setup/preparation/generation.
- Use Blender's own add-on removal operator for the confirmed Clean Uninstall path. The ordinary Blender Uninstall action does not clean the external model cache; Blender calls `unregister` for both disable and uninstall, so deleting assets there would risk data loss on ordinary disable.
- Maintain existing Tiiny 3D API pipelines, quality presets, and preparation behavior. No external Tiiny API or MCP changes.

See [LOCAL_TOOLS_SETUP.md](LOCAL_TOOLS_SETUP.md) for installation, progress and clean uninstall behavior.
