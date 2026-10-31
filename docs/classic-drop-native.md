# Classic Drop native shell

The native build implements the approved SwiftUI layout: an album grid and detail
page, Track list, editable import preview, removal filters/package/Review, recovery,
collapsible inspector and a task area shared by all workspaces. Navigation uses
`NavigationSplitView` on macOS 13 and newer and the system Inspector on macOS 14
and newer. macOS 12 retains the split-view compatibility layout; macOS 13 keeps an
Inspector column inside the system split view. The Library search uses the native
search toolbar. Track/import details and recovery use Forms; task progress uses a
system GroupBox. The album grid and dense Library/removal Tables remain content
views. The retained Qt entry remains available for comparison. Do not run both
against one iPod.

## Playlists

Playlist management follows [ADR-0186](adr/0186-manage-classic-drop-playlist-drafts.md).
The native sidebar provides ordinary Playlists, Smart Playlists and folders.
Edits stay in a helper-owned draft until **Review Changes** and **Save to iPod**.
Removing a Playlist Entry or deleting a Playlist preserves Library music.
Deleting a folder includes its descendants; Smart rule dependencies must be
resolved first. Undo/redo and Discard affect the draft only.

**Add Tracks** retains selections across searches. Select individual songs or all
current results, search again, and add the accumulated selection once. The count
includes hidden selections; **Clear Selection** clears the entire selection.

Table headers apply temporary sorting. **Save Current Sort as Playlist Order**
records the complete ordinary Playlist order and Manual sort in one undoable edit.
Manual dragging and movement require the complete list, no search filter, and no
temporary sort. Smart Playlists expose their saved presentation sort separately
from the rule limit's selection order.

Smart previews leave the draft unchanged. Applying supported rules saves their
matching members to the draft; unsupported imported rules remain read-only and
retained. Automatic updating refreshes supported membership in the final reviewed
candidate, rather than running a background service. Rule references read the same
input draft's saved membership.

Smart preview progress and cancellation remain available inside the rule editor.
Invalid rule input returns a correlated validation error and leaves the draft
unchanged so the user can correct it and retry.

Imports can target the Library alone, existing ordinary Playlists, or one new
ordinary Playlist in a selected folder. Review can combine selected imports with
Playlist edits. Saving Playlists alone leaves queued music unimported and requires
fresh source preparation afterward while preserving Host editing intentions and
the batch's original-ALAC choice. Temporary destinations continue only through
verified saved ID mappings. Saving or restoring never falls back to a same-name
Playlist. Recovery restores the complete save, including its combined import.

Check reads and projects current playback sidecars without writing the iPod.
Changes after Review require another Check. Disconnect or helper loss invalidates
draft/Review authority; an interrupted save is never replayed automatically.

## Build

Requirements: macOS, Apple's Swift toolchain with the macOS 26 SDK, UV and the
repository's locked Python 3.12 environment. Xcode is needed for XCTest; ordinary
app compilation can use the Command Line Tools. No third-party Swift packages
are used.

```shell
uv sync --locked
uv run python scripts/build_classic_drop_native.py
open "dist/native/Classic Drop.app"
```

The build refuses to overwrite an existing bundle. Use `--output` with a fresh
path for another build. `--skip-helper-build` reuses the helper in
`build/native-helper-dist/ClassicDropHelper.app`; use it only when Python source
has not changed. The nested helper/runtime and main application receive local
ad-hoc signatures. This does not create a signed/notarized release.

The app carries its own Python runtime; users do not need Python or UV. FFmpeg and
FFprobe retain the existing external-tool policy. Host history, recovery and logs
remain in `~/Library/Application Support/Classic Drop`. Existing `settings.ini`
language preferences migrate on first native launch. Native language changes are
saved independently and do not clear the in-memory queue.

For source debugging, without an application bundle:

```shell
CLASSIC_DROP_PYTHON="$PWD/.venv/bin/python" swift run --package-path native/ClassicDrop ClassicDrop
```

`CLASSIC_DROP_DATA_DIRECTORY` can isolate Host history/settings for development.
`CLASSIC_DROP_HELPER` selects a development helper executable when there is no
bundled helper. The distributed app always prefers its bundled helper. Never use
synthetic history or fixtures with a physical iPod.

