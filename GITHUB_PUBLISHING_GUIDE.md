# Publishing Tiiny AI for Blender on GitHub

Target repository: **https://github.com/US4LKW/tiiny-ai-for-blender**

This repository bundle already contains the installer, source code, Markdown documentation, and illustration files. **Do not upload the repository ZIP itself as a single file instead of its extracted contents.**

## 1. Create an empty repository

On GitHub, create a **Public** repository with:

- **Repository name:** `tiiny-ai-for-blender`
- **Description:** `Blender extension for local Image-to-3D with Tiiny AI Pocket Lab, Hunyuan3D, TRELLIS.2, PBR textures and automatic image preparation.`
- Do not ask GitHub to create another README, `.gitignore`, or LICENSE: these are already in this project.
- Choose the **main** branch as the default.

Suggested topics: `blender`, `blender-extension`, `image-to-3d`, `tiiny-ai`, `hunyuan3d`, `trellis`, `local-ai`, `3d-generation`.

## 2. Upload the repository contents

### With Git (recommended, preserves hidden files)

Unzip the **full GitHub project archive** into a folder. Open a terminal **inside that folder**, where `README.md` and `tiiny_ai_for_blender/` are visible:

```bash
git init
git branch -M main
git add .
git commit -m "Initial community preview v0.1.0"
git remote add origin https://github.com/US4LKW/tiiny-ai-for-blender.git
git push -u origin main
```

Authenticate with your own GitHub credentials when requested. If you already created an initialized repository, compare and reconcile its content instead of blindly overwriting the history.

### With the GitHub website

You can also use **Add file → Upload files** in the empty repository. Upload the **contents of the extracted project folder**, including its subdirectories. Keep the `docs/images/`, `tiiny_ai_for_blender/`, `releases/`, `tests/`, `tools/`, and hidden `.github/` directory structure intact. For many files, the Git workflow is more reliable.

**Verify after upload:** The homepage must display `README.md` with the `Layout.png` image. Open `docs/USER_GUIDE.md` and confirm every screenshot is visible. Click the installation ZIP link in the README and make sure the file exists in `releases/`.

## 3. Publish v0.1.0 as a pre-release

1. Open **Releases → Draft a new release**.
2. Create tag **`v0.1.0`**, targeting **`main`**.
3. Use release title: **`Tiiny AI for Blender v0.1.0 — First Community Preview`**.
4. Open `RELEASE_NOTES_v0.1.0.md`, copy its entire Markdown content into the release description, and check the Preview tab for images and links.
5. In the **Assets** uploader, attach the exact file **`releases/tiiny_ai_for_blender-0.1.0.zip`**. Do **not** attach the full repository archive as the extension installer.
6. Mark the release **Pre-release** for this early community version.
7. Publish the release.

GitHub automatically adds downloadable source-code archives to tagged releases. Those automatic archives are **source snapshots**, not installable Blender extensions. The separately attached installer ZIP is what Blender users should download.

The release notes use full image URLs from `main`; publish the repository files before publishing the release. If you later rename the repository or change the default branch, update those absolute URLs.

## 4. Files you should not upload

Do not publish your **Tiiny API key**, device credentials, private Blender preferences, local setup logs containing sensitive paths, generated test reports with private information, or any images without appropriate permissions.

## 5. Version policy

- **Public initial release tag:** `v0.1.0`.
- The extension manifest and installer name both use `0.1.0`.
- Internal development archive numbers are **not** GitHub release versions.
- **After publishing tag `v0.1.0`, change the public version** for subsequent releases (for example `0.1.1`). Avoid replacing a public release's code without changing its version.

See [LICENSE](LICENSE), [Third-Party Notices](docs/THIRD_PARTY_NOTICES.md), and [Image Rights](docs/IMAGE_RIGHTS.md).
