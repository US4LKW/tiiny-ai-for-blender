# Contributing

This project is an independent Blender client for the Tiiny image-to-3D API. Contributions are especially useful when they include reproducible device evidence for TRELLIS.2 geometry processing.

## Scope

Keep both supported model workflows available. Preserve the optional PBR path, explicit source-image selection, configurable folders, and per-model capability handling. Generation should remain a direct local Tiiny API workflow.

Use English for filenames, code comments, interface text, documentation, tests, and examples. Do not add Cyrillic text to the distributed package. User-selected file paths are runtime data and may naturally contain Unicode.

## Development setup

`tiiny_ai_for_blender/__init__.py` is the extension entry point. Install the packaged ZIP, not that Python file alone. The offline tests use Python and a small mocked Blender API. Image preparation tests also need Pillow and NumPy (`python -m pip install Pillow numpy`). A real Blender executable is needed for registration, property, import, and interface checks.

Run the isolated test suites from the repository root:

```sh
python tests/run_tests.py
python tests/run_tests.py --blender blender
```

The second command includes a real-Blender smoke test and requires Blender on PATH. It checks registration, property access, model-isolated settings, and save/reload source guards; it does not visually render the interface or contact a Tiiny device.

Alternatively, run individual offline scripts. In PowerShell:

```powershell
Get-ChildItem tests/test_*.py | ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Test failed: $($_.Name)" }
}
```

On a POSIX shell:

```sh
for test_file in tests/test_*.py; do
    python "$test_file" || exit 1
done
```

Offline request simulations do not run either AI model. Describe them as client tests, not end-to-end generation or proof that a mesh-quality problem is fixed.

## Parameter changes

1. Identify the exact model and Tiiny capability schema that supports the field.
2. Separate native-model documentation from the device adapter's accepted names, types, ranges, and defaults.
3. Validate enabled values against fresh capabilities before creating a device task.
4. Preserve disabled overrides and native defaults where no explicit setting is selected.
5. Cover routing, precedence, and rejection behavior with focused tests.
6. Record the exact request in a diagnostic report so a device result can be reproduced.

A schema maximum is a validation limit, not a recommendation for a quality preset. Do not automatically choose the largest texture size, iteration count, or face budget simply because the API allows it.

For geometry changes, report sampling settings separately from remeshing, decimation, projection, and texture baking. Keep a fixed input and explicit seed when comparing a new geometry profile. Avoid changing multiple unrelated variables in one comparison.

## Reporting an issue

Include:

- Add-on version, Blender version, operating system, and TiinyOS/model build if available.
- Exact model selection and the exported capability JSON.
- Steps to reproduce, expected behavior, and observed behavior.
- The generation JSON report and whether the defect is visible in Solid view, Material Preview, or both.
- A public reproduction image or mesh when it is needed to reproduce a geometry issue.

Do not include an API key, private paths, personal portraits, or other private assets unless you intentionally want to publish them. A small public reproduction is usually easier for others to test.

## Pull requests

Explain the concrete problem, the behavior changed, and the checks performed. State whether validation used mocked requests, Blender, a real Tiiny device, or some combination. Preserve the existing license notice and attribution. Do not bundle model weights or downloaded third-party dependencies.

The local source package is ready for review and publication by its owner; generating a release archive does not publish it to GitHub.