## Protocol and workflow

Protocol version 1 uses stdin/stdout JSON Lines; diagnostics use stderr and
`classic-drop-native.log`. There is no network listener. IDs are strings to retain
64-bit precision. Frames are at most 1 MiB; pages at most 200 entries; PNG
thumbnails at most 512 KiB. Browse commands return one generation-bound page.
Removal Review pages additionally require the retained Review token.

`hello`, `discover`, `select`, `validate`, `eject`, `prepare_browser`, `tracks`, `albums`, `facets`,
`artwork`, `audio_formats`, `preview`, `queue`, `edit`, `preview_artwork`, `cover`, `clear_cover`,
`discard`, `commit`, `filter`, `package`, `package_add`, `package_remove`,
`package_clear`, `prepare_delete`, `review`, `delete`, `restore`, `keep`, `cancel` and
`close` form the native adapter's command surface. The engine and Storage retain
all write preconditions. A UI enabled button is never write authority.

Adding prepares music on the Host. Explicit import submits the complete preview
token set after acknowledged edits; it does not silently import a partial batch.
Failed or canceled preparation preserves the prior queue. Confirmed/suspected
duplicates need explicit override. Removal keeps original files for restoration
and blocks another write until restored or explicitly kept as the current baseline
(ADR-0177 and ADR-0181). Keeping a completed removal changes Host history only;
the iPod's databases, recovery journals and retained files are unchanged. Earlier
changes stop being offered for automatic restore across that baseline. Interrupted
operations still require recovery, and Storage's restore checks remain strict.

The helper has one serial engine worker and an independent control reader. Cancel
requests reach a long operation without waiting for queued browse/cover work.
Shutdown cancels pending work and waits for cleanup. Pipe failure cannot raise
through a noncancellable Storage publication; cancellation takes effect at its
normal safe checkpoints. The native shell never replays an interrupted write.

## Verification and limits

```shell
uv run pytest tests/classic_drop tests/test_classic_drop_native_packaging.py
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path native/ClassicDrop
codesign --verify --deep --strict "dist/native/Classic Drop.app"
```

Virtual-volume tests cover import preservation, preview/review generations,
duplicate authorization, removal Review ordering, restore, cancellation and
transport failure. Swift tests cover Unicode framing, bounded input, lossless
IDs, progress state, edit flushing and artwork reloads. Bundle assembly and the
headless packaged helper can be checked without a connected device.

The deployment target is macOS 12.3; newer material APIs are availability-guarded.
Compilation for that target does not establish runtime compatibility on every
older system. The development Host is Apple Silicon macOS 26.5.2. macOS 27
materials, Intel, older-system runtime, VoiceOver, accessibility display options
and physical iPod playback/cover/recovery remain acceptance checks. Synthetic
library screenshots and virtual device writes do not establish hardware success.

## Complete native Library cache

Selecting an Active iPod prepares a generation-bound index of all retained Track
metadata on a cancellable, pure-metadata thread. The engine worker remains available
for passive disconnect discovery. Swift automatically transfers all Track and Album
pages with progress before enabling Library actions, then searches the retained
in-memory metadata locally. Search includes composer, genre, show, dates, lyrics
and other searchable Track/TrackMetadata fields; it does not read media files.
Pages shrink to fit the bounded transport without truncating search data. A single
record exceeding the transport allowance reports an incomplete cache rather than
publishing partial results as complete.

Track-ID selection is shared by the list and Album details and survives search,
view changes and returning to the Album grid. The selection count includes hidden
rows. Add to removal package accepts the Music subset in bounded batches;
it does not delete files. Disconnect, device switch, canceled preparation and helper
loss invalidate the cache and selection. A reconnected device builds a fresh cache.
Visible artwork demand takes priority, with at most two outstanding loads and a
128-image decoded cache. Once metadata is ready, idle time fills the Host thumbnail
cache for every distinct Library artwork ID, one speculative request at a time.
Hidden pending demand is dropped; the independent prefetch queue can still cache it.

