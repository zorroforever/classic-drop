"""Resolve signing identity without mistaking generic USB serials for GUIDs."""

import plistlib
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import _ipod_volume

from device_registry import DeviceEvidence, DeviceIdentifier, EvidenceAuthority
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinator,
    _read_device_guid,
)
from iPodDB.iTunesDB.writer.signature import verify_hash58
from storage import (
    HardwareIdentifiers,
    HardwareProbeObservation,
    HardwareProbeResult,
    Storage,
)
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize(
    ("serials", "metadata", "expected"),
    [
        (("ABCDEF12614E", "000A27001234614E"), "", "000a27001234614e"),
        (("000a27001234614e", "0x000A27001234614E"), "", "000a27001234614e"),
        (("ABCDEF12614E",), "000A27001234614E", "000a27001234614e"),
        (("ABCDEF12614E",), "", ""),
        (("000A27001234614E", "000A27008765614E"), "000A27001234614E", ""),
        (("000A27001234614E",), "000A27008765614E", "000a27001234614e"),
    ],
)
def test_signing_uses_only_complete_hardware_guids(
    tmp_path: Path, serials: tuple[str, ...], metadata: str, expected: str
) -> None:
    root = tmp_path / "volume"
    directory = root / "iPod_Control" / "Device"
    directory.mkdir(parents=True)
    if metadata:
        (directory / "SysInfo").write_text(f"FirewireGuid: {metadata}\n")
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    evidence = DeviceEvidence(
        transport_serials=tuple(
            DeviceIdentifier(serial, "iokit", EvidenceAuthority.CURRENT_HARDWARE)
            for serial in serials
        )
    )

    with storage.open_session(storage.discover().volumes[0]) as session:
        guid = _read_device_guid(session, evidence)

    assert guid == bytes.fromhex(expected)


def test_classic_save_signs_with_live_guid_alongside_usb_serial(tmp_path: Path) -> None:
    root = _ipod_volume(tmp_path / "classic", model_number="MB565")
    database_path = root / "iPod_Control" / "iTunes" / "iTunesDB"
    original = database_path.read_bytes()
    guid = bytes.fromhex("000A27001234614E")
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(transport_serial="ABCDEF12614E"),
        probe_result=HardwareProbeResult(
            observations=(
                HardwareProbeObservation(
                    source="iokit",
                    transport_serial="ABCDEF12614E",
                    vendor_payload=plistlib.dumps({"FireWireGUID": guid.hex()}),
                ),
            )
        ),
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id,
            reconcile_metadata=False,
            reconcile_sidecars=False,
            initialize_missing=False,
        )
        edited = replace(
            active.library,
            tracks=(replace(active.library.tracks[0], title="Signed using live GUID"),),
        )

        review = coordinator.prepare_library(
            LibraryPreparationRequest(edited, active, 1, 1), lambda _: None, Event()
        )

        assert database_path.read_bytes() == original
        assert review.result.prepared is not None, review.result.issues
        assert verify_hash58(review.result.prepared.itunes, guid)
        saved = coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[0].title == "Signed using live GUID"
        assert verify_hash58(database_path.read_bytes(), guid)
        assert (
            root / "iPod_Control" / "Device" / "SysInfo"
        ).read_text() == "ModelNumStr: MB565\n"
    finally:
        coordinator.close()
