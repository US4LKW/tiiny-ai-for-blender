# Device test findings: 2026-11-20

This note records the request audit of six completed Tiiny image-to-3D runs supplied by the project owner: H01-H03 and T01-T03. T04 was reported to stall during TRELLIS Maximum generation, followed by loss of device network responsiveness, but no T04 generation report is included in the supplied results.

The note distinguishes saved request/response evidence from hypotheses about the device implementation. Mesh-topology measurements and visual comparisons are separate evidence; this document does not infer watertightness or facial likeness from the number of triangles.

## Completed runs

All six generation reports have `status=saved` and `addon_version=0.1.0`. In this report format, `saved` means the server artifact was downloaded and written to a GLB; it does not certify the subsequent Blender import or the quality of the geometry.

| Test | Model and preset | Surface profile | Triangles recorded in final GLB | Sum of reported stage durations |
| --- | --- | --- | ---: | ---: |
| H01 | Hunyuan Standard | Off | 531,732 | 746.8 s |
| H02 | Hunyuan Draft | Off | 229,628 | 396.1 s |
| H03 | Hunyuan Maximum | Off | 955,888 | 1,372.2 s |
| T01 | TRELLIS Draft | Off | 1,818,126 | 324.7 s |
| T02 | TRELLIS Standard | Off | 2,513,190 | 476.1 s |
| T03 | TRELLIS Standard | Preserve detail 512 | 2,159,682 | 562.5 s |

Stage durations include client task submission, polling, and the artifact work measured by the client. They are not pure accelerator inference benchmarks. A larger triangle count does not establish a better reconstruction.

Every completed run used explicit **Seed 42**, **Target polygons 0**, and **PBR enabled**, with **no manual overrides**. All six reports contain the same original-source hash. H01-H03 share one prepared-input hash and report a 512-by-512 canvas; T01-T03 share another prepared-input hash and report a 1024-by-1024 canvas. The prepared images differ between models, while the recorded source bytes agree.

All six reports have `stage_previews_requested=false`. The archive therefore does not contain the intermediate shape and processed-geometry copies needed to isolate where a visible defect first appeared.

## Request audit

For every completed run, the saved `params_by_stage` and stage plan exactly match the current client's execution-plan output when reconstructed from the saved settings and capabilities. The capability objects embedded in the reports also match the repository's corresponding capability fixtures.

### TRELLIS quality routing

| Test | Shape request | Texture request | Export request |
| --- | --- | --- | --- |
| T01 | `output_precision=draft`, `inference_quality=fast`, `seed=42` | `inference_quality=fast`, `seed=42` | `asset_quality=fast` |
| T02 | `output_precision=standard`, `inference_quality=balance`, `seed=42` | `inference_quality=balance`, `seed=42` | `asset_quality=balance` |
| T03 | Same as T02 | Same as T02 | Same as T02, with an additional geometry-artifact input |

T01's server metadata reports `pipeline_type=512` and effective `output_precision=standard` after the client requested `draft`. This agrees with the capability mapping, where both Draft and Standard select a 512 pipeline. It is not evidence that the Draft request was lost: the server also reports the requested `fast` inference tier.

T02 and T03 report a 512 pipeline, Standard precision, and Balanced inference. Their shape and texture settings agree. Matching seed and input strengthen the comparison but do not prove bit-identical intermediate shape output, because those intermediate artifacts were not saved for analysis.

The client does not add undocumented native sampler parameters, an 8192-pixel texture request, or a hidden polygon budget to these presets.

### Hunyuan routing

H01 Standard sends the explicit seed while leaving quality controls to server defaults. H02 Draft sends the advertised `draft/fast/fast` quality controls; H03 Maximum sends `high/quality/quality`. The current Hunyuan response lacks detailed stage-control schemas, so the established client path carries these global controls in each stage's parameter object.

The device completed all three Hunyuan runs. Its shape metadata confirms the requested Draft and Maximum precision/inference values. Export metadata reports texture sizes of 2048 for H01, 1024 for H02, and 2048 for H03. These are server-reported values, not arbitrary numeric texture limits chosen by the client.

No TRELLIS remesh or projection fields occur in the Hunyuan requests. These results give no reason to change the working Hunyuan preset recipes as part of TRELLIS troubleshooting.

## T03: geometry projection is stage-specific

T03 inserts a geometry-processing stage with this request:

```json
{
  "asset_quality": "balance",
  "simplify": false,
  "remesh_resolution": 512,
  "remesh_closing_iterations": 1,
  "project_geometry": false
}
```

The geometry stage's returned metadata repeats `simplify=false`, `target_faces=null`, `remesh_resolution=512`, one closing iteration, and `project_geometry=false`. This confirms that the device reported the requested geometry-stage settings. It does not reveal the internal geometry algorithm.

