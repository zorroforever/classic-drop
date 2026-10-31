"""Strict JSON boundaries retain typed rules and exact Playlist occurrences."""

import json
from dataclasses import asdict, replace

import pytest

from classic_drop import playlist_protocol as wire
from classic_drop.playlists import PlaylistSession
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistEntry, Track
from iPodDB.library.playlists import (
    PlaylistKind,
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
    UnsupportedSmartRule,
)
from iPodDB.library.smart_rules import smart_operators, smart_value_kind


def supported() -> SmartPlaylist:
    return SmartPlaylist(
        rules=SmartRuleGroup(
            SmartMatch.ANY,
            (
                SmartRule(SmartField.TITLE, SmartOperator.CONTAINS, "abc"),
                SmartRuleGroup(
                    SmartMatch.ALL,
                    (
                        SmartRule(
                            SmartField.PLAYLIST,
                            SmartOperator.IS,
                            SmartPlaylistReference(9007199254740993),
                        ),
                        SmartRule(
                            SmartField.MEDIA_KIND,
                            SmartOperator.IS,
                            SmartMediaKind.MUSIC,
                        ),
                        SmartRule(
                            SmartField.LOCATION,
                            SmartOperator.IS_NOT,
                            SmartLocation.CLOUD,
                        ),
                        SmartRule(SmartField.RATING, SmartOperator.BETWEEN, 60, 100),
                        SmartRule(SmartField.CHECKED, SmartOperator.IS_TRUE, 0),
                        SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 86400),
                    ),
                ),
            ),
        ),
        live_update=False,
        checked_only=True,
        limit=SmartPlaylistLimit(
            50, SmartLimitUnit.TRACKS, SmartLimitSort.RATING, True
        ),
    )


def payload() -> dict[str, object]:
    return json.loads(json.dumps(asdict(wire.smart_to_dto(supported()))))  # type: ignore[no-any-return]


def test_recursive_smart_json_round_trip_preserves_types_and_large_domain_ids() -> None:
    raw = payload()
    assert wire.smart_from_json(raw) == supported()
    encoded = json.dumps(raw)
    assert '"9007199254740993"' in encoded
    assert '"playlist"' in encoded


@pytest.mark.parametrize(
    "path,value",
    [
        (("live_update",), 1),
        (("editable",), False),
        (("extra",), True),
        (("rules", "match"), "none"),
        (("rules", "rules", 0, "operator"), "greater_than"),
        (("rules", "rules", 0, "value", "value"), 8),
        (("rules", "rules", 1, "rules", 0, "value", "value"), 9007199254740993),
        (("rules", "rules", 1, "rules", 0, "value", "value"), "01"),
        (("rules", "rules", 1, "rules", 1, "value", "value"), "unknown"),
        (("rules", "rules", 1, "rules", 3, "value", "value"), True),
        (("rules", "rules", 1, "rules", 3, "upper_value", "value"), 50),
        (("limit", "value"), 0),
        (("limit", "descending"), 1),
    ],
)
def test_smart_decode_rejects_malformed_or_lossy_inputs(
    path: tuple[str | int, ...], value: object
) -> None:
    raw = payload()
    target = raw
    for component in path[:-1]:
        target = target[component]  # type: ignore[index,assignment]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(ValueError):
        wire.smart_from_json(raw)


def test_unsupported_configuration_is_displayed_but_cannot_be_submitted() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(rules=(UnsupportedSmartRule("native rule"),)),
        editable=False,
    )
    dto = wire.smart_to_dto(smart)
    assert not dto.supported and not dto.editable
    assert dto.support_reason
    assert asdict(dto)["rules"]["rules"][0]["description"] == "native rule"
    with pytest.raises(ValueError):
        wire.smart_from_json(asdict(dto))


def test_descriptors_use_shared_capabilities_and_typed_choice_values() -> None:
    descriptors = wire.smart_field_descriptors((Playlist(123, "Named"),))
    assert {d.field for d in descriptors} == {f.value for f in SmartField}
    for descriptor in descriptors:
        field = SmartField(descriptor.field)
        assert descriptor.value_kind == smart_value_kind(field).value
        assert descriptor.operators == tuple(op.value for op in smart_operators(field))
    fields = {d.field: d for d in descriptors}
    assert fields["playlist"].choices[0].value == "123"
    assert {c.value for c in fields["location"].choices} == {"local", "cloud"}
    assert {c.value for c in fields["media_kind"].choices} == {
        k.value for k in SmartMediaKind
    }


