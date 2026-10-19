# PyInstaller build of the Desktop AI Office Assistant (two programs, one folder).
#
#   pyinstaller packaging/OfficeAssistant.spec --noconfirm --clean
#
# Output: dist/OfficeAssistant/
#   OfficeAssistant.exe        the application (main.py)
#   OfficeAssistant-Admin.exe  the admin panel (admin.py)
#   _internal/                 Python, Qt, PyTorch + CUDA, the AI models, icons
#
# One-folder (not one-file): PyTorch's CUDA DLLs and ~8 GB of models would have to be
# unpacked to a temp folder on every start in one-file mode.
import os

from PyInstaller.building import build_main
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# On Windows, importing sentencepiece after PyQt5 crashes the process (access violation);
# main.py therefore imports it first. PyInstaller's binary-dependency step imports every
# collected package in one process and always puts Qt first. sentencepiece registers no
# extra DLL directories (it is a single .pyd), so it is simply left out of that step; it is
# still collected normally.
_find_binary_dependencies = build_main.find_binary_dependencies


def _without_sentencepiece(binaries, import_packages, *args, **kwargs):
    kept = [name for name in import_packages if not name.startswith("sentencepiece")]
    return _find_binary_dependencies(binaries, kept, *args, **kwargs)


build_main.find_binary_dependencies = _without_sentencepiece

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(ROOT, "assets", "icons", "app.ico")

datas = [
    (os.path.join(ROOT, "assistant", "intent_model.pt"), "assistant"),
    (os.path.join(ROOT, "assets"), "assets"),
]
# OFFICE_BUILD_NO_MODELS=1 makes a quick test build without the ~8 GB of models.
if os.environ.get("OFFICE_BUILD_NO_MODELS") != "1":
    datas.append((os.path.join(ROOT, "models"), "models"))         # Qwen, BART, MarianMT, YOLO (offline)
binaries = []
hiddenimports = [
    "PyQt5.QtSvg",
    "sentencepiece",
    "win32gui", "win32con", "win32api",
]

# ultralytics reads its YAML configs at run time; PyMuPDF ships native resources.
for package in ("ultralytics", "pymupdf"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# transformers imports model classes lazily by name -- collect the families the app uses.
for module in ("transformers.models.auto", "transformers.models.qwen2", "transformers.models.bart",
               "transformers.models.marian", "transformers.generation"):
    hiddenimports += collect_submodules(module)
datas += collect_data_files("transformers", include_py_files=False)

# transformers.pipelines is unused (we call generate() directly) and its import crashes
# PyInstaller's isolated analysis subprocess (access violation) on this stack.
excludes = ["tkinter", "pytest", "IPython", "notebook", "tensorflow", "jax", "flax",
            "transformers.pipelines", "transformers.commands"]


def analysis(script):
    return Analysis(
        [os.path.join(ROOT, script)],
        pathex=[ROOT],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=excludes,
        noarchive=False,
    )


def newer_vc_runtime(analysis_):
    """PyQt5 ships the 2020 MSVC runtime (14.26) in PyQt5/Qt5/bin; torch and sentencepiece need a
    newer one and crash in MSVCP140.dll when Qt's old copy is loaded first. Replace those copies
    with the build machine's current runtime (backward compatible), so the bundle does not depend
    on what the target PC has installed."""
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    replaced = []
    for i, (dest, src, kind) in enumerate(analysis_.binaries):
        name = os.path.basename(dest).lower()
        newer = os.path.join(system32, name)
        if dest.replace("\\", "/").startswith("PyQt5/") and name.startswith(("msvcp140", "vcruntime140")) \
                and os.path.exists(newer):
            analysis_.binaries[i] = (dest, newer, kind)
            replaced.append(dest)
    print("newer_vc_runtime: replaced", replaced)


app_a = analysis("main.py")
admin_a = analysis("admin.py")
newer_vc_runtime(app_a)
newer_vc_runtime(admin_a)

app_pyz = PYZ(app_a.pure)
admin_pyz = PYZ(admin_a.pure)

app_exe = EXE(app_pyz, app_a.scripts, [], exclude_binaries=True, name="OfficeAssistant",
              icon=ICON, console=False, upx=False)
admin_exe = EXE(admin_pyz, admin_a.scripts, [], exclude_binaries=True, name="OfficeAssistant-Admin",
                icon=ICON, console=False, upx=False)

coll = COLLECT(
    app_exe, app_a.binaries, app_a.datas,
    admin_exe, admin_a.binaries, admin_a.datas,
    upx=False,
    name="OfficeAssistant",
)
