# ADR-0180: Automatically mount qualified macOS iPod Classics

- Status: Accepted
- Date: 2026-10-30

## Context

Classic Drop previously saw an iPod only after Finder mounted its Volume. macOS
can enumerate external physical disks and unmounted partitions, but generic
Storage must not infer iPod identity or mount ambiguous media.

## Decision

Storage exposes generic, short-lived inventories of external Physical Devices
and opaque unmounted Volume candidates. The macOS adapter correlates current
IOKit USB evidence, accepts exactly one filesystem partition, revalidates whole
disk and partition identities, invokes `diskutil mount` for that partition
without force or elevation, and verifies a fresh mounted observation. Linux and
Windows report the capability as unavailable.

DeviceCoordinator qualifies current evidence through Device Registry. Only
normal-mode candidates whose possible profiles are all iPod Classic may be
mounted. Discovery remains read-only, selection remains explicit, and automatic
mounting does not write databases or import media.

The native Classic Drop shell discovers at startup and polls every five seconds
when idle or preparing the metadata index, with at most one discovery request
pending. Failed and successfully ejected Physical Devices remain
suppressed until a complete inventory confirms absence and a later inventory
observes them again. Manual Refresh retries failed mounts but does not undo
successful-eject suppression. Incomplete inventories never clear suppression.

## Consequences

Finder is no longer required for the supported reconnect workflow. Native
enumeration, stale-candidate rejection, and post-mount verification are part of
Storage's safety contract. Mount failures remain visible while other devices
continue through discovery.
