"""PyInstaller bundle for the append-only Classic Drop macOS app."""
# PyInstaller injects Analysis, PYZ, EXE, COLLECT, BUNDLE, and SPECPATH.
# ruff: noqa: F821

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

root = Path(SPECPATH).parent
datas: list[tuple[str, str]] = []
for package in ("device_registry", "iPodDB", "storage", "tzdata"):
    datas += collect_data_files(package)
datas += collect_data_files("iOpenPod", includes=["assets/glyphs/*.svg"])
datas += [
    (str(catalog), "classic_drop/translations")
    for catalog in (root / "src/classic_drop/translations").glob("*.qm")
]
binaries = collect_dynamic_libs("wasmtime", search_patterns=["*.dylib", "*.so"])
hiddenimports = [
    *collect_submodules("tzdata"),
    "Crypto.PublicKey._ed25519",
    "Crypto.PublicKey._ed448",
]

a = Analysis(
    [str(root / "src/classic_drop/__main__.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(root / "packaging/hooks")],
    excludes=["torch", "torchaudio", "demucs", "pytest", "mypy", "tkinter", "_tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    [],
    exclude_binaries=True,
    name="Classic Drop",
    console=False,
    argv_emulation=False,
    debug=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Classic Drop", strip=False, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Classic Drop.app",
        bundle_identifier="local.classicdrop.app",
        info_plist={
            "CFBundleDisplayName": "Classic Drop",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSPrincipalClass": "NSApplication",
            "NSHighResolutionCapable": True,
            "NSRemovableVolumesUsageDescription": "管理所选 iPod 的音乐曲库。",
        },
    )
