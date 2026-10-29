# ADR-0176: Use a native Qt workspace shell for Classic Drop

- Status: Accepted
- Date: 2026-10-29
- Extends: ADR-0009 and ADR-0175

## Context

The user requested implementation of the macOS UI phase in the published
Classic Drop design. Its exploratory window used a fixed light palette and
forced Fusion style. The design also describes future duplicate review and
recoverable deletion, whose workflows are not implemented in this phase.

## Decision

Keep PySide6 Widgets and the native Host style, window chrome and toolbar.
Classic Drop owns a source-list sidebar, workspace stack and collapsible
inspector. The first workspaces are the read-only iPod Library, import queue
and recovery entry supported by the existing worker. Device selection and
safe removal stay in the sidebar; actual progress and cancellation stay in
a separate action bar across workspaces.

Extract shell, Library view, import view and shared presentation widgets into
Classic Drop modules. Keep device and transaction coordination in the existing
window/worker/engine contracts. Presentation never gains direct device I/O.

Use system semantic palette roles and point-sized fonts with Qt logical
geometry. Use opaque surfaces as the initial fallback on macOS 12.3 and later;
this does not change the upstream iOpenPod design language or introduce a
new AppKit dependency. Do not claim Liquid Glass or native material fidelity
from stylesheet approximations or headless widget renders.

## Consequences

Workspace, inspector and locale changes retain in-memory queue edits and
do not submit device operations. At 940×580 the inspector defaults closed;
the user may reopen it while the action bar remains accessible. Library
sorting binds rows to Tracks, keeping search and inspection consistent.

Recovery is limited to the capability reported by the worker, without an
invented history or unimplemented deletion controls. Duplicate review and
recoverable deletion remain separate future increments under their own
workflow decisions.

Headless tests and renders verify state and layout. Native macOS materials,
VoiceOver, Retina, system accessibility settings, older macOS and physical
iPod behavior require separate platform acceptance evidence.
