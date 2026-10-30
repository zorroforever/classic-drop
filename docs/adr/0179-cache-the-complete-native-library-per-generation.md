# ADR-0179: Cache the complete native Library per generation

- Status: Accepted by the user, 2026-10-30
- Extends: ADR-0178

## Decision

Keep the approved SwiftUI and Liquid Glass shell. Prepare a full Track metadata
index from the retained Library Snapshot on a cancellable pure-metadata thread.
Keep all engine and Storage access serial. Automatically fetch complete bounded
Track and Album pages, report actual indexing/transfer progress, then filter the
native cache locally. Shrink pages without truncating metadata and reject oversized
single records explicitly.

Search all searchable Track/TrackMetadata values. Preserve Track-ID selection
across searches, list/grid changes and Album navigation. Adding to the removal
package uses only selected Music Tracks; deletion still requires the established
Review and recoverable Storage workflow. Clear caches and selections on disconnect
or device switch and rebuild after reconnect; stale preparation and page replies
cannot publish into a new generation.

Artwork has view-owned demand, two physical in-flight requests and an entry-bounded
cache. Leaving a view drops its unsent demand. Keep old physical slots occupied until
their replies arrive, while rejecting their content after generation changes.

## Consequences

Complete metadata needs memory proportional to Library size. Loading once trades
startup time for local search and navigation. Covers remain lazy and device-bound.
Synthetic tests cannot establish real iPod disk speed or firmware behavior.