def test_entries_preserve_repeated_occurrences_and_missing_references() -> None:
    source = LibrarySnapshot(
        tracks=(Track(1, "Title", "Artist", "Album", 3000),),
        playlists=(
            Playlist(
                10,
                "Saved",
                entries=(
                    PlaylistEntry("first", 1, 7),
                    PlaylistEntry("second", 1, 8),
                    PlaylistEntry("missing", 99),
                ),
            ),
        ),
    )
    entries = wire.playlist_entries_dto(source, 10)
    assert tuple(e.entry_id for e in entries) == ("first", "second", "missing")
    assert tuple(e.track_id for e in entries) == ("1", "1", "99")
    assert entries[0].position == 7 and entries[1].index == 1
    assert entries[0].track is not None and entries[0].track.title == "Title"
    assert entries[2].missing_reference and entries[2].track is None


def test_summary_and_draft_report_protected_dirty_and_saved_configuration() -> None:
    original = LibrarySnapshot(
        playlists=(
            Playlist(10, "Original"),
            Playlist(20, "Protected", system_managed=True),
        )
    )
    session = PlaylistSession(original)
    edit = wire.edit_from_json(
        {"action": "update", "playlist_id": "10", "name": "Changed"}
    )
    session.edit(edit, expected_revision=session.revision)
    summaries = wire.playlist_summaries(session)
    assert summaries[0].id == "10" and summaries[0].dirty and summaries[0].editable
    assert summaries[1].protected and not summaries[1].editable
    status = wire.playlist_draft_dto(session)
    assert status.dirty and status.can_undo and status.revision == session.revision
    assert status.changed_ids == ("10",)
    smart = replace(
        original,
        playlists=(Playlist(30, "Smart", kind=PlaylistKind.SMART, smart=supported()),),
    )
    summary = wire.playlist_summaries(PlaylistSession(smart))[0]
    assert summary.smart is not None and summary.smart.supported


@pytest.mark.parametrize(
    "raw",
    [
        {"action": "update", "playlist_id": 10},
        {"action": "update", "playlist_id": "0"},
        {"action": "update", "playlist_id": "+10"},
        {"action": "update", "playlist_id": "1.0"},
        {"action": "create", "system_managed": True},
        {"action": "create", "kind": "regular"},
        {"action": "append", "track_ids": [True]},
        {"action": "append", "allow_repeat": 1},
        {"action": "reorder_entries", "entry_ids": [1]},
        {"action": "update", "sort_order": True},
    ],
)
def test_edit_decode_rejects_untyped_ids_and_unknown_system_state(raw: object) -> None:
    with pytest.raises(ValueError):
        wire.edit_from_json(raw)


def test_edit_decode_keeps_opaque_entry_ids_and_negative_draft_ids() -> None:
    edit = wire.edit_from_json(
        {
            "action": "append",
            "playlist_id": "-12",
            "track_ids": ["9007199254740993"],
            "allow_repeat": True,
        }
    )
    assert (
        edit.playlist_id == -12
        and edit.track_ids == (9007199254740993,)
        and edit.allow_repeat
    )
    edit = wire.edit_from_json(
        {"action": "remove_entries", "playlist_id": "10", "entry_ids": ["opaque/a:2"]}
    )
    assert edit.entry_ids == ("opaque/a:2",)


def test_complete_oversize_smart_configuration_is_rejected_without_truncation() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=tuple(
                SmartRule(SmartField.TITLE, SmartOperator.IS, "x" * 16000)
                for _ in range(70)
            )
        )
    )
    with pytest.raises(ValueError, match="1 MiB"):
        wire.smart_to_dto(smart)


def test_configuration_limit_counts_actual_native_utf8_encoding() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=tuple(
                SmartRule(SmartField.TITLE, SmartOperator.IS, "曲" * 15000)
                for _ in range(20)
            )
        )
    )
    dto = wire.smart_to_dto(smart)
    raw = json.loads(json.dumps(asdict(dto), ensure_ascii=False))
    assert wire.smart_from_json(raw) == smart


def test_oversize_rule_input_is_rejected_as_one_complete_configuration() -> None:
    raw = payload()
    raw["rules"] = {
        "kind": "group",
        "match": "all",
        "rules": [
            {
                "kind": "rule",
                "field": "title",
                "operator": "is",
                "value": {"kind": "text", "value": "x" * 16000},
                "upper_value": None,
            }
            for _ in range(70)
        ],
    }
    with pytest.raises(ValueError, match="1 MiB"):
        wire.smart_from_json(raw)
