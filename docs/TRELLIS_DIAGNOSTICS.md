# TRELLIS.2 diagnostics

This document distinguishes client behavior that can be checked locally from geometry quality that must be checked on a Tiiny device.

## What the client controls

For a textured result, the ordinary request chain is `shape`, `texture`, then `export`. An optional `simplify` stage can be inserted after `shape`. Despite the stage name, the Tiiny TRELLIS schema exposes remeshing and geometry-projection controls there as well as mesh decimation.

The shape artifact is passed to texture generation. When geometry processing runs, its geometry artifact is supplied to export together with the shape and material artifacts. The final GLB bytes are saved and handed to Blender's glTF importer; the add-on does not apply a hidden Blender smoothing or repair modifier.

## Why the earlier comparison was ambiguous

The v0.2.7 Remesh 256 and Remesh 512 options both set `simplify=true` and one closing iteration. They therefore changed geometry processing while also leaving the server's decimation budget and geometry-projection defaults involved. A smoother or lumpier result cannot be attributed to remesh resolution alone from those settings.

The eight supplied experiment reports used `seed=-1`, meaning that the client omitted an explicit seed. The reports did not record the effective seed chosen by the device. This does not prove that every run used a different seed; it means that identical stochastic input was not established by those reports.

## The new candidate

The experimental **Preserve detail 512** profile requests, with Target polygons set to zero:

```json
{
  "remesh_resolution": 512,
  "remesh_closing_iterations": 1,
  "simplify": false,
  "project_geometry": false
}
```

The values are sent only if supported by the fresh device capability schema. This requests a 512-resolution remesh with target decimation and geometry-stage projection disabled. An explicit polygon budget enables decimation; manual overrides can also replace these values. In the controlled duck test, simplify-stage metadata confirmed those settings, but final export reported project_geometry=true. The export schema did not expose a switch for that behavior. The profile therefore does not guarantee that projection remains disabled throughout the pipeline or that visible surface rings disappear.

The profile is opt-in. Legacy profiles remain available to reproduce earlier experiments. Higher-resolution generation and geometry remeshing remain separate decisions.

## One useful comparison

The newer [three-run follow-up](NEXT_TESTS.md) separates shape, remeshing and textured export. Use that procedure for the next diagnostic batch. The comparison below remains useful background.

Use one input and change only the geometry profile:

1. Select the same prepared reference image and keep its crop, scale, and background settings unchanged.
2. Select **Standard**, set **Seed = 42**, keep **PBR** enabled, and leave **Target polygons = 0**. Disable manual overrides. Enable **Save intermediate meshes** in Advanced so the same run also saves the available shape/geometry previews.
3. Generate with geometry processing **Off**. Keep the GLB and its JSON report.
4. Generate once with **Preserve detail 512**. Keep the second GLB and report.
5. Compare both in **Solid** view first, using the same angle and zoom. Check the face, hair, thin edges, cracks, and surface smoothness. Then compare **Material Preview**. The optional meshes in `diagnostics/<result-name>/` distinguish defects in the shape preview, geometry preview, and final export within a single run.

A matching explicit seed improves the comparison but is not a promise of deterministic results across different firmware, model builds, or execution backends. Check the image hash and actual per-stage request records in both reports. If the client requested the same shape settings but the device returns different effective settings, preserve that evidence.

The original archive's Standard used omitted server defaults. To reproduce that request style, choose **Custom > Server defaults**, leave every override disabled, and choose a legacy surface mode. Do not directly attribute a difference between old Standard and new Standard to the surface profile alone.

There is no need to sweep dozens of Custom values before reporting the outcome. This one comparison tests the candidate's intended difference. If it worsens the result, return to Off; the original workflow is retained.

## Reading the symptoms

| Observation | What it suggests | What it does not establish |
| --- | --- | --- |
| Open boundaries in the saved GLB after welding identical vertex positions | Actual mesh discontinuities are present in that artifact. | The exact algorithm or stage that caused them. |
| Cracks visible only with materials enabled | Inspect texture alpha, normals, and material settings as well as geometry. | That the shape network itself failed. |
| Fewer holes but a lumpier silhouette after remesh | Geometry processing changed the surface and may trade detail for closure. | That a higher remesh resolution will always improve it. |
| A distorted face in an otherwise coherent model | The reconstruction lacks faithful local shape or appearance. | That Target Faces is a human-face detector or can fix likeness. |
| A long pause during export | The device is busy or not answering a poll. | That the task has stopped or failed. |

Texture seams split vertices in many valid GLB files. Raw boundary counts can therefore overstate holes. Diagnostic tools should compare position-welded topology and should not present every UV seam as damaged geometry.

## Reports and reproducibility

Development build dev-0.3.9 writes reports before generation and during polling, including failures and local/remote cancellation outcomes. See [Network and cancellation](NETWORK_AND_CANCELLATION.md). Effective shape resolutions above 512 require the experimental opt-in; do not repeat the failed Maximum run before investigating the device logs.

A useful report includes the add-on version, Blender version, TiinyOS/model build, selected model, current capability schema, two generation reports, and a clear statement of whether a defect is visible in Solid mode.

For public issues, use an image and model that you are comfortable sharing. Remove API keys and private local paths. Device capability fixtures supplied with this repository contain settings rather than user image data. The project package does not include the supplied portrait or the user's experimental models.

The native model repository is a reference for model design and native implementation details. The Tiiny capability schema is the evidence for which client parameters the current device accepts. Neither source alone proves the behavior of an unpublished Tiiny adapter.

## Reference projects

- [Microsoft TRELLIS.2 source](https://github.com/microsoft/TRELLIS.2)
- [TRELLIS.2 model card](https://huggingface.co/microsoft/TRELLIS.2-4B)
- [Tencent Hunyuan3D-2.1 source](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1)
