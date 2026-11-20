# Parameters and precedence

This guide describes the capability fixtures supplied with the add-on. The current response from the selected Tiiny device always takes precedence. A field accepted by the API is not proof that its native model implementation is identical to an upstream project.

## How settings combine

1. Select a generation preset. Custom has its own selectable base.
2. Choose the independent TRELLIS surface profile, if applicable.
3. A nonzero Target polygons value requests an explicit decimation budget.
4. When manual overrides are enabled, checked global and stage values replace inherited values. Boolean Inherit keeps the inherited value.
5. The add-on fetches capabilities again and validates the complete stage plan before submitting the first task. Removed explicit controls, changed bounds, unsupported enum values, and contradictory settings stop the job with an explanation.

Manual settings are stored per model. Switching to Custom from Draft, Standard, or Maximum retains that preset as the Custom base. Choosing Server defaults omits the preset's quality values. In the other modes, manual settings have no effect unless Enable manual overrides is selected.

## TRELLIS.2

### Global quality controls

| Control | Advertised choices | Where used |
| --- | --- | --- |
| Geometry precision (`output_precision`) | `draft`, `standard`, `high` | Shape. The supplied capabilities map the first two to pipeline 512 and high to 1024. |
| Inference quality (`inference_quality`) | `fast`, `balance`, `quality` | Shape and texture sampling, filtered by each stage's controls. |
| Asset processing quality (`asset_quality`) | `fast`, `balance`, `quality` | Geometry processing and export. Internal budgets and algorithms are not exposed by these names. |
| Seed | Explicit integer, or -1 in the UI to omit it | Shape and texture when advertised. -1 is not a promise of randomization or of a fixed server seed. |

Standard explicitly requests standard/balance/balance. Draft requests draft/fast/fast. Maximum requests high/quality/quality. The server's supported choices are checked; no undocumented native sampling parameters are added.

As of development build dev-0.3.9, effective TRELLIS shape resolutions above 512 require **Allow experimental 1024** for the current session. The check uses the final shape parameters after Custom/manual precedence; it does not silently change the Maximum recipe. Unknown server-default resolution remains unknown. Hunyuan is unaffected. Detailed stage schemas take precedence over a broader top-level quality enum.

### Stage controls

| Stage | Parameter | Published schema | Meaning and limits |
| --- | --- | --- | --- |
| Shape | `pipeline_type` | `512` or `1024`, nullable | Explicit Tiiny pipeline choice. It replaces an inherited geometry-precision alias. Conflicting explicit precision and pipeline overrides are rejected. Native cascade names are not sent. |
| Geometry | `simplify` | Boolean, default true | Whether to run mesh decimation, according to the server description. It is separate from selecting the geometry stage. |
| Geometry | `target_faces` | Integer 4-2,000,000, nullable | Mesh face/triangle budget. UI name: Target polygons. Zero is a client sentinel to omit it; zero is never sent as an explicit budget. It does not detect human faces. |
| Geometry | `remesh_resolution` | Integer 0-512, nullable | Device remesh-resolution control. A nullable default is unknown, not zero. Although zero is accepted by this schema, its exact backend behavior is not established here. |
| Geometry | `remesh_closing_iterations` | Integer 0-8, nullable | Device closing-iteration control. The client does not infer the server's internal morphology algorithm. |
| Geometry | `project_geometry` | Boolean, nullable | Controls projection in the geometry stage. Tiiny may independently enable projection during final export, as observed in T03. Its relationship to Microsoft's floating-point projection factor is unverified. |
| Export | `texture_size` | Integer 256-8192, nullable | Requested texture-map dimensions. An upper bound is not a recommended preset; large maps may cost substantial memory and time. |
| Export | `bake_projection` | `vertex_fallback` or `texel`, nullable | Advertised baking mode. Neither option is presented as a guaranteed mesh repair. |

The server also advertises a texture seed and texture inference tier; the shared controls supply these. The output filename is managed by the add-on rather than exposed as an override. Artifact identifiers are passed between stages automatically.

For a textured model with a geometry stage, export receives the shape, processed geometry, and material artifacts. The material sampler still consumes the shape artifact, as required by the device schema. Geometry processing is therefore applied before final texture baking/export.

### Surface profiles

| Profile | Decimation request | Remesh request | Projection request |
| --- | --- | --- | --- |
| Off (original) | No geometry stage unless a budget/override enables it | No explicit value | No explicit value |
| Preserve detail 512 (experimental) | False when budget is zero; true for an explicit budget | Resolution 512, closing iterations 1 | False |
| Tiiny cleanup (legacy) | True, server budget unless explicitly set | Server defaults | Server defaults |
| Remesh 256 + decimate (legacy) | True | Resolution 256, closing iterations 1 | Server defaults |
| Remesh 512 + decimate (legacy) | True | Resolution 512, closing iterations 1 | Server defaults |

The experimental profile requests different processing; it has not been validated for better geometry on Tiiny hardware. Manual overrides can change these values. The effective request display and JSON report show the final combination.

## Hunyuan3D 2.1

The supplied device response exposes the same three inference/asset tiers and these geometry-precision mappings:

| Tiiny precision | Advertised octree resolution |
| --- | ---: |
| draft | 192 |
| standard | 288 |
| high | 384 |

Hunyuan Standard retains server defaults. Draft and Maximum use the advertised low/high tiers. TRELLIS-specific surface parameters are never added to Hunyuan requests.

This response lists additional parameter names but does not include detailed stage schemas. The add-on provides opt-in numeric controls for `shape.step`, `shape.guidance_scale`, `texture.paint_step`, and `texture.guidance_scale` only while those exact names are advertised. Their UI reference values come from upstream Tencent documentation/code and are labeled experimental; they are not verified Tiiny defaults or complete device bounds. Other untyped fields are not turned into arbitrary text boxes.

## Image preparation controls

Canvas size, background removal, cropping, coverage, and interpolation operate on the input PNG in the separate preparation environment. They are not native TRELLIS sampler parameters. A 1024-pixel PNG does not imply 1024-resolution shape generation. Remeshing resolution and texture resolution are separate again.

The add-on preserves the selected source, creates prepared files in the chosen output folder, and records input hashes for comparison. No face-specific detector or facial-identity reconstruction module is enabled by these controls.

## Evidence

The two files under `fixtures/` are real capability exports used for offline regression tests. They describe a specific observed device API, not every TiinyOS version. Native model references are [Microsoft TRELLIS.2](https://github.com/microsoft/TRELLIS.2) and [Tencent Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1). Always keep API support, client requests, and observed server output distinct when reporting a result.