The client then correctly sends all three required/relevant references to export:

- The original shape artifact from the shape task.
- The processed geometry artifact from the geometry task.
- The material artifact from the texture task.

The texture task consumes the original shape artifact, as required by the device's advertised texture-stage inputs. It is not a client routing error to keep that shape reference for texture sampling.

**The export stage's metadata reports `project_geometry=true` for T03**, even though the geometry stage reports `false`. T01 and T02 export metadata report `project_geometry=false`. All three report `bake_projection=texel`; T01 reports a 1024 texture size and T02/T03 report 2048.

This is a material limitation of the existing description of Preserve detail 512: the profile disables the advertised geometry-stage projection parameter, but the evidence does not show that projection remains disabled throughout export. The export stage may make an additional internal decision when it receives a processed geometry artifact. That is a hypothesis, not an established explanation of the surface defects.

The supplied export schema exposes `bake_projection`, `output_name`, and `texture_size`, plus the `asset_quality` control. It does **not** expose an export-stage `project_geometry` parameter. The client should not invent that parameter or assume that a baking-mode switch repairs geometry.

Useful information for a Tiiny adapter issue would be the distinction between the two reported projection values, the exact geometry and export request objects, and intermediate meshes from a single run. Task identifiers can link the report to device-side logs when shared directly with the device maintainers.

## T04: what is and is not established

The reported failure is a TRELLIS Maximum run with surface processing Off. The user observed stalled progress and loss of device network responsiveness. There is no supplied T04 manifest, returned effective-settings record, or device crash log.

Under the current preset recipe, and without overrides, Maximum requests `output_precision=high` and `inference_quality=quality` for shape generation. The capability schema maps High to the 1024 pipeline. This is an advertised combination, but schema acceptance does not prove that the device can complete it reliably for every input.

The available evidence does not distinguish memory exhaustion, a runtime or driver failure, a long computation, network-service failure, or another device-side problem. It does not establish that the client submitted malformed parameters. It also does not prove that the expected unmodified request was actually submitted in T04, because that run's report is missing.

Keep Maximum's 1024 meaning explicit. A separate opt-in for experimental TRELLIS 1024 generation can prevent accidental repetition while retaining the advertised feature. Silently relabeling a 512 run as Maximum 1024 would make subsequent comparisons misleading. Hunyuan Maximum should remain independent of a TRELLIS-specific restriction.

## Confirmed client robustness fix

The audit found a separate capability-validation bug: the helper that retrieves a parameter schema preferred the broad model-level quality enum over a detailed stage-specific schema. A hypothetical updated texture schema that no longer accepts `fast` could still receive it from Draft, even if the model-wide list continued to advertise `fast` for shape.

The helper now prefers a nonempty stage-specific schema. Empty or name-only stage entries retain the global fallback. A regression test demonstrated the failure before the change and now verifies rejection before the first task POST. Additional tests preserve valid Standard/Maximum routing and the Hunyuan contract without stage schemas.

The actual archived schemas have matching quality choices, so this bug is **not an established cause of T04**. It is a confirmed client validation defect found during the review.

## Next test: isolate shape, geometry processing, and export

Use the same selected source and prepared-image settings for all three runs. Set **TRELLIS Standard**, **Seed 42**, **Target polygons 0**, **manual overrides disabled**, and **Save intermediate meshes enabled**. Keep experimental 1024 generation disabled for this comparison.

| Run | Surface profile | PBR | Expected stages | Main comparison |
| --- | --- | --- | --- | --- |
| A | Off | Disabled | Shape | Inspect the shape preview directly. |
| B | Preserve detail 512 | Disabled | Shape, geometry | Compare this run's saved shape preview with its processed geometry preview. |
| C | Preserve detail 512 | Enabled | Shape, geometry, texture, export | Compare this run's shape preview, geometry preview, and final GLB. |

Inspect geometry first in Blender **Solid** view with matching camera angle and scale; then inspect Run C in Material Preview. Do not use the texture appearance alone to decide whether a gap exists in the mesh.

Keep each final GLB, its JSON report, and the corresponding `diagnostics/<result-name>/` folder. The saved previews provide comparisons within one generation chain, which is stronger evidence than assuming separate shape runs were identical. Compare the recorded input hashes and exact requests before attributing a difference to a setting.

If a run stops, preserve its partial JSON report and note the last visible stage and whether the Tiiny device remains reachable. A local cancellation or a stopped polling loop is not proof that the device confirmed cancellation of its task.

These three runs are intended to locate the stage where defects appear. They are not a promise that the current remesh profile solves the problem, and they do not require a broad sweep of undocumented parameters.