Clicking an Album card explicitly replaces the Track selection with all Music
Tracks in that Album, including Tracks hidden by the current search. Double-click
to open its Track list and select individual rows when only part of the Album
should be removed. Choose **Add to removal package**, then open **To Remove** and
check the accumulated package. **Remove from package** only edits this list.
Choose **Review removal…** to inspect the complete Track list, affected Playlists
and recovery size, then explicitly confirm **Remove recoverably** to change the
iPod Library. Original media remains on the iPod for recovery, so this operation
does not immediately free capacity. In **Recovery & History**, restore the removal
or choose **Keep Current Result and Continue** before another import or removal.
Keeping preserves the current removal package; another removal still requires
Review and explicit confirmation. Retained recovery files continue to occupy space.

On macOS, discovery can mount a filesystem volume positively qualified as an iPod
through Storage. Failures are suppressed until physical reconnect or manual
refresh; explicit ejection suppresses automatic remount until physical reconnect.
See ADR-0179 and ADR-0180. The retained Qt application is a separate entry; launch
this native bundle explicitly when testing the Liquid Glass interface.

## Actual audio format display

Audio format reading starts **off on each launch**. Enable **Read audio formats**
in the top-right **More** menu when needed. While off, browsing does not inspect
audio headers, unloaded table cells show “—”, and Album summaries are hidden.
Turning it off drops unsent reads and cancels an outstanding read at safe
checkpoints; a late reply cannot restart scanning. Previously cached values remain
available within the current Library generation.

The Track list and Album detail table show codec, bit depth and sample rate.
Album cards summarize all members of the Album, including members hidden by search;
different values are listed separately. A partially observed Album shows a loading
label, and unreadable members remain explicitly unknown. AAC and MP3 bit depth is
not applicable and displays “—”; MP4 sample-size placeholders are not treated as
lossless precision.

While enabled, visible rows and Album summaries request actual encoded headers on demand through
identity-bound Playback Sources. The serial engine worker handles at most eight
unique Track IDs per request, with one physical format request outstanding in the
native shell. Each file has a 1 MiB read budget, 64 KiB maximum physical reads and
an operation limit; large media payloads and metadata padding are skipped. Results,
including unreadable files, are cached only for the current Library generation.
Leaving a view drops unsent work; stale replies cannot populate a new generation.
The pure metadata index does not read media files.

Artwork is loaded on demand first, then remaining Library covers are cached in the
background. The Host stores validated 320-pixel thumbnails under the macOS user
cache directory (`ClassicDrop/Artwork-v1`), with a 512 MiB total budget and oldest
entries removed first. Up to 128 decoded images stay in memory; switching views
or evicting an image can reload the Host thumbnail without rereading the iPod.
Background fills do not evict visible decoded covers just to retain hidden covers.

Cache namespaces combine the Volume identity, iTunesDB/ArtworkDB fingerprints,
thumbnail size and schema version, so unchanged Libraries reuse thumbnails after
relaunch. Changing either database produces a new namespace. Thumbnail shard edits
made externally without changing either database are not detected by this key.
Corrupt or unavailable Host cache files are treated as misses. Host IO and payload
validation run outside the UI actor. Background device reads pause for foreground
work; disconnects and Library generation changes discard the old queue and late
results. First-time uncached covers still require device reads, and Libraries
larger than the disk budget cannot remain fully cached. See ADR-0185.

Artwork and audio-header requests share the serial engine worker; leaving audio
reading off avoids that extra device work while browsing covers.

This display observes existing files, including high-resolution ALAC, without
applying import compatibility rules. It neither changes import/transcoding policy
nor establishes what a particular iPod firmware can play.

## Original ALAC import option

Before adding files, open **To Import** and enable **Import ALAC without conversion**
to retain ALAC source bytes, bit depth and sample rate. The switch starts off on
each launch. Off retains the existing compatibility rules, including conversion of
higher-resolution lossless input to 16-bit / 44.1 kHz ALAC. Other formats follow
their existing rules in both modes. Playback support is confirmed on the iPod.

The option is fixed for the prepared queue and locked while preparing/importing.
To change it, clear the queue and add the original source files again. Files already
imported are unaffected. Invalid or unsupported ALAC inputs fail rather than being
silently converted when original import is selected. The protocol field
`allow_high_resolution_alac` is a strict boolean on `preview`, defaulting to false;
commit uses the retained prepared result. See ADR-0182.
