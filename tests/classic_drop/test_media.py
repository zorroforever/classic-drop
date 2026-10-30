import base64
import subprocess
from contextlib import ExitStack
from pathlib import Path

import pytest
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4
from PIL import Image

from classic_drop.media import collect_audio, prepare_song
from iOpenPod.app.display_text import SourceText
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device

FIXTURES = Path(__file__).parents[1] / "fixtures/media"


def media_file(directory: Path, name: str = "chapters-cover.m4a") -> Path:
    target = directory / name
    target.write_bytes(base64.decodebytes((FIXTURES / f"{name}.b64").read_bytes()))
    return target


def test_collect_audio_deduplicates_overlaps_and_ignores_symlinks(tmp_path):
    album = tmp_path / "Album"
    album.mkdir()
    song = album / "01.MP3"
    song.touch()
    (album / "cover.jpg").touch()
    (album / "._02.mp3").touch()
    (album / "linked.mp3").symlink_to(song)
    (album / "loop").symlink_to(album, target_is_directory=True)
    assert collect_audio((album, song)) == (song,)


def test_missing_input_preserves_a_translatable_path_template(tmp_path):
    path = tmp_path / "缺失.m4a"

    with pytest.raises(ValueError) as captured:
        collect_audio((path,))

    assert isinstance(captured.value.args[0], SourceText)
    assert captured.value.args[0].source == "File not found: {path}"
    assert captured.value.args[0].parameters == (("path", str(path.absolute())),)


def test_compatible_file_is_unchanged_with_embedded_cover(tmp_path):
    device = bare_device(tmp_path)
    source = media_file(tmp_path)
    original = source.read_bytes()
    try:
        with ExitStack() as resources:
            prepared = prepare_song(
                source, device.active.profile, resources, lambda: None
            )
            assert prepared.song.source.source.path == source
            assert prepared.song.track.title == "Chapter test"
            assert prepared.song.artwork is not None
            assert prepared.mode == "copy"
            assert source.read_bytes() == original
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("original_alac", [False, True])
def test_flac_converts_to_alac_and_retains_unicode_tags_and_picture(
    tmp_path: Path, original_alac: bool
) -> None:
    device = bare_device(tmp_path)
    source = tmp_path / "夜曲.flac"
    original_audio = media_file(tmp_path, "lossless.m4a")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(original_audio),
            "-c:a",
            "flac",
            str(source),
        ],
        check=True,
    )
    cover = tmp_path / "front.png"
    Image.new("RGB", (40, 40), (230, 30, 70)).save(cover)
    tags = FLAC(source)
    tags["title"], tags["artist"], tags["album"] = "夜曲", "演奏者", "作品集"
    tags["albumartist"] = "专辑艺人"
    tags["tracknumber"], tags["discnumber"] = "3/8", "2/2"
    picture = Picture()
    picture.type, picture.mime, picture.data = 3, "image/png", cover.read_bytes()
    tags.add_picture(picture)
    tags.save()
    original = source.read_bytes()
    try:
        with ExitStack() as resources:
            prepared = prepare_song(
                source,
                device.active.profile,
                resources,
                lambda: None,
                allow_high_resolution_alac=original_alac,
            )
            song = prepared.song
            assert prepared.mode == "convert"
            assert (song.track.title, song.track.artist, song.track.album) == (
                "夜曲",
                "演奏者",
                "作品集",
            )
            assert song.track.album_artist == "专辑艺人"
            assert song.track.track_number == 3 and song.track.metadata.disc_number == 2
            assert song.artwork is not None
            assert song.artwork.rgb888[:3] == bytes((230, 30, 70))
            assert Path(song.source.source.path).exists()
            converted_tags = MP4(song.source.source.path)
            assert converted_tags.tags["\u00a9nam"] == ["夜曲"]
            assert converted_tags.tags["covr"]
            converted = Path(song.source.source.path)
            assert source.read_bytes() == original
        assert not converted.exists()
    finally:
        device.coordinator.close()


