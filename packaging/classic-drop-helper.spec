"""Console helper embedded in the native app; no Qt application or widgets."""
# PyInstaller supplies the spec execution globals.
# ruff: noqa: F821

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

root = Path(SPECPATH).parent
datas = []
for package in ("device_registry", "iPodDB", "storage", "tzdata"):
    datas += collect_data_files(package)

a = Analysis(
    [str(root / "src/classic_drop/native_helper.py")],
    pathex=[str(root / "src")],
    binaries=collect_dynamic_libs("wasmtime", search_patterns=["*.dylib", "*.so"]),
    datas=datas,
    hiddenimports=[
        *collect_submodules("tzdata"),
        "Crypto.PublicKey._ed25519",
        "Crypto.PublicKey._ed448",
    ],
    hookspath=[str(root / "packaging/hooks")],
    excludes=[
        "torch",
        "torchaudio",
        "demucs",
        "pytest",
        "mypy",
        "tkinter",
        "_tkinter",
        "PySide6.QtWidgets",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="classic-drop-helper",
    console=True,
    argv_emulation=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas, name="classic-drop-helper", strip=False, upx=False
)
app = BUNDLE(
    coll,
    name="ClassicDropHelper.app",
    bundle_identifier="local.classicdrop.helper",
    info_plist={
        "CFBundleName": "Classic Drop Worker",
        "LSMinimumSystemVersion": "12.3",
        "LSUIElement": True,
    },
)
