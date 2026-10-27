# ADR-0175: Classic Drop for stock-firmware iPod Classic on macOS

- Status: Accepted by the user, 2026-10-25
- Upstream: iOpenPod 16fee285049ba66da067dc9ebf04eb146a1ba537

Classic Drop is a focused GPL-3.0-or-later macOS frontend over the retained
iOpenPod application, iPodDB, Device Registry and Storage implementations.
It adds music to an existing Apple-firmware Classic library. A1238 and the
capacity of replacement solid-state storage are not exact Device Identity.
The identified Device Profile and retained databases determine write behavior.
Rockbox, mirrored deletion, video, podcasts and streaming services are excluded.

The new package is `src/classic_drop`. Upstream code and its branding assets
remain intact; Classic Drop gets its own entry point and build spec.
Python stays pinned to 3.12 and the existing UV lock provides dependencies.

Device discovery and initial selection are read-only: disable metadata,
volume-presentation, playback-sidecar reconciliation and missing-library
initialization. Admit only exactly identified iPod Classic profiles with an
existing readable library. Report unreadable artwork instead of rebuilding it.

Selected paths expand recursively without following symlinks. Inspect only that
batch. Compatible audio is copied without transcoding; incompatible audio uses
the upstream verified media preparer, with lossless ALAC preferred for lossless
sources. Reject non-audio inputs. Tag and cover extraction is content-bound.
Embedded front covers take precedence over folder covers and an optional user
replacement. Preview permits correcting title, artist, album, album artist,
disc and track numbers. Duplicate content in one batch is skipped. Local import
receipts recognize previous imports only while their device destinations still
match the current library. Metadata-only matches are suggestions, not proof.

All device writes stay in upstream Storage. Commit reconciles pending playback
history, adds selected songs through LibraryWorkspace, prepares one reviewed
LibraryPreparationRequest with delete_omissions=False and saves one transaction.
Reject any removal or overwrite of retained music. Store recovery originals on
the Host, retain the successful transaction and expose restore explicitly.
Preparation failure never publishes the append draft. Cancel and source/device
changes use upstream preconditions. Do not claim multi-file power-loss atomicity.

Qt runs filesystem/media work on one persistent worker thread, with queued UI
signals. Closing cancels and waits for the worker; a device is ejected only by
an explicit command. The first usable screen is a compact device selector and
an import table with artwork preview, progress and file/folder controls.

Acceptance requires tests using actual media and virtual Classic volumes:
read-only selection; preserving old audio, metadata, artwork and playlists;
multiple thumbnail readbacks and HASH58 verification; repeat import; changed
sources; cancellation; restore; FLAC conversion and Unicode tags. Headless Qt
smoke tests and a native macOS launch/build check complement these tests.
Physical SSD-modified A1238 playback and cover validation remain a separate
hardware check, never inferred from simulated filesystem success.
