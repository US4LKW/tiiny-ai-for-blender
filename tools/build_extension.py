#!/usr/bin/env python3
"""Build a Blender Extension installer with a unique package ID.

Usage: python tools/build_extension.py [--output /path/to/archive.zip]
The repository ZIP itself is NOT a Blender installer.
"""
import argparse
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "tiiny_ai_for_blender"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    manifest = tomllib.loads((PKG / "blender_manifest.toml").read_text(encoding="utf-8"))
    assert manifest["id"] == "tiiny_ai_for_blender"
    assert manifest["type"] == "add-on"
    assert (PKG / "__init__.py").is_file()
    assert "version" in manifest
    target = args.output or ROOT / "dist" / f'{manifest["id"]}-{manifest["version"]}.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in ("blender_manifest.toml", "__init__.py", "LICENSE"):
            content = ((ROOT if name == "LICENSE" else PKG) / name).read_bytes()
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    with zipfile.ZipFile(target) as check:
        assert check.namelist() == ["blender_manifest.toml", "__init__.py", "LICENSE"]
        assert check.testzip() is None
    print(target)


if __name__ == "__main__":
    main()
