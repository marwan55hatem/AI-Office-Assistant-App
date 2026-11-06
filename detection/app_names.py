"""Which application owns the focused window -- by process name, never by window title.

Only a short display name such as "Chrome" or "VS Code" is produced. Window titles
(page names, document names, chat partners) are not part of it and do not leave the
computer. Windows-only; on any failure the name is "" and nothing is counted.
"""
import os
import re

OTHER = "Other"
MAX_LENGTH = 80

#: process name (lower case, without ``.exe``) -> the name people recognise
FRIENDLY = {
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "brave": "Brave", "opera": "Opera",
    "code": "VS Code", "devenv": "Visual Studio", "pycharm64": "PyCharm", "pycharm": "PyCharm",
    "idea64": "IntelliJ IDEA", "studio64": "Android Studio", "sublime_text": "Sublime Text",
    "notepad": "Notepad", "notepad++": "Notepad++", "cursor": "Cursor",
    "winword": "Word", "excel": "Excel", "powerpnt": "PowerPoint", "outlook": "Outlook", "onenote": "OneNote",
    "olk": "Outlook", "wps": "WPS Office", "et": "WPS Spreadsheets", "wpp": "WPS Presentation",
    "teams": "Teams", "ms-teams": "Teams", "slack": "Slack", "zoom": "Zoom", "skype": "Skype",
    "discord": "Discord", "telegram": "Telegram", "whatsapp": "WhatsApp", "whatsapp.root": "WhatsApp",
    "spotify": "Spotify", "vlc": "VLC", "steam": "Steam", "epicgameslauncher": "Epic Games",
    "explorer": "File Explorer", "cmd": "Command Prompt", "powershell": "PowerShell", "pwsh": "PowerShell",
    "windowsterminal": "Windows Terminal", "wt": "Windows Terminal", "mintty": "Git Bash",
    "acrobat": "Acrobat", "acrord32": "Acrobat Reader", "sumatrapdf": "SumatraPDF",
    "figma": "Figma", "photoshop": "Photoshop", "illustrator": "Illustrator", "blender": "Blender",
    "postman": "Postman", "docker desktop": "Docker Desktop", "taskmgr": "Task Manager",
    "calculatorapp": "Calculator", "calc": "Calculator", "snippingtool": "Snipping Tool",
    "claude": "Claude", "notion": "Notion", "obsidian": "Obsidian", "python": "Python", "pythonw": "Python",
    "officeassistant": "Office Assistant",
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def display_name(executable: str) -> str:
    """``C:\\Program Files\\Google\\Chrome\\chrome.exe`` -> ``Chrome``; unknown programs get a tidy name."""
    stem = os.path.splitext(os.path.basename(str(executable or "").replace("\\", "/")))[0].strip().lower()
    if not stem:
        return ""
    if stem in FRIENDLY:
        return FRIENDLY[stem]
    words = re.sub(r"[._-]+", " ", stem).strip()
    name = " ".join(word.capitalize() if word.islower() else word for word in words.split()) or OTHER
    return _CONTROL.sub("", name)[:MAX_LENGTH] or OTHER


def process_image_path(hwnd) -> str:
    """The full path of the program that owns window ``hwnd``, or "" when Windows will not say."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if not pid.value:
            return ""
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = kernel32.QueryFullProcessImageNameW(wintypes.HANDLE(handle), 0, buffer, ctypes.byref(size))
            return buffer.value if ok else ""
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(handle))
    except Exception:
        return ""


def active_app_name(hwnd) -> str:
    """Display name of the program that owns ``hwnd`` ("" if unknown; "Other" for protected programs)."""
    if not hwnd:
        return ""
    path = process_image_path(hwnd)
    return display_name(path) if path else OTHER
