"""Exact external-disk inventory and non-forced macOS mounting."""

from __future__ import annotations

import plistlib
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from storage.errors import StorageMountError
from storage.models import (
    DeviceBus,
    DiscoveryIssue,
    HardwareIdentifiers,
    PhysicalDevice,
    PhysicalDeviceId,
    UnmountedVolumeCandidate,
    UnmountedVolumeDiscoveryResult,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from storage.models import VolumeObservation
    from storage.platform.macos import MacOSPlatformAdapter

_FILESYSTEM_CONTENTS = {
    "apple_apfs",
    "apple_hfs",
    "apple_hfsx",
    "dos_fat_12",
    "dos_fat_16",
    "dos_fat_32",
    "linux_filesystem",
    "windows_ntfs",
}


@dataclass(frozen=True, slots=True)
class MountTarget:
    """Adapter-private identity snapshot; never accepted from callers."""

    partition: str
    partition_identity: str
    volume_identity: str
    physical_device: PhysicalDevice


def discover_unmounted(adapter: MacOSPlatformAdapter) -> UnmountedVolumeDiscoveryResult:
    result, targets = _inventory()
    adapter._mount_candidates = targets
    return result


def _inventory() -> tuple[UnmountedVolumeDiscoveryResult, dict[str, MountTarget]]:
    """Retain every observed disk, including disks whose enrichment failed."""

    from storage.platform import macos

    issues: list[DiscoveryIssue] = []
    devices: list[PhysicalDevice] = []
    candidates: list[UnmountedVolumeCandidate] = []
    targets: dict[str, MountTarget] = {}
    try:
        payload = _dict(
            _plist_command(["diskutil", "list", "-plist", "external", "physical"])
        )
        disks = payload.get("AllDisksAndPartitions")
        if not isinstance(disks, list):
            raise StorageMountError("diskutil returned an invalid external disk list")
        hardware = macos._ioreg_hardware_index() if disks else {}
        for raw_disk in disks:
            issue_source = "macos.diskutil"
            try:
                disk = _dict(raw_disk)
                disk_id = _text(disk, "DeviceIdentifier")
                if not _whole_disk(disk_id):
                    raise StorageMountError("External disk identity was incomplete")
                issue_source = disk_id
                # The external physical inventory establishes this identity even
                # when a following info/correlation request fails.
                devices.append(_physical_device(disk_id, {}, hardware))
                info = _info(disk_id)
                if _text(info, "DeviceIdentifier") != disk_id:
                    raise StorageMountError(
                        "External disk identity changed during inventory"
                    )
                physical = _physical_device(disk_id, info, hardware)
                devices[-1] = physical
                if disk_id not in hardware:
                    issues.append(
                        DiscoveryIssue(disk_id, "USB device correlation is incomplete")
                    )
                    continue
                partitions = disk.get("Partitions", [])
                if not isinstance(partitions, list):
                    raise StorageMountError("Partition list was malformed")
                filesystem_partitions: list[dict[str, object]] = []
                for raw_partition in partitions:
                    partition = _dict(raw_partition)
                    identifier = _text(partition, "DeviceIdentifier")
                    if not _partition_of(identifier, disk_id):
                        raise StorageMountError("Partition identity was invalid")
                    if _text(partition, "Content").casefold() in _FILESYSTEM_CONTENTS:
                        filesystem_partitions.append(partition)
                if len(filesystem_partitions) > 1:
                    raise StorageMountError(
                        "Multiple filesystem partitions are ambiguous"
                    )
                if not filesystem_partitions:
                    continue
                partition = filesystem_partitions[0]
                identifier = _text(partition, "DeviceIdentifier")
                partition_info = _info(identifier)
                if (
                    _text(partition_info, "DeviceIdentifier") != identifier
                    or _text(partition_info, "ParentWholeDisk") != disk_id
                ):
                    raise StorageMountError(
                        "Partition identity changed during inventory"
                    )
                if _text(partition_info, "MountPoint"):
                    continue
                identity = _partition_identity(partition_info)
                listed_identity = _partition_identity(partition)
                if listed_identity and listed_identity != identity:
                    raise StorageMountError(
                        "The partition identity changed during inventory"
                    )
                if not identity:
                    raise StorageMountError(
                        "The partition has no stable Volume identity"
                    )
                candidate_id = uuid.uuid4().hex
                candidates.append(UnmountedVolumeCandidate(candidate_id, physical))
                targets[candidate_id] = MountTarget(
                    identifier, identity, _volume_identity(partition_info), physical
                )
            except (StorageMountError, OSError, ValueError) as error:
                issues.append(DiscoveryIssue(issue_source, str(error)))
    except (StorageMountError, OSError, ValueError) as error:
        issues.append(DiscoveryIssue("macos.diskutil", str(error)))
    return UnmountedVolumeDiscoveryResult(
        tuple(candidates), tuple(devices), tuple(issues)
    ), targets


def mount(
    adapter: MacOSPlatformAdapter, candidate: UnmountedVolumeCandidate
) -> VolumeObservation:
    """Consume a current token, revalidate it, mount exactly, then reinspect."""

    try:
        target = adapter._mount_candidates.pop(candidate.candidate_id, None)
        if target is None or target.physical_device != candidate.physical_device:
            raise StorageMountError("The unmounted Volume candidate is stale")
        discovery, current_targets = _inventory()
        target_disk = target.physical_device.id.value.removeprefix("macos:")
        blocking_issues = tuple(
            issue
            for issue in discovery.issues
            if issue.source in {target_disk, "macos.diskutil"}
        )
        if blocking_issues or target not in current_targets.values():
            raise StorageMountError(
                "The unmounted Volume candidate is stale or ambiguous"
            )
        completed = _run(["diskutil", "mount", target.partition])
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).decode(
                "utf-8", errors="replace"
            )
            raise StorageMountError(
                detail.strip() or "diskutil could not mount the Volume"
            )
        info = _info(target.partition)
        if (
            _text(info, "DeviceIdentifier") != target.partition
            or _text(info, "ParentWholeDisk")
            != target.physical_device.id.value.removeprefix("macos:")
            or _partition_identity(info) != target.partition_identity
            or _volume_identity(info) != target.volume_identity
        ):
            raise StorageMountError("The mounted partition identity changed")
        mount_point = _text(info, "MountPoint")
        if not mount_point or not Path(mount_point).is_absolute():
            raise StorageMountError("diskutil did not confirm a mounted Volume")
        observation = adapter.inspect(Path(mount_point))
        if observation.physical_device.id != target.physical_device.id:
            raise StorageMountError(
                "The mounted observation belongs to a different Physical Device"
            )
        observed_volume_identity = observation.volume.id.value.removeprefix("macos:")
        if observed_volume_identity != target.volume_identity:
            raise StorageMountError(
                "The mounted observation belongs to a different Volume"
            )
        return observation
    except StorageMountError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise StorageMountError(
            str(error) or "Could not mount the external Volume"
        ) from error


