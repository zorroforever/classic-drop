# ADR-0178: Use SwiftUI with a headless Classic Drop helper

- Status: Accepted by the user, 2026-10-29
- Supersedes: ADR-0176's frontend choice and ADR-0175's Qt worker model for the native build
- Preserves: ADR-0175 import constraints and ADR-0177 removal and recovery rules

## Context

The user approved a native SwiftUI shell after reviewing light/dark workspaces,
an album grid and album detail designs. Adding music already performs substantial
Host work, but the Qt shell's small progress bar and missing media callback made
that preparation difficult to see.

## Decision

Build the macOS shell in SwiftUI and AppKit. Keep the existing Python engine,
Device Coordinator, iPodDB, Device Registry and Storage implementations. The native
shell never writes device files. Keep the Qt entry as a behavioral reference during
migration; the native build has its own explicitly launched application bundle.

One bundled headless helper owns the engine, SQLite history, preparation resources,
Active iPod, Library Snapshot and Library Reviews. A serial worker executes engine
commands. A separate input reader handles cancellation and shutdown while that
worker is busy. The helper creates no Qt application or GUI event loop; retained
engine imports still require QtCore/Gui/Network/Multimedia libraries.

Use versioned JSON Lines over Foundation Process/Pipe, without a shell or network
service. Requests and replies have typed DTOs, request IDs, generation tokens and
ordered events. Domain identifiers use decimal strings. Control messages are
bounded to 1 MiB, query pages to 200 items, thumbnails to 512 KiB. Fetch covers on
demand. Preparation resources and partial tokens publish only on batch completion.

Python remains authoritative for preview tokens, edits, duplicate overrides,
removal packages, immutable paged Reviews and write eligibility. The frontend
flushes version-bound edits before explicit import. Removal confirmation submits
the saved Review token. A changed Active iPod invalidates earlier generations,
preview edits, package and Review tokens. No write is automatically retried after
helper loss; an interrupted write has an unknown result until recovery is checked.

The window provides the four workspaces, album grid/detail, native Track tables,
collapsible inspector and a persistent task area. Progress describes actual
enumeration, file inspection, measured transcoding, source revalidation and
upstream write stages. Stage completion never implies transaction success. Unknown
totals remain indeterminate. Transport failure requests cancellation at safe
checkpoints and does not throw through a Storage publication progress callback.

Keep macOS 12.3 as the deployment target. Guard macOS 26 Liquid Glass APIs and
use standard materials on older systems. Follow system appearance/accessibility.
Ship English, Simplified Chinese and Japanese resources; changing language does
not restart the helper or clear edits. Migrate the existing Host language setting.

The native app embeds a PyInstaller-built helper application, Python runtime and
existing dependencies. Preserve `local.classicdrop.app` and Host data locations.
The native shell uses a glass-inspired version of the Classic Drop icon, retaining
its player and drop motif. FFmpeg/FFprobe remain externally installed as before. No dependency,
CI, release channel, minimum-OS, playback or permanent-deletion policy changes.

## Consequences

Swift and Python now require paired protocol tests and separate build steps. Native
and retained Qt frontends must never manage the same device concurrently. The
first native bundle is an opt-in development build with local ad-hoc signatures,
not a notarized release. Intel, older macOS, macOS 27 materials, VoiceOver and
physical iPod playback/recovery require separate acceptance evidence.

See [native build and verification](../classic-drop-native.md).
