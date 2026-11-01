# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Nexa.  Build with:  build_exe.bat   (or: pyinstaller nexa.spec --noconfirm --clean)

Output: dist/Nexa/Nexa.exe  (a folder build - faster to start and far less likely to be
flagged by antivirus than a single-file build, which unpacks ~400 MB to a temp folder on every launch).
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(SPECPATH)  # noqa: F821  (SPECPATH is provided by PyInstaller)
DIST_UI = os.path.join(ROOT, "frontend", "dist")
if not os.path.isfile(os.path.join(DIST_UI, "index.html")):
    raise SystemExit("frontend/dist is missing - run `npm install && npm run build` inside frontend/ first.")

datas = [(DIST_UI, os.path.join("frontend", "dist"))]  # the React UI, served by FastAPI
binaries = []
hiddenimports = []

# Packages that ship native libraries, model assets or lazily imported modules.
# A package that is not installed (e.g. PyAudioWPatch off Windows) is skipped.
for package in (
    "faster_whisper",  # includes assets/silero_vad*.onnx
    "ctranslate2",
    "tokenizers",
    "av",
    "onnxruntime",
    "huggingface_hub",
    "webview",  # pywebview: WebView2 loader DLLs + JS bridge
    "clr_loader",  # pythonnet runtime used by pywebview on Windows
    "pythonnet",
    "pyaudiowpatch",  # WASAPI loopback (_portaudiowpatch.pyd)
    "docx",  # python-docx default templates
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception as exc:  # noqa: BLE001
        print(f"[nexa.spec] skipping {package}: {exc}")
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# uvicorn / starlette pick protocol, loop and lifespan implementations by string name at runtime.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["multipart", "python_multipart", "dotenv", "pypdf", "email.mime.multipart"]
hiddenimports += collect_submodules("backend")

a = Analysis(
    [os.path.join(ROOT, "desktop.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "pytest", "IPython", "notebook", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

ICON = os.path.join(ROOT, "nexa.ico")  # optional: drop a nexa.ico next to this file to brand the exe

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Nexa",
    console=False,  # no black console window
    icon=ICON if os.path.isfile(ICON) else None,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Nexa",
)
