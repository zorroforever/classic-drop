"""Build a self-contained SwiftUI app without changing the retained Qt entry."""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "native/ClassicDrop"
HELPER_DIST = ROOT / "build/native-helper-dist"


def assemble_app(
    binary: Path, resources: Path, helper: Path, destination: Path
) -> None:
    if destination.exists():
        raise FileExistsError(f"Choose a new output path; bundle exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="classic-drop-", dir=destination.parent
    ) as stage:
        app = Path(stage) / destination.name
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir()
        (contents / "Helpers").mkdir()
        shutil.copy2(binary, contents / "MacOS/Classic Drop")
        shutil.copytree(resources, contents / "Resources" / resources.name)
        shutil.copytree(
            helper, contents / "Helpers/ClassicDropHelper.app", symlinks=True
        )
        shutil.copy2(
            ROOT / "src/classic_drop/assets/classic-drop-glass.icns",
            contents / "Resources/classic-drop.icns",
        )
        for name in ("LICENSE", "COPYING.md", "ACKNOWLEDGEMENTS.md"):
            shutil.copy2(ROOT / name, contents / "Resources" / name)
        shutil.copytree(
            ROOT / "packaging/third-party", contents / "Resources/third-party"
        )
        (contents / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleIdentifier": "local.classicdrop.app",
                    "CFBundleExecutable": "Classic Drop",
                    "CFBundleName": "Classic Drop",
                    "CFBundleDisplayName": "Classic Drop",
                    "CFBundlePackageType": "APPL",
                    "CFBundleShortVersionString": "0.1.0",
                    "CFBundleVersion": "0.1.0",
                    "CFBundleIconFile": "classic-drop.icns",
                    "CFBundleDevelopmentRegion": "en",
                    "CFBundleLocalizations": ["en", "zh-Hans", "ja"],
                    "LSMinimumSystemVersion": "12.3",
                    "NSPrincipalClass": "NSApplication",
                    "NSHighResolutionCapable": True,
                    "NSRemovableVolumesUsageDescription": "管理所选 iPod 的音乐曲库。",
                }
            )
        )
        app.rename(destination)


def sign_app(app: Path) -> None:
    magic = {
        b"\xcf\xfa\xed\xfe",
        b"\xce\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xca\xfe\xba\xbf",
    }
    for path in sorted(app.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path == app / "Contents/MacOS/Classic Drop":
            continue
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                is_macho = stream.read(4) in magic
            if is_macho:
                subprocess.run(
                    ["codesign", "--force", "--sign", "-", str(path)],
                    check=True,
                    capture_output=True,
                )
        elif (
            path.is_dir()
            and path.suffix in {".framework", ".app"}
            and not path.is_symlink()
        ):
            subprocess.run(
                ["codesign", "--force", "--sign", "-", str(path)],
                check=True,
                capture_output=True,
            )
    subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "dist/native/Classic Drop.app"
    )
    parser.add_argument(
        "--skip-helper-build",
        action="store_true",
        help="Reuse a helper already built from the current source",
    )
    options = parser.parse_args()
    if options.output.exists():
        parser.error("Output exists. Choose a new --output path.")
    environment = dict(os.environ, MACOSX_DEPLOYMENT_TARGET="12.3")
    subprocess.run(
        ["xcrun", "swift", "build", "-c", "release", "--package-path", str(PACKAGE)],
        env=environment,
        check=True,
    )
    if not options.skip_helper_build:
        subprocess.run(
            [
                "uv",
                "run",
                "pyinstaller",
                "--clean",
                "--noconfirm",
                "--distpath",
                str(HELPER_DIST),
                "--workpath",
                str(ROOT / "build/native-helper-work"),
                str(ROOT / "packaging/classic-drop-helper.spec"),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
    binary_directory = PACKAGE / ".build/release"
    assemble_app(
        binary_directory / "ClassicDrop",
        binary_directory / "ClassicDrop_ClassicDrop.bundle",
        HELPER_DIST / "ClassicDropHelper.app",
        options.output.absolute(),
    )
    sign_app(options.output.absolute())
    print(options.output.absolute())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
