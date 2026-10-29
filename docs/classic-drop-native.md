# Classic Drop native shell

The native build implements the approved SwiftUI layout: an album grid and detail
page, Track list, editable import preview, removal filters/package/Review, recovery,
collapsible inspector and a task area shared by all workspaces. The retained Qt
entry remains available for comparison. Do not run both against one iPod.

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

`hello`, `discover`, `select`, `validate`, `eject`, `tracks`, `albums`, `facets`,
`artwork`, `preview`, `queue`, `edit`, `preview_artwork`, `cover`, `clear_cover`,
`discard`, `commit`, `filter`, `package`, `package_add`, `package_remove`,
`package_clear`, `prepare_delete`, `review`, `delete`, `restore`, `cancel` and
`close` form the native adapter's command surface. The engine and Storage retain
all write preconditions. A UI enabled button is never write authority.

Adding prepares music on the Host. Explicit import submits the complete preview
token set after acknowledged edits; it does not silently import a partial batch.
Failed or canceled preparation preserves the prior queue. Confirmed/suspected
duplicates need explicit override. Removal keeps original files for restoration
and blocks another write until restored, as required by ADR-0177.

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
