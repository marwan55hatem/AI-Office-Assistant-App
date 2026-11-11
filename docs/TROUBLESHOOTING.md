# Troubleshooting

First look at the log: `%LOCALAPPDATA%\OfficeAssistant\logs\app.log` (installed) or `data\logs\app.log` (from source).

To test the local AI models at once, run `"C:\Program Files\Office Assistant\OfficeAssistant.exe" --self-check`
(no window opens; after ~30 s the log contains one `SELF-CHECK ok` / `FAIL` line per check).

| problem | cause | fix |
|---|---|---|
| Banner "You are offline…" | no internet, or the service is not reachable | check the connection; a running session keeps counting and is sent later. On free hosting the service may need ~1 minute to wake up after a quiet period |
| "Waiting for approval" at sign-in | the manager has not approved the account yet | ask your manager (website → *Employees*) |
| Forgot the password | — | website → *Sign in* → *Forgot password*; the link is valid for 30 minutes |
| Signed out unexpectedly | the session expired, the account was disabled, or a stolen sign-in token was detected (all sessions end) | sign in again; ask the manager if the account is disabled |
| No e-mails arrive | spam folder; the person switched them off (Settings → Notifications); the service has no e-mail provider configured | check those; the operator checks the service log |
| Camera preview stays black / "Could not open webcam 0" | another app uses the camera, or camera access is off for desktop apps | close Teams/Zoom/Camera; *Windows Settings → Privacy & security → Camera → Let desktop apps access your camera*. The session still works without a camera (screen + keyboard only). |
| Every second counts as "away" | no person detected (camera covered / pointing away) or keyboard idle | check the *Person* indicator; move the camera |
| AI Chat answers with a ⚠ note instead of a general answer | offline, the company's daily AI budget is used up, or the service has no model key | try later; the chat still answers questions about your tasks and calendar |
| Summarise/translate: "Could not load the model" | from source: models not fetched | `python tools/fetch_models.py` |
| The app closes immediately on start (from source) | `sentencepiece` imported after PyQt5 on Windows | always start through `main.py` (it pre-imports sentencepiece); do not import PyQt5 first in your own scripts |
| Text too small / too large on a 4K screen | automatic zoom | set the environment variable `APP_UI_SCALE` to e.g. `1.25` (or `1` to disable) |
| SmartScreen blocks the installer | the installer is not code-signed | *More info → Run anyway* |
| Installer says a `.bin` file is missing | only `Setup.exe` was downloaded | download all `OfficeAssistant-Setup*` files into the same folder |
| Website: "Too many attempts" | rate limit on sign-in / reset | wait a few minutes |
