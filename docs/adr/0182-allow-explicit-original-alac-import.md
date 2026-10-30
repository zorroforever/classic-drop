# ADR-0182: Allow explicitly selected original ALAC import

- Status: Accepted scope from the user, 2026-10-31
- Extends: ADR-0175 and ADR-0178

## Decision

The native import workspace offers **Import ALAC without conversion**, initially
off for each application launch. When enabled, true ALAC in an MP4 container may
retain its source bit depth and sample rate instead of following conservative
compatibility conversion. Other codecs retain their existing preparation policy.
Device Registry capabilities are unchanged; this is explicit import policy rather
than a new hardware-support claim.

The option is captured during preparation and bound to the retained preview. A
nonempty preview cannot change policy; clear it and add the sources again.
Preparation/import and a populated queue disable the native switch. Device changes
and helper loss reset the native option. Old clients omit the protocol boolean and
retain conservative behavior. The shared MusicImporter defaults to that behavior.

Original ALAC still requires a supported ALAC Device Profile, a valid container,
one mono/stereo audio stream, no motion video, a positive duration/sample rate and
known ALAC precision. Validation failure on an opted-in ALAC produces an error;
it does not silently convert that file. Source fingerprints, duplicate review,
identity-bound device access, staged Storage writes and recovery are unchanged.
The committed media bytes match the original source, including embedded tags;
reviewed metadata changes continue to affect Library fields as before.

The legacy MHIT sample-rate field is unsigned 16.16 and cannot represent 96 kHz.
Writers and verification use the existing shared saturating field converter while
the floating-point companion records the actual rate. Projection uses that
companion only when the legacy field is saturated and the companion is a positive
integral rate above 65535 Hz, within the exact integer range of float32. Other
retained disagreements keep the previous projection and unchanged bytes.

## Consequences

Real encoded-file and virtual-volume tests cover 24-bit / 96 and 192 kHz original
ALAC, conservative conversion with the option off, unrelated formats, queue policy
binding, strict protocol typing and byte-preserving commit/round-trip. These checks
do not establish playback support or the database representation preferred by
Apple software for every firmware. Hardware playback is tested by the user; this
option does not revise general compatibility limits.
