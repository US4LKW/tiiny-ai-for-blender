# Focused follow-up tests

Use development build `dev-0.3.9` (public extension version `0.1.0`). Keep the original results. Do not repeat the failing 1024 run as part of this first follow-up.

## Common settings

Use the same prepared duck image for all three runs, with the same crop and alpha. Select **TRELLIS.2**, **Standard**, **Seed = 42**, **Target polygons = 0**, and disable **Enable manual overrides**. In Advanced, enable **Save intermediate meshes**. Leave **Allow experimental 1024** disabled.

The image canvas is 1024x1024; Standard's shape pipeline is 512. These are different resolutions and are not contradictory.

## Three isolating runs

| ID | Surface | PBR | Purpose |
| --- | --- | --- | --- |
| D01 | Off | Off | Inspect the shape-stage preview without texture generation, final textured export, or remeshing. |
| D02 | Preserve detail 512 | Off | Inspect geometry after remeshing but before the textured export stage. |
| D03 | Preserve detail 512 | On | Compare saved shape and geometry previews with the final textured GLB from the same run. |

Keep the final GLB, its JSON report, and the complete `diagnostics/<result-name>/` subfolder for each run. The JSON records which optional previews were saved. If one is unavailable, keep the report rather than rerunning repeatedly.

The key comparison is inside D03: the shape preview, geometry preview, and final output share one generation's artifacts. Compare D01/D02 across runs only after checking image hashes and shape settings. A fixed seed improves reproducibility but does not establish identical output on every backend.

## What to inspect

Use Solid shading or a neutral material first. Use identical scale, viewpoint and lighting for comparisons. Look for:

- missing patches and open cracks;
- concentric rings or stair-step bands;
- extra geometry under the duck;
- changes between the geometry preview and final export;
- silhouette and face/detail changes after remeshing.

A mesh with no open boundary edges can still have tunnels, self-intersections, shading defects or poor shape. Do not equate a clean edge count with a perfect printable solid.

## Quick Stop test

You do not need to reproduce the device crash. Start one ordinary Standard run, wait until a task ID has been received, then press **Stop generation** once.

The local job should immediately show Cancelled. It may then show that Tiiny accepted/confirmed the stop, or that remote cancellation is unconfirmed. Wait for the device to finish/confirm or inspect its status before the next generation.

## If Tiiny stops responding again

Keep the JSON from the output folder even if no GLB exists. Also collect, when available:

- TiinyOS version and model/adapter build;
- the incident time;
- server/model logs around that time;
- memory, accelerator and temperature information already exposed by Tiiny's own tools;
- whether only the 3D API failed or the whole device disappeared from the network.

No specific TiinyOS log command is assumed here because this project does not know the device's administrative interface.

## Hunyuan confirmation

The completed H01/H02/H03 tests already validate the observed request recipes and artifact sequence. A full repeat is unnecessary for this patch. If checking the updated client on hardware, one Hunyuan Standard/PBR run plus the Stop test is sufficient to check the changed networking path before more expensive runs.

## 1024 remains experimental

Maximum still means the server-advertised high/quality recipe; it is not relabeled 512. A separate session-only opt-in permits effective TRELLIS shape resolutions above 512, including Custom overrides. No claim is made that enabling it fixes the crash. Native server defaults whose resolution is not published cannot be classified reliably by the client.
