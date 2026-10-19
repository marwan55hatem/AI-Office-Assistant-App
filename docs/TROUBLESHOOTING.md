# Troubleshooting

First look at the log: `%LOCALAPPDATA%\OfficeAssistant\logs\app.log` (installed) or `data\logs\app.log` (from source).

To test all AI models at once, run `"C:\Program Files\Office Assistant\OfficeAssistant.exe" --self-check`
(no window opens; after ~30 s the log contains one `SELF-CHECK ok` / `FAIL` line per model).

| problem | cause | fix |
|---|---|---|
| Camera preview stays black / "Could not open webcam 0" | another app uses the camera, or camera access is off for desktop apps | close Teams/Zoom/Camera; *Windows Settings → Privacy & security → Camera → Let desktop apps access your camera*. The session still works without a camera (screen + keyboard only). |
| Every second counts as "away" | no person detected (camera covered / pointing away) or keyboard idle | check the *Person* indicator; move the camera |
| AI Chat badge: *slow mode · CPU* | no NVIDIA GPU, an old driver, or less than 3.8 GB of free graphics memory (the camera model and other apps use some) | update the NVIDIA driver (525+); close other GPU-heavy apps; or keep CPU mode (works, slower) |
| AI Chat badge: *not installed* | the model folder is missing (from-source run) | `python tools/fetch_models.py` |
| Summarise/translate: "Could not load the model" | from source: models not fetched and no internet | `python tools/fetch_models.py` |
| The app closes immediately on start (from source) | `sentencepiece` imported after PyQt5 on Windows | always start through `main.py` (it pre-imports sentencepiece); do not import PyQt5 first in your own scripts |
| "database is locked" | two copies of the app (or the app and the admin panel) writing at the same moment | close the other copy; SQLite allows one writer at a time |
| Forgot the manager password | — | Admin panel → Users → edit the account and set a new password |
| Want a clean start | — | Admin panel → Danger zone → Factory reset (keeps only the demo accounts), or delete `%LOCALAPPDATA%\OfficeAssistant` while the app is closed |
| Text too small / too large on a 4K screen | automatic zoom | set the environment variable `APP_UI_SCALE` to e.g. `1.25` (or `1` to disable) |
| SmartScreen blocks the installer | the installer is not code-signed | *More info → Run anyway* |
| Installer says a `.bin` file is missing | only `Setup.exe` was copied | copy all `OfficeAssistant-Setup*` files into the same folder |
