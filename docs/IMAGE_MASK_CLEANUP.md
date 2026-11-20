# Foreground-mask cleanup

This guide describes the image-preparation refresh within package **0.1.0**, development build **dev-0.3.9**. The 3D model presets and network behavior are unchanged.

## What this fixes

A segmentation mask can contain faint background residue even when the prepared image looks transparent. The diagnostic duck image retained a broad low-opacity shadow beneath the object. Such residue can influence the visible object bounds and may affect how a 3D model interprets the image.

The update adds a conservative cleanup step before cropping and centering. It also uses the mask with the original RGB values rather than applying an extra dark composite at soft boundaries. This improves the local preparation path; it is not a guarantee that TRELLIS will stop generating all unwanted geometry.

## Controls

Open the **Tiiny AI** sidebar, then **Advanced model settings > Reference image preparation**. Local image tools must be enabled and ready.

| Control | Default | Purpose |
| --- | --- | --- |
| Clean soft background | On | Reduce broad weak-alpha residue in a newly generated segmentation mask. |
| Clean existing alpha | Off | Explicitly allow cleanup of an image that already has transparency. Requires Clean soft background. |

Leave **Remove background** and **Auto prepare before generation** enabled for ordinary photos. Select the original photo and wait for the Prepared thumbnail. Changing a cleanup option invalidates the old preview and, when automatic preparation is enabled, queues a new preparation.

For an already prepared transparent PNG, leave **Clean existing alpha** off to retain the supplied mask. Cropping, resizing and centering still follow their own existing settings. To send a prepared file byte-for-byte without local processing, disable **Use local image tools** in extension Preferences.

If cleanup removes a desired faint feature, turn **Clean soft background** off and prepare the image again. The original source remains available because it is never overwritten.

## Processing behavior

1. Read the source, apply its orientation metadata and inspect transparency.
2. For an opaque source with background removal enabled, obtain the segmentation mask separately from rembg and combine it with the original RGB.
3. Apply cleanup to a fresh mask when enabled. Apply it to a supplied alpha mask only when explicitly requested.
4. Determine the object bounds from the processed mask, then crop, resize and center according to the existing canvas and coverage settings.
5. Save the prepared RGBA PNG, its matching final alpha mask and a preparation report.

The conservative cleanup protects mask values at or above 64/255 and a narrow soft fringe around supported foreground, approximately two pixels at a 1024-pixel reference scale. Thin attached low-opacity features receive additional protection. Broad weak regions farther from supported foreground can be removed. The algorithm retains multiple supported object components instead of keeping only the largest one.

When cleanup has analyzed a mask, cropping uses all of its retained nonzero alpha, including faint protected strands. It does not apply the older alpha-above-20 crop cutoff to that result. A mask that is left unchanged by cleanup receives the same treatment. Untouched supplied alpha and cleanup-disabled paths retain their previous crop policy.

It does not apply blanket erosion or closing to the whole object. RGB remains straight-alpha color; it is not repeatedly multiplied by the mask. Fully transparent pixels can have their RGB cleared without changing visible foreground color.

The mask and PNG are saved after final resizing and canvas placement, so the mask file corresponds to the actual prepared input. Cleanup statistics and the processing revision are retained in the preparation report and in generation diagnostics when a prepared image is used.

## What remains uncertain

The method cannot always distinguish a soft shadow from a real transparent or faint object part using a mask alone. Hair, fur, glass, translucent fabric and very low-opacity details still need visual inspection. Protecting thin features reduces the risk of damage; it does not prove preservation of every possible subject.

Removing visible mask residue is directly testable without a Tiiny device. Whether that change improves a particular 3D result requires a controlled generation. It does not by itself fix remeshing, double surfaces or final-export behavior inside the Tiiny adapter.

## Cache behavior after this update

The public and development version numbers remain unchanged. A separate image-processing revision, **`mask-cleanup-1`**, is included in the prepared-image cache key.

- An old prepared PNG is not silently reused as if it had received the new processing.
- A fresh preparation creates a new cache entry once for the selected source and settings.
- Repeating the same preparation reuses the new entry.
- Changing cleanup settings creates or selects the corresponding entry.
- Older prepared images, source images and generated GLBs are left untouched.
- Existing Python packages and downloaded segmentation weights remain cached.

There is no need to remove tools, delete model caches or select a different neural network for this update.

## A focused check

1. Install the refreshed ZIP using the [same-version update instructions](INSTALLATION.md#this-same-version-mask-update).
2. Select the original photo used for the previous test.
3. Keep background removal, automatic preparation and Clean soft background enabled. Leave Clean existing alpha disabled for this original-photo check.
4. Inspect the new Prepared image, especially the area beneath the object and any thin edges.
5. If comparing 3D output, reuse the previous image subject, Standard preset, seed and geometry settings. Change only preparation, and keep the new PNG, mask and JSON report.

A full preset sweep or a Maximum/1024 run is not required to evaluate this local preparation change.

## Validation of this refresh

On 2026-11-20, all **23 validation entries** passed: 22 offline test scripts and a real Blender 4.3.2 headless registration/property test. Blender's extension validator also accepted the rebuilt installer. The checks include:

- Original RGB preservation in the actual image-preparation subprocess with a controlled segmentation backend.
- Empty, opaque and uncertain masks; connected faint strands; detached foreground parts; real holes; and repeated cleanup.
- End-to-end cropping, resizing and centering of an alpha-16 strand that the old crop cutoff could truncate, including a cleanup result with no removed pixels.
- The matching saved alpha-mask file, cleanup disabled, existing transparency preserved by default, and explicit existing-alpha cleanup.
- Cache invalidation for this processing revision and both cleanup options.
- Real Blender RNA defaults, settings snapshots, thumbnail invalidation, and both model panels.
- Existing preparation-cache, optional-tools, generation-request, cancellation, network-recovery, and extension-package tests.

A test-fixture teardown race was also corrected: cancellation/report-writing test threads now finish before temporary report files are removed. This is a test-only change; the add-on's network runtime is unchanged.

The exact production cleanup helper was separately applied to the saved 1024 x 1024 duck mask from the diagnostic archive, without cropping or resizing, so before/after pixels stayed aligned:

| Measurement | Before | After |
| --- | ---: | ---: |
| Nonzero-alpha pixels in the measured shadow rectangle | 23,112 | 0 |
| Alpha changes among the 409,511 pixels initially at alpha >=64 | - | 0 |
| Alpha changes among the 6,460 retained weak-alpha pixels | - | 0 |
| Retained RGB changes in direct mask composition | - | 0 |

The shadow rectangle is `[580, 843, 925, 910]`, with right and bottom exclusive. Cleanup removed 57,967 weak-alpha pixels across the complete image. These counts describe this image and do not establish universal semantic mask accuracy.

The original JPEG was not present in that archive. This measured check therefore cleans an existing saved neural mask; it does not rerun ISNet on the original photograph. Fresh segmentation integration uses controlled mask fixtures in the offline tests. No new Tiiny generation, Windows/Blender 5.3 run, or visual Blender UI validation was performed here.

For the backend API used by the implementation, see the upstream [rembg mask-only return path](https://github.com/danielgatis/rembg/blob/main/rembg/bg.py). The add-on requests that mask and combines it with the source RGB before local cleanup and framing.
