# ADR-0186: Manage Classic Drop Playlist drafts through reviewed saves

- Status: Accepted by the user, 2026-10-31
- Extends: ADR-0022, ADR-0026, ADR-0035, ADR-0142, and ADR-0178
- Amends: ADR-0175's append-only scope for explicit Playlist edits
- Preserves: ADR-0177 and ADR-0181 Track removal and recovery boundaries

## Context

The native Classic Drop browser previously exposed Playlist names only as Track
removal filters. The user approved management of ordinary Playlists, Smart
Playlists, and Playlist Folders, with reversible edits and one explicit reviewed
save. Music import also needs explicit Playlist destinations.

The shared Library Workspace, semantic rule descriptions, evaluator, and iPodDB
writer already model these operations. Duplicating that knowledge in Swift would
lose occurrence identities, imported rule data, and dataset reconciliation.

## Decision

The headless helper owns a source-bound Playlist session over the shared Library
Workspace. Swift displays typed, bounded pages and sends semantic edits with the
current device generation and independent Playlist revision. Each validated user
action changes the draft atomically and supports undo/redo. Undo never revives an
old revision or reuses a previously allocated temporary identity.

Ordinary Playlists retain ordered Entry identities, including repeated Tracks.
Removing an Entry removes only that occurrence. Folders contain Playlists and
other folders; deleting a folder reviews its descendant closure and preserves
Library Tracks. System-managed Playlists remain protected. Missing or ambiguous
hierarchy and Smart rule dependencies block unsafe edits rather than guessing.

Smart rule fields and operators come from the shared semantic descriptions.
Supported recursive rules can be previewed without editing, then applied with
their matching saved membership. Explicit evaluation and Live updating follow
ADR-0035 and ADR-0142. Unsupported imported rules and saved members remain
retained; safe renames, moves, and ordinary copies do not rewrite those rules.

Classic Drop uses manual Review and Save for these drafts independently of the
main iOpenPod application's autosave setting. Check captures fresh firmware
sidecars through Storage and projects them into an isolated source. It overlays
only source-bound semantic edits, rejecting conflicting changes or identity
collisions. Check neither adopts this source nor writes device bytes. Sidecar
statistics, On-The-Go Playlists, and supported Smart membership refreshes appear
in the reviewed candidate.

Only the exact issued Review may save. Source database fingerprints, sidecar
contents and inventory, device connection, draft revision, queue choices, and
Host sources are validated again. A changed source expires the Review; a failed
attempt cannot be replayed by restoring old evidence. Save publishes the fixed
candidate and captured sidecar consumption through one verified Storage
Transaction. Accepting Review does not evaluate Smart rules again.

Playlist omission authorizes Playlist deletion only. Existing Track identities,
metadata, media and artwork remain retained apart from reviewed playback evidence
derived from captured sidecars. Playlist-only writes reject retained media or
artwork replacement. Import adds only explicitly selected music and can append it
to selected ordinary Playlists or one new ordinary Playlist in a chosen folder.
Smart Playlists and folders cannot be manual Track destinations. Reusing existing
music requires a selected current Track and verified matching content; names or
stale import receipts never authorize reuse.

Playlist-only Save does not import the queue. It retains Host editing intent and
the explicit original-ALAC batch policy, expires source-bound preparation tokens,
and remaps temporary destinations only through verified output identities. Missing
or invalid mappings require reselection. Repreparing the retained intent is an
explicit operation against the new source.

Successful saves retain recovery data and record a distinct `playlist` operation
or a combined `import` operation. Restore covers the entire operation, in reverse
chronological order, and never crosses an accepted removal baseline. A pending or
uncertain transaction and an unaccepted latest Track removal block further writes.
Saving Playlists never authorizes Track deletion, permanent cleanup, or replay
after helper loss.

Native views use system navigation, tables, sheets, and inspector containers.
Liquid Glass APIs are guarded by macOS 26 availability, with standard controls on
older supported systems. English, Simplified Chinese, and Japanese presentation
does not translate user data or native rule bytes.

## Consequences

There is one authoritative draft and one reviewed publication path; Swift never
packs database bytes or writes device files. This adds no dependency or standalone
package. Virtual-device and native protocol tests establish software behavior;
physical firmware presentation, Smart rule execution, eject/reconnect, and recovery
still require separate hardware acceptance. Recovery retention is independent of
Backup Snapshots and is not a multi-file power-loss atomicity guarantee.
