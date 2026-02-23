# clipcommand.spec
# ─────────────────────────────────────────────────────────────────────────────
# PyInstaller build spec for ClipCommand
#
# Usage:
#   pip install pyinstaller
#   pyinstaller clipcommand.spec
#
# Output:
#   dist/ClipCommand/          <- distribute this entire folder
#
# To build a macOS .app bundle instead:
#   Set BUNDLE_APP = True below
#
# To build on Windows (produces ClipCommand.exe):
#   Run exactly the same command — the spec handles both platforms.
# ─────────────────────────────────────────────────────────────────────────────

import sys
import os
from pathlib import Path

# ── Build options ─────────────────────────────────────────────────────────────

BUNDLE_APP  = False   # macOS only: True = .app bundle, False = plain folder+exe
APP_NAME    = "ClipCommand"
APP_VERSION = "1.2.0"

# Path to an icon file (optional — comment out if you don't have one)
# macOS: .icns file,  Windows: .ico file
# ICON_FILE = "assets/clipcommand.icns"   # macOS
# ICON_FILE = "assets/clipcommand.ico"    # Windows
ICON_FILE   = None

# ─────────────────────────────────────────────────────────────────────────────

block_cipher = None

# Detect platform
is_mac     = sys.platform == "darwin"
is_windows = sys.platform == "win32"

# ── Hidden imports ────────────────────────────────────────────────────────────
# Modules that PyInstaller misses because they're imported dynamically

hidden_imports = [
    # PySide6 internals
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    # Clipboard
    "pyperclip",
    # YAML
    "yaml",
    # python-docx (optional Word transforms)
    "docx",
    "docx.oxml",
    "docx.oxml.ns",
    "docx.table",
    # Anthropic (optional AI transforms)
    "anthropic",
    "httpx",
    # Standard lib used by transforms
    "importlib.util",
    "configparser",
    "sqlite3",
    "json",
    "subprocess",
    "re",
]

# Add win32com on Windows
if is_windows:
    hidden_imports += [
        "win32com",
        "win32com.client",
        "win32com.client.gencache",
        "pywintypes",
    ]

# ── Data files ────────────────────────────────────────────────────────────────
# (source, dest_in_bundle)
# The transforms folder ships alongside the executable, NOT bundled inside it,
# because users need to edit/add transforms at runtime.
# We include a starter set here; advanced users can add more.

datas = []

# Include the runtime support modules that clipcommand.py imports directly
for module_file in ["db_logger.py", "log_browser.py"]:
    if Path(module_file).exists():
        datas.append((module_file, "."))

# Include a starter transforms folder with the core/example scripts
# (excludes user-specific configs like word_from_yaml_active.py DOC_PATH)
transforms_dir = Path("transforms")
if transforms_dir.exists():
    datas.append(("transforms", "transforms"))

# ── Analysis ──────────────────────────────────────────────────────────────────

a = Analysis(
    ["clipcommand.py"],
    pathex        = [str(Path(".").resolve())],
    binaries      = [],
    datas         = datas,
    hiddenimports = hidden_imports,
    hookspath     = [],
    hooksconfig   = {},
    runtime_hooks = [],
    excludes      = [
        # Exclude heavy unused packages to keep bundle size down
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "tkinter",
        "wx",
        "PyQt5",
        "PyQt6",
    ],
    win_no_prefer_redirects = False,
    win_private_assemblies  = False,
    cipher                  = block_cipher,
    noarchive               = False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Executable ────────────────────────────────────────────────────────────────

exe_kwargs = dict(
    name          = APP_NAME,
    debug         = False,
    bootloader_ignore_signals = False,
    strip         = False,
    upx           = True,          # compress if UPX is installed
    console       = False,         # no terminal window
    disable_windowed_traceback = False,
    target_arch   = None,
    codesign_identity   = None,
    entitlements_file   = None,
)

if ICON_FILE and Path(ICON_FILE).exists():
    exe_kwargs["icon"] = ICON_FILE

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries = True,
    **exe_kwargs,
)

# ── Collection (onedir — one folder, fast startup) ────────────────────────────

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip       = False,
    upx         = True,
    upx_exclude = [],
    name        = APP_NAME,
)

# ── macOS .app bundle (optional) ──────────────────────────────────────────────

if is_mac and BUNDLE_APP:
    app = BUNDLE(
        coll,
        name     = f"{APP_NAME}.app",
        icon     = ICON_FILE if ICON_FILE and Path(ICON_FILE).exists() else None,
        bundle_identifier = f"au.com.aidinsight.{APP_NAME.lower()}",
        info_plist = {
            "CFBundleName":             APP_NAME,
            "CFBundleDisplayName":      APP_NAME,
            "CFBundleVersion":          APP_VERSION,
            "CFBundleShortVersionString": APP_VERSION,
            "NSHighResolutionCapable":  True,
            "NSRequiresAquaSystemAppearance": False,  # allow dark mode
        },
    )
