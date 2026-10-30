"""Native mounting is exact, unforced, and revalidated."""

import plistlib
import subprocess
from pathlib import Path
from typing import TypedDict

import pytest

from storage import (
    DeviceBus,
    HardwareIdentifiers,
    MountPoint,
    PhysicalDevice,
    PhysicalDeviceId,
    StorageCapabilities,
    StorageMountError,
    Volume,
    VolumeId,
)
from storage.models import VolumeObservation
from storage.platform import macos


class Partition(TypedDict, total=False):
    DeviceIdentifier: str
    Content: str
    Size: int
    DiskUUID: str
    VolumeName: str


class Disk(TypedDict, total=False):
    DeviceIdentifier: str
    Content: str
    Size: int
    Partitions: list[Partition]


class Layout(TypedDict):
    AllDisksAndPartitions: list[Disk]


NativeFixture = tuple[
    macos.MacOSPlatformAdapter,
    Layout,
    dict[str, str],
    dict[str, HardwareIdentifiers],
    list[list[str]],
    dict[str, int],
]


@pytest.fixture
def native(monkeypatch: pytest.MonkeyPatch) -> NativeFixture:
    layout: Layout = {
        "AllDisksAndPartitions": [
            {
                "DeviceIdentifier": "disk4",
                "Content": "FDisk_partition_scheme",
                "Size": 160000,
                "Partitions": [
                    {
                        "DeviceIdentifier": "disk4s2",
                        "Content": "DOS_FAT_32",
                        "Size": 150000,
                        "DiskUUID": "DATA-UUID",
                    }
                ],
            }
        ]
    }
    info = {
        "DeviceIdentifier": "disk4s2",
        "ParentWholeDisk": "disk4",
        "DiskUUID": "DATA-UUID",
        "MountPoint": "/Volumes/IPOD",
    }
    hardware = {"disk4": HardwareIdentifiers(0x05AC, 0x1261, transport_serial="SERIAL")}
    calls: list[list[str]] = []
    failure: dict[str, int] = {}

    def run(
        command: list[str], *, capture_output: bool, timeout: int, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        assert capture_output and not check and timeout <= 30
        if command[1] == "list":
            output = plistlib.dumps(layout)
        elif command[1] == "info":
            if command[-1] in ("disk4", "disk5"):
                output = plistlib.dumps(
                    {"DeviceIdentifier": command[-1], "BusProtocol": "USB"}
                )
            else:
                current = dict(info)
                if not failure.get("mounted"):
                    current.pop("MountPoint", None)
                output = plistlib.dumps(current)
        else:
            if failure.get("timeout"):
                raise subprocess.TimeoutExpired(command, 30)
            failure["mounted"] = True
            return subprocess.CompletedProcess(
                command, failure.get("code", 0), b"mounted", b"busy"
            )
        return subprocess.CompletedProcess(command, 0, output, b"")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(macos, "_ioreg_hardware_index", lambda: hardware)
    return macos.MacOSPlatformAdapter(), layout, info, hardware, calls, failure


def test_discover_unmounted_lists_external_devices_and_one_data_partition(
    native: NativeFixture,
) -> None:
    adapter, layout, _, _, calls, _ = native
    layout["AllDisksAndPartitions"].append(
        {"DeviceIdentifier": "disk5", "Partitions": []}
    )
    result = adapter.discover_unmounted()
    assert len(result.candidates) == 1
    assert {d.id.value for d in result.observed_devices} == {
        "macos:disk4",
        "macos:disk5",
    }
    assert calls[0] == ["diskutil", "list", "-plist", "external", "physical"]


def test_discover_unmounted_retains_observations_when_usb_correlation_is_incomplete(
    native: NativeFixture,
) -> None:
    adapter, _, _, hardware, _, _ = native
    hardware.clear()
    result = adapter.discover_unmounted()
    assert result.observed_devices[0].id.value == "macos:disk4"
    assert result.issues
    assert not result.candidates


@pytest.mark.parametrize("count", [0, 2])
def test_discover_unmounted_rejects_zero_or_ambiguous_filesystem_partitions(
    native: NativeFixture, count: int
) -> None:
    adapter, layout, _, _, _, _ = native
    partition = layout["AllDisksAndPartitions"][0]["Partitions"][0]
    layout["AllDisksAndPartitions"][0]["Partitions"] = [
        {**partition, "DeviceIdentifier": f"disk4s{i + 1}"} for i in range(count)
    ]
    assert not adapter.discover_unmounted().candidates


@pytest.mark.parametrize("change", ["serial", "partition", "absent"])
def test_mount_candidate_is_revalidated_before_diskutil_mount(
    native: NativeFixture, change: str
) -> None:
    adapter, layout, _, hardware, calls, _ = native
    candidate = adapter.discover_unmounted().candidates[0]
    if change == "serial":
        hardware["disk4"] = HardwareIdentifiers(
            0x05AC, 0x1261, transport_serial="OTHER"
        )
    elif change == "partition":
        layout["AllDisksAndPartitions"][0]["Partitions"][0]["DiskUUID"] = "OTHER"
    else:
        layout["AllDisksAndPartitions"] = []
    with pytest.raises(StorageMountError):
        adapter.mount(candidate)
    assert not any(command[1] == "mount" for command in calls)


def _observation(
    volume_uuid: str = "DATA-UUID", disk: str = "disk4"
) -> VolumeObservation:
    physical = PhysicalDevice(
        PhysicalDeviceId(f"macos:{disk}"), "External", DeviceBus.USB, True
    )
    return VolumeObservation(
        physical,
        Volume(
            VolumeId(f"macos:{volume_uuid}"),
            physical.id,
            "IPOD",
            "msdos",
            100,
            50,
            StorageCapabilities(True, True, False, None, None, None),
        ),
        MountPoint(Path("/Volumes/IPOD")),
        "mount-instance",
    )


def test_mount_targets_only_the_exact_partition_without_force(
    native: NativeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, _, _, calls, _ = native
    candidate = adapter.discover_unmounted().candidates[0]
    observation = _observation()
    monkeypatch.setattr(adapter, "inspect", lambda _path: observation)
    assert adapter.mount(candidate) is observation
    assert [c for c in calls if c[1] == "mount"] == [["diskutil", "mount", "disk4s2"]]
    assert calls[-1] == ["diskutil", "info", "-plist", "disk4s2"]


def test_mount_verifies_filesystem_uuid_separately_from_partition_uuid(
    native: NativeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, info, _, _, _ = native
    info["VolumeUUID"] = "FILESYSTEM-UUID"
    candidate = adapter.discover_unmounted().candidates[0]
    observation = _observation("FILESYSTEM-UUID")
    monkeypatch.setattr(adapter, "inspect", lambda _path: observation)
    assert adapter.mount(candidate) is observation


def test_mount_rejects_changed_filesystem_uuid_with_same_partition_uuid(
    native: NativeFixture,
) -> None:
    adapter, _, info, _, calls, _ = native
    info["VolumeUUID"] = "ORIGINAL-FILESYSTEM"
    candidate = adapter.discover_unmounted().candidates[0]
    info["VolumeUUID"] = "OTHER-FILESYSTEM"
    with pytest.raises(StorageMountError):
        adapter.mount(candidate)
    assert not any(command[1] == "mount" for command in calls)


@pytest.mark.parametrize("failure_kind", ["timeout", "native", "malformed"])
def test_mount_rejects_timeout_and_malformed_plist(
    native: NativeFixture, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    adapter, _, _, _, _, failure = native
    candidate = adapter.discover_unmounted().candidates[0]
    if failure_kind == "malformed":
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a[0], 0, b"invalid plist", b""),
        )
    else:
        failure["timeout" if failure_kind == "timeout" else "code"] = 1
    with pytest.raises(StorageMountError):
        adapter.mount(candidate)


@pytest.mark.parametrize("change", ["mount", "parent", "partition"])
def test_mount_requires_fresh_mounted_info(native: NativeFixture, change: str) -> None:
    adapter, _, info, _, _, _ = native
    candidate = adapter.discover_unmounted().candidates[0]
    info[
        {"mount": "MountPoint", "parent": "ParentWholeDisk", "partition": "DiskUUID"}[
            change
        ]
    ] = "" if change == "mount" else "other"
    with pytest.raises(StorageMountError):
        adapter.mount(candidate)


def test_mount_ignores_unrelated_external_disk_issue(
    native: NativeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, layout, _, _, _, failure = native
    layout["AllDisksAndPartitions"].append(
        {"DeviceIdentifier": "disk5", "Partitions": [{"DeviceIdentifier": "bad"}]}
    )
    candidate = adapter.discover_unmounted().candidates[0]
    failure["mounted"] = False
    observation = _observation()
    monkeypatch.setattr(adapter, "inspect", lambda _path: observation)
    assert adapter.mount(candidate) is observation


def test_mount_ignores_ambiguous_partitions_on_another_correlated_usb_disk(
    native: NativeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, layout, _, hardware, calls, _ = native
    hardware["disk5"] = HardwareIdentifiers(0x1234, 0x5678)
    layout["AllDisksAndPartitions"].append(
        {
            "DeviceIdentifier": "disk5",
            "Partitions": [
                {"DeviceIdentifier": f"disk5s{i}", "Content": "DOS_FAT_32"}
                for i in (1, 2)
            ],
        }
    )
    inventory = adapter.discover_unmounted()
    assert len(inventory.candidates) == 1
    observation = _observation()
    monkeypatch.setattr(adapter, "inspect", lambda _path: observation)
    assert adapter.mount(inventory.candidates[0]) is observation
    assert [c for c in calls if c[1] == "mount"] == [["diskutil", "mount", "disk4s2"]]


def test_mount_rejects_post_mount_observation_for_another_device(
    native: NativeFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, _, _, _, _ = native
    candidate = adapter.discover_unmounted().candidates[0]
    monkeypatch.setattr(
        adapter, "inspect", lambda _path: _observation("other", "disk-other")
    )
    with pytest.raises(StorageMountError):
        adapter.mount(candidate)


def test_empty_inventory_is_complete(native: NativeFixture) -> None:
    adapter, layout, _, hardware, _, _ = native
    layout["AllDisksAndPartitions"] = []
    hardware.clear()
    result = adapter.discover_unmounted()
    assert not result.issues
    assert not result.observed_devices


def test_named_unmounted_volume_is_a_candidate(native: NativeFixture) -> None:
    adapter, layout, _, _, _, _ = native
    layout["AllDisksAndPartitions"][0]["Partitions"][0]["VolumeName"] = "IPOD"
    assert len(adapter.discover_unmounted().candidates) == 1


def test_already_mounted_partition_is_not_a_candidate(native: NativeFixture) -> None:
    adapter, _, _, _, _, failure = native
    failure["mounted"] = True
    assert not adapter.discover_unmounted().candidates
