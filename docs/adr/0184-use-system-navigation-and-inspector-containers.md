# ADR-0184: Use system navigation and Inspector containers

- Status: Accepted
- Date: 2026-10-31

## Context

The native shell used a manually assembled three-pane `HSplitView`, a trailing
Inspector with a custom translucent background, an inline Library search field,
and a custom material card around task progress. The Library grid and dense Track
Tables are domain content and already use SwiftUI controls; their visual layout
does not need to become glass.

## Decision

- Use SwiftUI `NavigationSplitView` for the sidebar and workspace columns on
  macOS 13 and newer.
- Use the system `.inspector(isPresented:)` column on macOS 14 and newer. Keep the
  existing visibility preference and hide it outside Library/Incoming and while
  an Album detail is open.
- Keep a manually composed Inspector within `NavigationSplitView` on macOS 13 and
  retain the `HSplitView` fallback on macOS 12.3. Do not raise the deployment floor.
- Use native toolbar search for Library, Forms for Inspector and Recovery details,
  and `GroupBox` for active task details and progress.
- Preserve album-grid presentation, Tables, workspace actions, import editing,
  and explicit removal/recovery workflows. Keep content backgrounds appropriate
  to readable data; do not apply Liquid Glass to the whole content area.

## Consequences

Navigation and Inspector appearance, spacing, and collapse behavior follow the
installed macOS version and system accessibility settings. The older compatibility
layouts remain necessary while macOS 12.3 is supported. Changes to domain content
must preserve its existing selection and workflow semantics independently of the
system-owned containers.

See [the native shell guide](../classic-drop-native.md).
