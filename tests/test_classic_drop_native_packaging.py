import plistlib
from pathlib import Path

from scripts import build_classic_drop_native as native


def test_assembly_embeds_runtime_and_preserves_app_identity(tmp_path: Path) -> None:
    binary = tmp_path / "ClassicDrop"
    binary.write_bytes(b"native executable")
    binary.chmod(0o755)
    resources = tmp_path / "ClassicDrop_ClassicDrop.bundle"
    resources.mkdir()
    (resources / "sample.txt").write_text("translated resource")
    helper = tmp_path / "classic-drop-helper"
    helper.mkdir()
    (helper / "classic-drop-helper").write_bytes(b"helper executable")
    (helper / "_internal").mkdir()
    (helper / "_internal/runtime").write_bytes(b"embedded python")
    app = tmp_path / "output/Classic Drop.app"
    native.assemble_app(binary, resources, helper, app)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "local.classicdrop.app"
    assert info["LSMinimumSystemVersion"] == "12.3"
    assert (app / "Contents/Resources/classic-drop.icns").read_bytes() == (
        native.ROOT / "src/classic_drop/assets/classic-drop-glass.icns"
    ).read_bytes()
    assert (app / "Contents/MacOS/Classic Drop").read_bytes() == b"native executable"
    assert (
        app / "Contents/Helpers/ClassicDropHelper.app/_internal/runtime"
    ).read_bytes() == b"embedded python"
    assert (
        app / "Contents/Resources/ClassicDrop_ClassicDrop.bundle/sample.txt"
    ).read_text() == "translated resource"


def test_assembly_refuses_overwriting_an_existing_bundle(tmp_path: Path) -> None:
    import pytest

    app = tmp_path / "Classic Drop.app"
    app.mkdir()
    with pytest.raises(FileExistsError):
        native.assemble_app(Path("unused"), Path("unused"), Path("unused"), app)
