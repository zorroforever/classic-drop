import base64
import subprocess
from contextlib import ExitStack
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4
from PIL import Image

from classic_drop.media import collect_audio, prepare_song
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


def test_flac_converts_to_alac_and_retains_unicode_tags_and_picture(tmp_path):
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
                source, device.active.profile, resources, lambda: None
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
