# Deployment — building the offline Windows installer

The app is shipped as **one Windows installer that works without internet**: Python, all libraries and all
AI models are inside it. The target PC needs nothing installed beforehand.

```
source + models/ ──► PyInstaller (onedir) ──► dist/OfficeAssistant/ ──► Inno Setup ──► dist/installer/
                     packaging/OfficeAssistant.spec                    packaging/installer.iss
                                                                       OfficeAssistant-Setup.exe + *.bin
```

## Why this design

| decision | reason |
|---|---|
| PyInstaller **onedir** (not onefile) | the bundle is several GB (torch + models); onefile would unpack it to `%TEMP%` on every start |
| Two programs in one bundle (`OfficeAssistant.exe`, `OfficeAssistant-Admin.exe`) | they share torch/Qt, so the libraries are stored once |
| Models **inside** the installer | the requirement is fully offline; `HF_HUB_OFFLINE=1` is set in the installed app so nothing ever tries the network |
| Data in `%LOCALAPPDATA%\OfficeAssistant` | `C:\Program Files` is read-only for normal users; per-user data also survives updates and uninstalls |
| No database shipped | the first start creates the schema and the demo accounts (`seed_demo_users`); the developer's `data/` folder (real passwords) is never packaged |
| Inno Setup with `DiskSpanning` | the payload is larger than 4 GB, the limit of a single setup file |

`app_paths.py` is the single place that knows these locations (bundle folder vs. user-data folder).

## Build machine

* Windows 10/11 x64, Python 3.12, ~40 GB free disk.
* `pip install -r requirements-build.txt --extra-index-url https://download.pytorch.org/whl/cu124`
* Inno Setup 6: `winget install -e --id JRSoftware.InnoSetup`

## One command

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

`build.ps1` runs the steps below and stops at the first failure. Switches: `-SkipTests`, `-SkipModels`
(don't download), `-NoInstaller` (stop after PyInstaller).

## The steps

1. **Models** — `python tools/fetch_models.py` downloads into `models/` (idempotent; `--check` only lists):
   `qwen2.5-1.5b-instruct/` (chat), `hf/bart-large-cnn/` (summaries), `hf/opus-mt-*` (12 translation pairs),
   `yolo12n.pt` (camera).
2. **Gate** — `python -m pytest tests/` and `python database/db_manager.py` must pass.
3. **Freeze** — `pyinstaller packaging/OfficeAssistant.spec --noconfirm --clean` → `dist/OfficeAssistant/`.
   Set `OFFICE_BUILD_NO_MODELS=1` for a quick build without models (then run it with
   `OFFICE_MODELS_DIR=<project>\models`).
4. **Frozen self-check** (automatic in `build.ps1`) — `OfficeAssistant.exe --self-check` opens no window; it
   creates the database and runs the camera detector, summariser, translator and chat model once inside the
   frozen app, writes `SELF-CHECK ok/FAIL` lines to the log and exits with the number of failures.
   Then a manual smoke test: run `dist\OfficeAssistant\OfficeAssistant.exe`, log in, start a session.
5. **Installer** — `iscc packaging\installer.iss` → `dist\installer\OfficeAssistant-Setup.exe` + `-1.bin`, `-2.bin`, …
6. **Clean-PC test** — install in Windows Sandbox or a VM *without network*, run the manual checklist in
   [TESTING.md](TESTING.md), uninstall.

## Packaging pitfalls (already handled in the spec)

| symptom | cause | fix in `OfficeAssistant.spec` |
|---|---|---|
| PyInstaller: *Isolated subprocess crashed while importing package 'sentencepiece'* | PyInstaller imports every package in one process with Qt first; sentencepiece crashes after PyQt5 on Windows | sentencepiece is left out of that DLL-path scan (it is still bundled) |
| same crash for `transformers.pipelines` | pipelines imports sentencepiece | `transformers.pipelines` is excluded (the app never uses it) |
| frozen app exits silently, Event Viewer: crash in `PyQt5\Qt5\bin\MSVCP140.dll` 14.26 | PyQt5 ships an old MSVC runtime; torch needs a newer one | `newer_vc_runtime()` swaps in the build machine's current `msvcp140*/vcruntime140*` |

## Release checklist

- [ ] Version number updated in `packaging/installer.iss` (`MyAppVersion`) and `CHANGELOG.md`
- [ ] `fetch_models.py --check` shows every model *ok*
- [ ] pytest and the database self-test pass
- [ ] Frozen app smoke test passes offline
- [ ] Installer installs, runs and uninstalls on a clean PC
- [ ] `data/` and `*.bak` are **not** in `dist/` (search the folder for `.db`)
- [ ] Release notes mention: change the demo passwords, SmartScreen warning (unsigned), copy all `.bin` files

## Measured (v1.0.0, CUDA build)

| | size | time on the build PC |
|---|---|---|
| `models/` | 7.9 GB | download once |
| `dist/OfficeAssistant/` (installed size) | 12.2 GB | PyInstaller ~10 min |
| `dist/installer/` | 7.4 GB = `Setup.exe` 3 MB + 4 × ~1.9 GB `.bin` | Inno Setup LZMA2/ultra64 ~50 min |
| frozen self-check | 5/5 ok | ~20 s |

For faster test builds, set `Compression=lzma2/fast` in `installer.iss` (larger files, minutes instead of an hour).

## Distributing

Copy the whole `dist\installer\` folder (USB drive, network share or a zip per part). Code-signing the
installer (an Authenticode certificate + `signtool`) would remove the SmartScreen warning; it is optional
for a university deployment.

## Known limits

* Size: the CUDA build of torch alone is ~2.5 GB. A CPU-only build (install the CPU torch wheel before
  running PyInstaller) is ~2 GB smaller but the chat model then always runs in slow mode.
* Windows only (window tracking uses `pywin32`).
* YOLO (ultralytics) is AGPL-3.0 — fine for this non-commercial university project; see
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) before any commercial distribution.
