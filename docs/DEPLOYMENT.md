# Deployment — building the Windows installer

This page builds the **desktop app's installer**. Deploying the online service and the website is in
[PRODUCTION.md](PRODUCTION.md); the installer is built *after* the service has its final address, because
the address is built into it.

The installer contains Python, all libraries and the local AI models (camera detector, summariser,
translator, intent classifier). The target PC needs nothing installed beforehand; it needs the internet
only to reach the company's online account.

```
source + models/ ──► PyInstaller (onedir) ──► dist/OfficeAssistant/ ──► Inno Setup ──► dist/installer/
                     packaging/OfficeAssistant.spec                    packaging/installer.iss
                                                                       OfficeAssistant-Setup.exe + *.bin
```

## Why this design

| decision | reason |
|---|---|
| PyInstaller **onedir** (not onefile) | the bundle is several GB (torch + models); onefile would unpack it to `%TEMP%` on every start |
| One program (`OfficeAssistant.exe`) | version 1's admin program edited the local database; in version 2 the data is online and managed in the app and on the website |
| Local models **inside** the installer | summaries, translation and the camera work offline; `HF_HUB_OFFLINE=1` is set in the installed app so they never try the network. The chat language model is online (no Qwen: about 3 GB smaller) |
| Service address built in (`-ApiUrl`) | `build.ps1` writes it to `_internal\server_url.txt`; `cloud/config.py` reads it (`OFFICE_API_URL` still overrides it for testing). No secret is in the app |
| Data in `%LOCALAPPDATA%\OfficeAssistant` | `C:\Program Files` is read-only for normal users; per-user data also survives updates and uninstalls |
| No database shipped | accounts live online; the build fails if any `.db`/`.bak` file reaches the bundle |
| Inno Setup with `DiskSpanning` (parts under 2 GB) | the payload is larger than a single setup file allows, and GitHub releases accept files up to 2 GB |

`app_paths.py` is the single place that knows these locations (bundle folder vs. user-data folder).

## Build machine

* Windows 10/11 x64, Python 3.12, ~40 GB free disk.
* `pip install -r requirements-build.txt --extra-index-url https://download.pytorch.org/whl/cu130`
* Inno Setup 6: `winget install -e --id JRSoftware.InnoSetup`

## One command

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -ApiUrl https://<service>
```

`build.ps1` runs the steps below and stops at the first failure. `-ApiUrl` is required (https; http only for
localhost). Switches: `-SkipTests`, `-SkipModels` (don't download), `-NoInstaller` (stop after PyInstaller).

## The steps

1. **Models** — `python tools/fetch_models.py` downloads into `models/` (idempotent; `--check` only lists):
   `hf/bart-large-cnn/` (summaries), `hf/opus-mt-*` (12 translation pairs), `yolo12n.pt` (camera).
2. **Gate** — `python -m pytest tests/` and `python -m database.db_manager` must pass.
3. **Freeze** — `pyinstaller packaging/OfficeAssistant.spec --noconfirm --clean` → `dist/OfficeAssistant/`.
   Set `OFFICE_BUILD_NO_MODELS=1` for a quick build without models (then run it with
   `OFFICE_MODELS_DIR=<project>\models`).
4. **Service address** — written to `dist\OfficeAssistant\_internal\server_url.txt`.
5. **Frozen self-check** (automatic in `build.ps1`) — `OfficeAssistant.exe --self-check` opens no window; it
   checks the local data folder and runs the intent classifier, camera detector, summariser and translator once
   inside the frozen app, writes `SELF-CHECK ok/FAIL` lines to the log and exits with the number of failures.
   Then a manual smoke test: run `dist\OfficeAssistant\OfficeAssistant.exe`, sign in, start a session.
6. **Installer** — `iscc packaging\installer.iss` → `dist\installer\OfficeAssistant-Setup.exe` + `-1.bin`, `-2.bin`, …
7. **Clean-PC test** — install in Windows Sandbox or a VM, run the manual checklist in
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
- [ ] desktop, service and website tests pass (CI green)
- [ ] the service is deployed and `/health/ready` answers; the build used its https address (`-ApiUrl`)
- [ ] Frozen app smoke test: sign in, session, AI Helper offline
- [ ] Installer installs, runs and uninstalls on a clean PC
- [ ] `data/` and `*.bak` are **not** in `dist/` (search the folder for `.db`)
- [ ] Release notes mention: SmartScreen warning (unsigned), download all `.bin` files into one folder
- [ ] Git tag `v<version>` and a GitHub release with every file of `dist\installer\` attached

## Measured (v1.0.0, CUDA build, with the Qwen model)

| | size | time on the build PC |
|---|---|---|
| `models/` | 7.9 GB | download once |
| `dist/OfficeAssistant/` (installed size) | 12.2 GB | PyInstaller ~10 min |
| `dist/installer/` | 7.4 GB = `Setup.exe` 3 MB + 4 × ~1.9 GB `.bin` | Inno Setup LZMA2/ultra64 ~50 min |
| frozen self-check | 5/5 ok | ~20 s |

Version 2 has no Qwen model (−3.1 GB of weights); its sizes are in the v2.0.0 release notes.
For faster test builds, set `Compression=lzma2/fast` in `installer.iss` (larger files, minutes instead of an hour).

## Distributing

Attach every file of `dist\installer\` to the GitHub release (the website's *Download* section links to the
latest release), or copy the folder (USB drive, network share). Code-signing the
installer (an Authenticode certificate + `signtool`) would remove the SmartScreen warning; it is optional
for a university deployment.

## Known limits

* Size: the CUDA build of torch alone is ~2.5 GB. A CPU-only build (install the CPU torch wheel before
  running PyInstaller) is ~2 GB smaller; summaries and translations then always run on the CPU.
* Windows only (window tracking uses `pywin32`).
* YOLO (ultralytics) is AGPL-3.0 — fine for this non-commercial university project; see
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) before any commercial distribution.
