"""Typed Playlist presentation and strict recursive JSON input boundaries."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from typing import cast

from classic_drop.playlists import PlaylistAction, PlaylistEdit, PlaylistSession
from iPodDB.library import LibrarySnapshot, Playlist
from iPodDB.library.playlists import (
    PlaylistKind,
    PlaylistSortOrder,
    SmartField,
    SmartLimitSort,
    SmartLimitUnit,
    SmartLocation,
    SmartMatch,
    SmartMediaKind,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistLimit,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    SmartRuleValue,
    UnsupportedSmartRule,
)
from iPodDB.library.smart_rules import (
    SmartValueKind,
    smart_operators,
    smart_value_kind,
    validate_smart_playlist,
)

MAX_CONFIGURATION_BYTES = 1024 * 1024


def _require_transportable(raw: object) -> None:
    encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_CONFIGURATION_BYTES:
        raise ValueError("The complete Smart Playlist configuration exceeds 1 MiB.")


@dataclass(frozen=True, slots=True)
class SmartValueDTO:
    kind: str
    value: str | int


@dataclass(frozen=True, slots=True)
class SmartRuleDTO:
    field: str
    operator: str
    value: SmartValueDTO
    upper_value: SmartValueDTO | None = None
    kind: str = dataclass_field(default="rule", init=False)


@dataclass(frozen=True, slots=True)
class UnsupportedRuleDTO:
    description: str
    kind: str = dataclass_field(default="unsupported", init=False)


@dataclass(frozen=True, slots=True)
class SmartGroupDTO:
    match: str
    rules: tuple[SmartRuleDTO | SmartGroupDTO | UnsupportedRuleDTO, ...]
    kind: str = dataclass_field(default="group", init=False)


@dataclass(frozen=True, slots=True)
class SmartLimitDTO:
    value: int
    unit: str
    sort: str
    descending: bool


@dataclass(frozen=True, slots=True)
class SmartPlaylistDTO:
    rules: SmartGroupDTO
    live_update: bool
    match_rules: bool
    checked_only: bool
    limit: SmartLimitDTO | None
    editable: bool
    supported: bool
    support_reason: str


def _value_dto(value: SmartRuleValue, value_kind: SmartValueKind) -> SmartValueDTO:
    if isinstance(value, SmartPlaylistReference):
        return SmartValueDTO(value_kind.value, str(value.playlist_id))
    return SmartValueDTO(value_kind.value, value)


def _group_dto(group: SmartRuleGroup, depth: int, budget: list[int]) -> SmartGroupDTO:
    if depth > 64:
        raise ValueError("Smart Playlist rule nesting exceeds 64 levels.")
    rules: list[SmartRuleDTO | SmartGroupDTO | UnsupportedRuleDTO] = []
    for rule in group.rules:
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("Smart Playlist rules exceed the transport limit.")
        if isinstance(rule, SmartRuleGroup):
            rules.append(_group_dto(rule, depth + 1, budget))
        elif isinstance(rule, UnsupportedSmartRule):
            rules.append(UnsupportedRuleDTO(rule.description))
        else:
            kind = smart_value_kind(rule.field)
            rules.append(
                SmartRuleDTO(
                    rule.field.value,
                    rule.operator.value,
                    _value_dto(rule.value, kind),
                    None
                    if rule.upper_value is None
                    else _value_dto(rule.upper_value, kind),
                )
            )
    return SmartGroupDTO(group.match.value, tuple(rules))


def smart_to_dto(smart: SmartPlaylist) -> SmartPlaylistDTO:
    """Expose unsupported configurations for display, never for lossy replacement."""
    reason = ""
    try:
        validate_smart_playlist(smart)
    except ValueError as error:
        reason = str(error)
    limit = smart.limit
    dto = SmartPlaylistDTO(
        _group_dto(smart.rules, 0, [10_000]),
        smart.live_update,
        smart.match_rules,
        smart.checked_only,
        None
        if limit is None
        else SmartLimitDTO(
            limit.value, limit.unit.value, limit.sort.value, limit.descending
        ),
        smart.editable,
        not reason,
        reason,
    )
    _require_transportable(asdict(dto))
    return dto


def _object(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or any(type(key) is not str for key in raw):
        raise ValueError("Expected a JSON object.")
    return cast("dict[str, object]", raw)


def _keys(
    raw: dict[str, object], required: set[str], optional: set[str] | None = None
) -> None:
    if not required <= raw.keys() or raw.keys() - required - (optional or set()):
        raise ValueError("Missing or unknown Playlist field.")


def _text(raw: object, *, maximum_chars: int = 16384) -> str:
    if not isinstance(raw, str) or len(raw) > maximum_chars:
        raise ValueError("Expected bounded Playlist text.")
    try:
        raw.encode("utf-16-be")
    except UnicodeEncodeError:
        raise ValueError("Playlist text contains invalid Unicode.") from None
    if "\0" in raw:
        raise ValueError("Playlist text contains a null character.")
    return raw


def _integer(raw: object) -> int:
    if type(raw) is not int:
        raise ValueError("Expected a whole number.")
    return raw


def _boolean(raw: object) -> bool:
    if type(raw) is not bool:
        raise ValueError("Expected a boolean.")
    return raw


def domain_id(raw: object) -> int:
    """Canonical decimal strings prevent JSON number precision loss for opaque IDs."""
    if not isinstance(raw, str) or re.fullmatch(r"-?[1-9][0-9]{0,19}", raw) is None:
        raise ValueError("Expected a nonzero decimal-string Library identity.")
    value = int(raw)
    if not -(1 << 63) <= value <= (1 << 64) - 1:
        raise ValueError("Library identity is out of range.")
    return value


def _rule_value(raw: object, smart_field: SmartField) -> SmartRuleValue:
    value = _object(raw)
    _keys(value, {"kind", "value"})
    kind = smart_value_kind(smart_field)
    if value["kind"] != kind.value:
        raise ValueError("Smart rule value has the wrong type.")
    item = value["value"]
    if kind is SmartValueKind.PLAYLIST:
        return SmartPlaylistReference(domain_id(item))
    if kind is SmartValueKind.CHOICE:
        text = _text(item)
        return (
            SmartMediaKind(text)
            if smart_field is SmartField.MEDIA_KIND
            else SmartLocation(text)
        )
    if kind is SmartValueKind.TEXT:
        # Rule payloads are bounded by the complete configuration, not label size.
        return _text(item, maximum_chars=MAX_CONFIGURATION_BYTES)
    return _integer(item)


def _group_from_json(raw: object, depth: int, budget: list[int]) -> SmartRuleGroup:
    if depth > 64:
        raise ValueError("Smart Playlist rule nesting exceeds 64 levels.")
    group = _object(raw)
    _keys(group, {"kind", "match", "rules"})
    if group["kind"] != "group" or not isinstance(group["rules"], list):
        raise ValueError("Expected a recursive Smart Playlist rule group.")
    match = SmartMatch(_text(group["match"]))
    rules: list[SmartRule | SmartRuleGroup] = []
    for raw_rule in group["rules"]:
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("Smart Playlist rules exceed the transport limit.")
        rule = _object(raw_rule)
        if rule.get("kind") == "group":
            rules.append(_group_from_json(rule, depth + 1, budget))
        else:
            _keys(rule, {"kind", "field", "operator", "value", "upper_value"})
            if rule["kind"] != "rule":
                raise ValueError("Unsupported Smart Playlist rules cannot be replaced.")
            smart_field = SmartField(_text(rule["field"]))
            operator = SmartOperator(_text(rule["operator"]))
            upper = rule["upper_value"]
            rules.append(
                SmartRule(
                    smart_field,
                    operator,
                    _rule_value(rule["value"], smart_field),
                    None if upper is None else _rule_value(upper, smart_field),
                )
            )
    return SmartRuleGroup(match, tuple(rules))


def smart_from_json(raw: object) -> SmartPlaylist:
    """Decode authorable rules only, with one shared semantic validation pass."""
    value = _object(raw)
    _keys(
        value,
        {"rules", "live_update", "match_rules", "checked_only", "limit", "editable"},
        {"supported", "support_reason"},
    )
    if not _boolean(value["editable"]) or not _boolean(value.get("supported", True)):
        raise ValueError("Unsupported Smart Playlist configurations are read-only.")
    if "support_reason" in value:
        _text(value["support_reason"])
    raw_limit = value["limit"]
    limit = None
    if raw_limit is not None:
        limited = _object(raw_limit)
        _keys(limited, {"value", "unit", "sort", "descending"})
        limit = SmartPlaylistLimit(
            _integer(limited["value"]),
            SmartLimitUnit(_text(limited["unit"])),
            SmartLimitSort(_text(limited["sort"])),
            _boolean(limited["descending"]),
        )
    smart = SmartPlaylist(
        _group_from_json(value["rules"], 0, [10_000]),
        _boolean(value["live_update"]),
        _boolean(value["match_rules"]),
        _boolean(value["checked_only"]),
        limit,
    )
    validate_smart_playlist(smart)
    _require_transportable(value)
    return smart


def _sequence(raw: object) -> list[object]:
    if not isinstance(raw, list) or len(raw) > 20_000:
        raise ValueError("Expected a bounded Playlist selection.")
    return raw


def edit_from_json(raw: object) -> PlaylistEdit:
    value = _object(raw)
    _keys(value, {"action"}, set(PlaylistEdit.__dataclass_fields__) - {"action"})
    return PlaylistEdit(
        action=PlaylistAction(_text(value["action"])),
        playlist_id=None
        if value.get("playlist_id") is None
        else domain_id(value["playlist_id"]),
        name=None if value.get("name") is None else _text(value["name"]),
        parent_id=None
        if value.get("parent_id") is None
        else domain_id(value["parent_id"]),
        kind=PlaylistKind(_text(value.get("kind", "playlist"))),
        entry_ids=tuple(_text(v) for v in _sequence(value.get("entry_ids", []))),
        track_ids=tuple(domain_id(v) for v in _sequence(value.get("track_ids", []))),
        sort_order=None
        if value.get("sort_order") is None
        else PlaylistSortOrder(_integer(value["sort_order"])),
        smart=None if value.get("smart") is None else smart_from_json(value["smart"]),
        description=None
        if value.get("description") is None
        else _text(value["description"]),
        allow_repeat=_boolean(value.get("allow_repeat", False)),
    )


@dataclass(frozen=True, slots=True)
class SmartChoiceDTO:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class SmartFieldDTO:
    field: str
    value_kind: str
    operators: tuple[str, ...]
    choices: tuple[SmartChoiceDTO, ...] = ()


def smart_field_descriptors(
    playlists: tuple[Playlist, ...] = (),
) -> tuple[SmartFieldDTO, ...]:
    descriptors = []
    for smart_field in SmartField:
        choices: tuple[SmartChoiceDTO, ...] = ()
        if smart_field is SmartField.PLAYLIST:
            choices = tuple(
                SmartChoiceDTO(str(p.playlist_id), p.name) for p in playlists
            )
        elif smart_field is SmartField.MEDIA_KIND:
            choices = tuple(SmartChoiceDTO(k.value, k.value) for k in SmartMediaKind)
        elif smart_field is SmartField.LOCATION:
            choices = tuple(SmartChoiceDTO(k.value, k.value) for k in SmartLocation)
        descriptors.append(
            SmartFieldDTO(
                smart_field.value,
                smart_value_kind(smart_field).value,
                tuple(op.value for op in smart_operators(smart_field)),
                choices,
            )
        )
    return tuple(descriptors)


@dataclass(frozen=True, slots=True)
class PlaylistTrackDTO:
    id: str
    title: str
    artist: str
    album: str
    album_artist: str
    length_ms: int
    artwork_id: str


@dataclass(frozen=True, slots=True)
class PlaylistEntryDTO:
    entry_id: str
    track_id: str
    position: int | None
    index: int
    missing_reference: bool
    track: PlaylistTrackDTO | None


def playlist_entries_dto(
    snapshot: LibrarySnapshot, playlist_id: int
) -> tuple[PlaylistEntryDTO, ...]:
    playlist = next(
        (p for p in snapshot.playlists if p.playlist_id == playlist_id), None
    )
    if playlist is None:
        raise ValueError("This Playlist is no longer in the Library.")
    tracks = {t.track_id: t for t in snapshot.tracks}
    result = []
    for index, entry in enumerate(playlist.entries):
        track = tracks.get(entry.track_id)
        result.append(
            PlaylistEntryDTO(
                entry.entry_id,
                str(entry.track_id),
                entry.position,
                index,
                track is None,
                None
                if track is None
                else PlaylistTrackDTO(
                    str(track.track_id),
                    track.title,
                    track.artist,
                    track.album,
                    track.album_artist,
                    track.length_ms,
                    str(track.artwork_id),
                ),
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PlaylistSummaryDTO:
    id: str
    parent_id: str | None
    kind: str
    name: str
    description: str
    path: tuple[str, ...]
    sort_order: int
    sort_supported: bool
    editable: bool
    protected: bool
    dirty: bool
    can_edit_entries: bool
    can_edit_rules: bool
    entry_count: int
    track_count: int
    duration_ms: int
    missing_entry_count: int
    smart: SmartPlaylistDTO | None


def playlist_summaries(session: PlaylistSession) -> tuple[PlaylistSummaryDTO, ...]:
    snapshot = session.snapshot
    originals = {p.playlist_id: p for p in session.original_snapshot.playlists}
    current = {p.playlist_id: p for p in snapshot.playlists}
    tracks = {t.track_id: t for t in snapshot.tracks}
    summaries = []
    for playlist in snapshot.playlists:
        ancestors = [playlist.name]
        seen = {playlist.playlist_id}
        parent_id = playlist.parent_id
        while parent_id is not None and parent_id in current and parent_id not in seen:
            seen.add(parent_id)
            parent = current[parent_id]
            ancestors.append(parent.name)
            parent_id = parent.parent_id
        entries = playlist.entries
        if playlist.kind is PlaylistKind.FOLDER:
            ids = {
                i
                for child in session.deletion_impact(playlist.playlist_id)
                if child.kind is not PlaylistKind.FOLDER
                for i in child.track_ids
            }
            track_ids = tuple(ids)
        else:
            track_ids = playlist.track_ids
        smart = None if playlist.smart is None else smart_to_dto(playlist.smart)
        summaries.append(
            PlaylistSummaryDTO(
                str(playlist.playlist_id),
                None if playlist.parent_id is None else str(playlist.parent_id),
                playlist.kind.value,
                playlist.name,
                playlist.description,
                tuple(reversed(ancestors)),
                playlist.sort_order.value,
                isinstance(playlist.sort_order, PlaylistSortOrder),
                not playlist.system_managed,
                playlist.system_managed,
                originals.get(playlist.playlist_id) != playlist,
                not playlist.system_managed and playlist.kind is PlaylistKind.PLAYLIST,
                not playlist.system_managed and smart is not None and smart.supported,
                len(track_ids)
                if playlist.kind is PlaylistKind.FOLDER
                else len(entries),
                len(set(track_ids)),
                sum(tracks[i].length_ms for i in track_ids if i in tracks),
                sum(i not in tracks for i in track_ids),
                smart,
            )
        )
    return tuple(summaries)


@dataclass(frozen=True, slots=True)
class PlaylistDraftDTO:
    revision: str
    dirty: bool
    can_undo: bool
    can_redo: bool
    locked: bool
    changed_ids: tuple[str, ...]
    deleted_ids: tuple[str, ...]


def playlist_draft_dto(session: PlaylistSession) -> PlaylistDraftDTO:
    original = {p.playlist_id: p for p in session.original_snapshot.playlists}
    current = {p.playlist_id: p for p in session.snapshot.playlists}
    return PlaylistDraftDTO(
        session.revision,
        session.dirty,
        session.can_undo,
        session.can_redo,
        session.locked,
        tuple(str(i) for i, p in current.items() if original.get(i) != p),
        tuple(str(i) for i in original if i not in current),
    )
