# Third-party notices

## Original Blender MCP project

This add-on originated from an adaptation of the Blender MCP project by Siddharth Ahuja. The original project is distributed under the MIT License, with the notice:

> Copyright (c) 2025 Siddharth Ahuja

The full original notice is retained without removal in `../LICENSE_ORIGINAL_MCP.txt` and in `../LICENSE`. Attribution to the original project does not imply that its author maintains or endorses this Tiiny adaptation.

## External runtime components and models

The following projects are used externally or referenced by the workflow. Their code and model weights are not redistributed in this source package:

- [Blender](https://www.blender.org/) provides the host application and glTF importer.
- [uv](https://github.com/astral-sh/uv) manages the optional image-preparation environment.
- [Pillow](https://github.com/python-pillow/Pillow) handles image preparation in that environment.
- [rembg](https://github.com/danielgatis/rembg) provides optional background removal and downloads separately licensed segmentation models.
- [Microsoft TRELLIS.2](https://github.com/microsoft/TRELLIS.2) and its model weights run through the Tiiny device's model integration.
- [Tencent Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) and its model weights run through the Tiiny device's model integration.

Their own license notices and terms apply to their respective components and weights. The MIT notice in this repository does not relicense third-party models, Blender, Tiiny software, or user-provided images and meshes.

Tiiny, Blender, TRELLIS, and Hunyuan names identify compatible software and models. This repository is an independent client project.
