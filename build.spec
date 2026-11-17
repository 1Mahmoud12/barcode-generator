# PyInstaller spec for the Windows build.
#
# Build with:
#     pyinstaller build.spec --noconfirm
#
# Output: dist\IVDPackTooling\IVDPackTooling.exe  (a folder, not one file)
#
# One folder rather than one file on purpose: a single-file build unpacks a
# temporary copy on every launch, which takes seconds with PySide6 and makes
# antivirus scanners suspicious. A folder starts instantly and is easier to support.
#
# zint is NOT bundled. It is a separate executable the user installs, because
# bundling a third-party binary into a distributed package requires shipping its
# licence and source offer. The app detects its absence and says what to do.

import sys
from pathlib import Path

block_cipher = None

# Hidden imports: modules loaded dynamically or only by name at runtime.
hidden = [
    "bcgen",
    "bcgen.code128",
    "bcgen.generate",
    "bcgen.label",
    "bcgen.measure",
    "bcgen.pack",
    "bcgen.payload",
    "bcgen.register",
    "bcgen.render",
    "bcgen.results",
    "bcgen.sheet",
    "bcgen.solution",
    "bcgen.calib",
    "bcgen.kind",
    "app",
    "label_app",
    "pack_app",
    "solution_app",
    "batch_app",
    "zxingcpp",
    "pypdfium2",
    "segno",
    "ppf.datamatrix",
    "numpy",
]

# Data files that must sit beside the executable.
datas: list[tuple[str, str]] = []
readme = Path("README.md")
if readme.exists():
    datas.append(("README.md", "."))

a = Analysis(
    ["main_app.py"],
    pathex=[str(Path.cwd())],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test and dev-only modules never needed at runtime.
        "tests",
        "PyInstaller",
        "pytest",
        "tkinter",
        # Qt modules this app does not use; excluding them cuts ~150 MB.
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IVDPackTooling",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression triggers antivirus false positives
    console=False,      # windowed app; set True while debugging startup errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="IVDPackTooling",
)
