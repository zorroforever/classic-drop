# ADR-0185: Cache native artwork on the Host

- Status: Accepted
- Date: 2026-10-31

## Context

The native Library retained at most 128 decoded covers and loaded only visible
artwork. Larger Libraries evicted earlier covers, and searching or changing views
could reread the iPod. Relaunching discarded all thumbnails. Memory-only prefetch
would repeat those reads and increase memory pressure.

## Decision

Preserve visible-first demand loading and add a disposable Host disk thumbnail
cache. When the complete metadata index is ready, queue all distinct Library
artwork IDs, including Track covers outside Album representatives. Speculation
uses at most one outstanding load and yields to visible demand. Total outstanding
artwork loads remain bounded at two. The existing serialized engine worker and
identity-bound Storage reads remain authoritative for device access.

Persist validated thumbnails of at most 320 by 320 pixels and 512 KiB each in the
macOS user cache directory. A dedicated Swift actor performs Host filesystem IO
and image validation outside the UI actor. Atomic replacements and a 512 MiB total
disk budget keep this cache disposable and bounded. Remove oldest entries first;
retain a separate bounded decoded memory cache for presentation.

Namespace keys hash the Volume identity, Library and ArtworkDB SHA-256
fingerprints, thumbnail size and schema version. Connection generations remain
the authority for current requests; they are not persistent cache identities.
Disconnects, device changes and Library invalidation discard pending work and
reject stale callbacks. Foreground workflows pause speculative reads. Cache
failures fall back to normal reads without blocking workflows.

## Consequences

Unchanged Libraries reuse covers across launches without device thumbnail reads.
The first fill still performs device reads and may keep an iPod active until it
finishes. No iPod files are changed. Decoded memory stays bounded independently
of the disk cache; a Library larger than the disk budget may require later reads.

The namespace does not detect external thumbnail shard edits that leave both
database fingerprints unchanged. This cache supplies presentation only; it never
authorizes a device mutation or replaces Storage verification. No dependencies
or audio-header scanning are added.
