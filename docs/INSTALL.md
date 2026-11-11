# Installing the Desktop AI Office Assistant

Version 2: the app signs in to your company's online account. Summaries, translation and the camera
model run on the PC; reports, tasks, meetings, messages and the AI Chat's general answers need the
internet.

## Requirements

| | minimum | recommended |
|---|---|---|
| Windows | 10 or 11, 64-bit | 11 |
| Disk space | about 9 GB for the program (+ the installer files while installing) | SSD |
| Memory | 8 GB | 16 GB |
| Camera | any webcam (optional — without one the session uses screen + keyboard only) | |
| Graphics | none (summaries and translations then run on the CPU, slower) | NVIDIA GPU, recent driver |
| Internet | needed for sign-in, reports, tasks, meetings, messages and the AI Chat | |

## Install

1. Open the **latest release** on GitHub (or the website's *Download* section) and download **all**
   files into one folder: `OfficeAssistant-Setup.exe` and the `OfficeAssistant-Setup-*.bin` parts next to
   it (the installer is split into parts because it is larger than the 2 GB GitHub limit per file).
2. Double-click `OfficeAssistant-Setup.exe`. Windows SmartScreen may warn about an unknown publisher
   (the installer is not code-signed): choose *More info → Run anyway*.
3. Accept the licence, choose the folder (default `C:\Program Files\Office Assistant`) and whether you
   want a desktop shortcut.
4. Start **Office Assistant** from the Start menu or the desktop.

## First start

* **Managers**: *Create company* (in the app or on the website). Then share the **company code** or an
  **invite link** (website → *Employees*) with your team.
* **Employees**: *Join a company* with the code or the link; sign in once your manager has approved you.
* Forgot your password? Use *Forgot password* on the website's sign-in page.
* The first time you use the camera, Windows may ask for camera permission
  (*Settings → Privacy & security → Camera → Let desktop apps access your camera*).

## Where your data is

Your company's data (accounts, sessions, tasks, calendar, meetings, messages, documents) is kept in the
company's online account. On the PC, for your Windows user:

```
%LOCALAPPDATA%\OfficeAssistant\
    outbox\                 finished work sessions waiting to be sent (when offline)
    logs\app.log            the application log (useful when reporting a problem)
```

The sign-in token is kept in the Windows Credential Manager. Theme and AI settings are stored in the
registry (`HKEY_CURRENT_USER\Software\DesktopAIOfficeAssistant`).

## Update

Install the new version over the old one. Nothing on the PC needs migrating.

## Uninstall

*Settings → Apps → Installed apps → Office Assistant → Uninstall*. The uninstaller asks whether to also
delete the local folder (`%LOCALAPPDATA%\OfficeAssistant`). Your company's online data is not touched.
