# Installing the Desktop AI Office Assistant

## Requirements

| | minimum | recommended |
|---|---|---|
| Windows | 10 or 11, 64-bit | 11 |
| Disk space | 12.2 GB for the program (+ 7.4 GB for the installer files while installing) | SSD |
| Memory | 8 GB | 16 GB |
| Camera | any webcam (optional — without one the session uses screen + keyboard only) | |
| Graphics | none (the chat model then runs on the CPU, slowly) | NVIDIA GPU with 6 GB+, driver 525 or newer |
| Internet | **not needed** — all AI models are inside the installer | |

## Install

1. Copy the whole installer folder (7.4 GB) to the PC: `OfficeAssistant-Setup.exe` **and** the four
   `OfficeAssistant-Setup-1.bin` … `-4.bin` files next to it (the installer is split into ~1.9 GB parts
   because it is larger than 4 GB).
2. Double-click `OfficeAssistant-Setup.exe`. Windows SmartScreen may warn about an unknown publisher
   (the installer is not code-signed): choose *More info → Run anyway*.
3. Accept the licence, choose the folder (default `C:\Program Files\Office Assistant`) and whether you
   want desktop shortcuts. Installation unpacks 12.2 GB and takes about 5–15 minutes.
4. Start **Office Assistant** from the Start menu or the desktop.

Two programs are installed:

| program | for |
|---|---|
| **Office Assistant** | everyone: employees and managers |
| **Office Assistant Admin** | developer / IT tool (password `admin123`): users, backups, factory reset |

## First start

1. Log in with a demo account, then immediately change its password in **Settings**:
   * Manager — `manager` / `1234`
   * Employee — `marwan` / `1234`
2. New employees click **Sign up** on the login screen; a manager approves them under **Employees**.
3. The first time you use the camera, Windows may ask for camera permission
   (*Settings → Privacy & security → Camera → Let desktop apps access your camera*).

## Where your data is

Everything you create is stored for your Windows user in

```
%LOCALAPPDATA%\OfficeAssistant\
    office_assistant.db     the database (accounts, sessions, tasks, calendar, chats, documents)
    logs\app.log            the application log (useful when reporting a problem)
```

Back it up with **Office Assistant Admin → Danger zone → Export database**, or by copying the folder
while the app is closed. Theme and AI-model settings are stored in the Windows registry
(`HKEY_CURRENT_USER\Software\DesktopAIOfficeAssistant`).

## Update

Install the new version over the old one. Your data folder is kept and the database is migrated
automatically on the first start (no data is deleted).

## Uninstall

*Settings → Apps → Installed apps → Office Assistant → Uninstall*. The uninstaller asks whether to also
delete your data folder (`%LOCALAPPDATA%\OfficeAssistant`); answer *No* to keep it for a later reinstall.