def test_folder_cover_is_used_only_when_no_embedded_cover(tmp_path):
    device = bare_device(tmp_path)
    source = media_file(tmp_path, "tone.mp3")
    Image.new("RGB", (32, 32), (0, 255, 0)).save(tmp_path / "cover.jpg")
    try:
        with ExitStack() as resources:
            prepared = prepare_song(
                source, device.active.profile, resources, lambda: None
            )
            assert prepared.song.artwork is not None
            assert prepared.song.artwork.rgb888[1] >= 250
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("original", [False, True])
def test_alac_original_switch_preserves_high_resolution_bytes_only_when_enabled(
    tmp_path: Path, original: bool
) -> None:
    from classic_drop.audio_format import AudioFormat, inspect_audio_format
    from tests.classic_drop.test_audio_format import Source, encoded_audio

    device = bare_device(tmp_path)
    source = tmp_path / "hires.m4a"
    source.write_bytes(encoded_audio(tmp_path, "alac", 96000, 24))
    before = source.read_bytes()
    try:
        with ExitStack() as resources:
            prepared = prepare_song(
                source,
                device.active.profile,
                resources,
                lambda: None,
                allow_high_resolution_alac=original,
            )
            output = prepared.song.source.source.path
            assert inspect_audio_format(
                Source(Path(output).read_bytes()), checkpoint=lambda: None
            ) == (
                AudioFormat("ALAC", 24, 96000)
                if original
                else AudioFormat("ALAC", 16, 44100)
            )
            assert prepared.mode == ("copy" if original else "convert")
            assert source.read_bytes() == before
            if original:
                assert output == source
                assert Path(output).read_bytes() == before
                assert "96000" in " ".join(prepared.warnings)
    finally:
        device.coordinator.close()


def test_alac_override_does_not_accept_high_resolution_aac_as_alac(
    tmp_path: Path,
) -> None:
    from iOpenPod.app.media.importing import MusicImporter
    from iOpenPod.app.media.inspection import MediaInspectionError
    from storage import HostPath
    from tests.classic_drop.test_audio_format import encoded_audio

    device = bare_device(tmp_path)
    source = tmp_path / "pretend-alac.m4a"
    source.write_bytes(encoded_audio(tmp_path, "aac", 96000, 16))
    try:
        with pytest.raises(MediaInspectionError):
            MusicImporter().inspect(
                HostPath(source),
                device.active.profile,
                checkpoint=lambda: None,
                allow_high_resolution_alac=True,
            )
    finally:
        device.coordinator.close()


def test_default_importer_still_rejects_high_resolution_alac(tmp_path: Path) -> None:
    from iOpenPod.app.media.importing import MusicImporter
    from iOpenPod.app.media.inspection import MediaInspectionError
    from storage import HostPath
    from tests.classic_drop.test_audio_format import encoded_audio

    device = bare_device(tmp_path)
    source = tmp_path / "hires.m4a"
    source.write_bytes(encoded_audio(tmp_path, "alac", 96000, 24))
    try:
        with pytest.raises(MediaInspectionError):
            MusicImporter().inspect(
                HostPath(source), device.active.profile, checkpoint=lambda: None
            )
    finally:
        device.coordinator.close()


def test_original_alac_with_unsupported_channels_fails_without_conversion(
    tmp_path: Path,
) -> None:
    from iOpenPod.app.media.inspection import MediaInspectionError

    device = bare_device(tmp_path)
    source = tmp_path / "surround.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=96000:cl=5.1",
            "-t",
            "0.1",
            "-c:a",
            "alac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    try:
        with ExitStack() as resources, pytest.raises(MediaInspectionError):
            prepare_song(
                source,
                device.active.profile,
                resources,
                lambda: None,
                allow_high_resolution_alac=True,
            )
    finally:
        device.coordinator.close()


def test_original_alac_in_unsupported_container_fails_without_silent_conversion(
    tmp_path: Path,
) -> None:
    from iOpenPod.app.media.inspection import MediaInspectionError

    device = bare_device(tmp_path)
    source = tmp_path / "disguised.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=sample_rate=96000:duration=0.1",
            "-c:a",
            "alac",
            "-sample_fmt",
            "s32p",
            "-f",
            "caf",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    before = source.read_bytes()
    try:
        with ExitStack() as resources, pytest.raises(MediaInspectionError):
            prepare_song(
                source,
                device.active.profile,
                resources,
                lambda: None,
                allow_high_resolution_alac=True,
            )
        assert source.read_bytes() == before
    finally:
        device.coordinator.close()
