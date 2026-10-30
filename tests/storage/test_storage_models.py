"""Unmounted inventory grants no filesystem authority."""

from dataclasses import fields

import pytest

from storage import DeviceBus, DiscoveryIssue, PhysicalDevice, PhysicalDeviceId, models
from storage.platform.linux import LinuxPlatformAdapter
from storage.platform.windows import WindowsPlatformAdapter


def test_unmounted_candidate_contains_generic_device_identity_only() -> None:
    device = PhysicalDevice(PhysicalDeviceId("test"), "External", DeviceBus.USB, True)
    candidate = models.UnmountedVolumeCandidate("opaque", device)
    assert {field.name for field in fields(candidate)} == {
        "candidate_id",
        "physical_device",
    }
    assert candidate.physical_device.id.value == "test"


def test_unmounted_inventory_reports_all_devices_and_enumeration_issues() -> None:
    device = PhysicalDevice(PhysicalDeviceId("test"), "External", DeviceBus.USB, True)
    result = models.UnmountedVolumeDiscoveryResult(
        (), (device,), (DiscoveryIssue("inventory", "incomplete"),)
    )
    assert result.candidates == ()
    assert len(result.observed_devices) == 1
    assert result.issues[0].detail == "incomplete"


@pytest.mark.parametrize("adapter_type", (LinuxPlatformAdapter, WindowsPlatformAdapter))
def test_non_macos_adapters_report_unmounted_discovery_unavailable(
    adapter_type: type[LinuxPlatformAdapter] | type[WindowsPlatformAdapter],
) -> None:
    adapter = object.__new__(adapter_type)
    result = adapter.discover_unmounted()
    assert result.candidates == ()
    assert result.issues
