# ADR-0177: Recoverable Track removal in Classic Drop

- Status: Accepted, 2026-10-29
- Supersedes: the append-only restriction in ADR-0175 for explicit Classic Drop Track removal only

## Context

Classic Drop's confirmed product scope includes removing selected Music Tracks from
an iPod Classic Library and restoring the most recent Library change. ADR-0175
made Classic Drop append-only. Upstream Library Drafts can remove Tracks, but the
ordinary save path permanently removes omitted media after the transaction commits.
That behavior does not satisfy the confirmed recoverable-removal requirement.

## Decision

Classic Drop may remove explicitly selected Music Tracks from the current Library.
Podcast, Audiobook, Video, and other non-Music media remain outside this action.
Removing a Track also removes every occurrence from every Playlist.

The operation uses `LibraryWorkspace.remove_tracks`, a revision-bound
`LibraryPreparationRequest` with `delete_omissions=True`, and one Storage
Transaction. The request selects device-side recovery. Original database and media
files remain in the transaction's device recovery area; the operation does not use
Host Recovery and does not permanently delete recovery data. Shared media still
referenced by a retained Track remains in place.

Classic Drop stores the returned transaction path and operation kind in its local
history database. Restore uses Storage's observed transaction and identity checks,
then restores and finalizes the transaction. Import and another removal are blocked
after a removal until that removal has been restored. Consecutive imports remain
allowed and individually recoverable. Recovery data therefore continues to occupy
iPod capacity until restore. The removal confirmation reports the selected Tracks,
unique unshared media size retained for recovery, and affected Playlists.

Only Classic Drop opts into this behavior. Other iOpenPod Library saves keep their
existing recovery and permanent-cleanup policies. If a commit result is uncertain,
the application must retain its recovery path and must not report that removal was
completed.

## Consequences

- Removal is recoverable across application restarts while the local operation
  history and original iPod remain available.
- A removal must be restored before another import or removal; consecutive imports
  remain individually recoverable.
- The removal workspace provides title, artist, album, genre, year, and Playlist
  filters; dimensions combine with AND, and selected values within genre, year, and
  Playlist combine with OR. Its accumulated package is session-only and bound to
  the Active iPod, Library Snapshot, and retained database fingerprint.
- This decision does not claim power-loss atomicity beyond Storage's journal and
  verified transaction guarantees.
