# ADR-0181: Accept a completed Classic Drop removal as the current baseline

- Status: Accepted, 2026-10-31
- Supersedes: ADR-0177's mandatory restore before subsequent writes

## Context

ADR-0177 blocks further imports and removals until the last removal is restored.
This prevents users from keeping a successful removal and continuing. A changed
unchanged dependency, such as firmware Preferences, can also correctly prevent
restoration, leaving a completed removal blocking all subsequent work.

## Decision

Classic Drop offers an explicit confirmed choice to keep the current Library after
a completed removal. It validates the selected device, current Library fingerprint,
expected latest local removal record, and identity-bound committed transaction
state through a read-only Storage session. Interrupted or uncertain operations
cannot use this action. Storage's restoration preconditions remain unchanged.

Acceptance atomically marks the removal and earlier outstanding operations for
that device as kept in Host history, distinct from restored. Automatic restore
must never cross this accepted baseline. Other devices' history is unchanged.
The action clears non-authoritative receipts for that device. It does not modify
iPod databases, media, transaction journals, or retained recovery payloads, and it
does not delete history rows. The current removal package and Library generation
remain available. A subsequent removal still requires a new Review and confirmation.

## Consequences

- Users can keep a completed removal and continue importing or removing music.
- Kept operations and earlier operations stop appearing as automatic Restore
  choices, including after restart. The confirmation explains this consequence.
- Retained recovery files still occupy iPod capacity. Manual recovery and recovery
  cleanup remain separate work; this action does not promise either workflow.
- Failed validation or Host history persistence leaves further writes blocked.
- This decision applies to Classic Drop's completed recoverable removals only;
  other iOpenPod recovery policies remain unchanged.
