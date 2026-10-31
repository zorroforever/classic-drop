# ADR-0183: Preserve ambiguous historical composer identities

- Status: Accepted
- Date: 2026-10-31

## Context

Retained iPod databases can assign several native composer IDs to the same
case-insensitive composer name. Composer IDs have no separate browse dataset.
Requiring a unique historical ID blocked otherwise valid imports and composer
edits with `library.ambiguous_composer`, including converted audio imports.

## Decision

Unchanged Tracks retain their native composer IDs. A new or renamed composer
reuses a single retained candidate when one exists. When the name has several
historical candidates, preparation allocates a fresh collision-free ID instead
of choosing an arbitrary historical identity or renumbering existing Tracks.
Affected Tracks with the same case-insensitive name share the new ID within that
preparation. Empty names still receive zero; older layouts keep composer text
without inventing a native field.

Independent verification requires a fresh ID when retained candidates are
ambiguous. It continues to check untouched references, ownership, collisions and
consistent identities among affected Tracks. Preparation returns verified bytes;
the application still publishes only through the existing Storage workflow.

## Consequences

Import no longer requires consolidation of historical composer IDs. Future
preparations may allocate another ID while multiple historical candidates remain;
this deliberately avoids introducing an unsupported canonical identity. No audio
conversion, retained metadata or device compatibility policy changes.

Public Library tests cover import, rename, unique-candidate reuse, unchanged source
bytes and rejection of corrupted identities. Host-only preparation using a captured
database supplements those tests without performing a physical device write.