def _physical_device(
    disk_id: str, info: dict[str, object], hardware: Mapping[str, HardwareIdentifiers]
) -> PhysicalDevice:
    identifiers = hardware.get(disk_id, HardwareIdentifiers())
    bus = (
        DeviceBus.USB
        if disk_id in hardware or _text(info, "BusProtocol").casefold() == "usb"
        else DeviceBus.UNKNOWN
    )
    return PhysicalDevice(
        PhysicalDeviceId(f"macos:{disk_id}"),
        _text(info, "MediaName") or disk_id,
        bus,
        True,  # The caller enumerates external physical disks exclusively.
        identifiers,
    )


def _partition_identity(info: dict[str, object]) -> str:
    return _text(info, "DiskUUID") or _text(info, "VolumeUUID")


def _volume_identity(info: dict[str, object]) -> str:
    return _text(info, "VolumeUUID") or _text(info, "DiskUUID")


def _info(identifier: str) -> dict[str, object]:
    return _dict(_plist_command(["diskutil", "info", "-plist", identifier]))


def _plist_command(command: list[str]) -> object:
    completed = _run(command)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).decode(
            "utf-8", errors="replace"
        )
        raise StorageMountError(detail.strip() or "diskutil command failed")
    try:
        return plistlib.loads(completed.stdout)
    except (plistlib.InvalidFileException, TypeError, ValueError) as error:
        raise StorageMountError(f"Could not parse diskutil plist: {error}") from error


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(command, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StorageMountError(str(error) or "diskutil command timed out") from error


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise StorageMountError("diskutil returned an unexpected plist structure")
    return cast("dict[str, object]", value)


def _text(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    return item.strip() if isinstance(item, str) else ""


def _whole_disk(identifier: str) -> bool:
    return bool(identifier.startswith("disk") and identifier[4:].isdigit())


def _partition_of(partition: str, disk: str) -> bool:
    suffix = partition.removeprefix(disk).removeprefix("s")
    return partition.startswith(f"{disk}s") and suffix.isdigit()
