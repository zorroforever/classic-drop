"""Invalid semantic payloads finish their own request without killing transport."""

import io
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from classic_drop.native_helper import HelperServer
from classic_drop.native_protocol import MAX_MESSAGE
from classic_drop.playlist_protocol import smart_to_dto
from iPodDB.library.playlists import (
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
)


def run_helper(tmp_path: Path, lines: tuple[bytes, ...]) -> list[dict[str, Any]]:
    output = io.StringIO()
    server = HelperServer(output, tmp_path / "host")
    server.run(
        io.BytesIO(
            b"\n".join(lines) + b'\n{"version":1,"id":"close","command":"close"}\n'
        )
    )
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_invalid_smart_value_returns_correlated_error_and_next_request_works(
    tmp_path: Path,
) -> None:
    smart = asdict(
        smart_to_dto(
            SmartPlaylist(
                SmartRuleGroup(
                    rules=(SmartRule(SmartField.RATING, SmartOperator.GREATER_THAN, 0),)
                )
            )
        )
    )
    smart["rules"]["rules"][0]["value"]["value"] = -1
    invalid = json.dumps(
        {
            "version": 1,
            "id": "invalid-rating",
            "command": "playlist_preview",
            "smart": smart,
        }
    ).encode()
    messages = run_helper(
        tmp_path, (invalid, b'{"version":1,"id":"next","command":"hello"}')
    )
    error = next(message for message in messages if message["event"] == "error")
    assert error["id"] == "invalid-rating" and error["code"] == "invalid_request"
    assert "outside the supported range" in error["detail"]
    assert (
        next(message for message in messages if message["id"] == "next")["event"]
        == "result"
    )


@pytest.mark.parametrize("bad_id", [123, "", "x" * 16385, "\ud800"])
def test_invalid_envelope_id_is_never_echoed(tmp_path: Path, bad_id: object) -> None:
    invalid = json.dumps(
        {"version": 1, "id": bad_id, "command": "playlist_preview", "smart": {}}
    ).encode()
    messages = run_helper(tmp_path, (invalid,))
    error = next(message for message in messages if message["event"] == "error")
    assert error["id"] == "" and error["code"] == "invalid_request"


@pytest.mark.parametrize(
    "line",
    [
        b'{"version":2,"id":"wrong-version","command":"playlist_preview","smart":{}}',
        b'{"version":true,"id":"bool-version","command":"playlist_preview","smart":{}}',
        b'{"id":"partial"',
        b"x" * (MAX_MESSAGE + 1),
    ],
)
def test_invalid_frame_or_protocol_keeps_uncorrelated_error(
    tmp_path: Path, line: bytes
) -> None:
    messages = run_helper(tmp_path, (line,))
    error = next(message for message in messages if message["event"] == "error")
    assert error["id"] == "" and error["code"] == "invalid_request"


def test_invalid_payload_cannot_finish_an_existing_request_identity(
    tmp_path: Path,
) -> None:
    messages = run_helper(
        tmp_path,
        (
            b'{"version":1,"id":"shared","command":"hello"}',
            b'{"version":1,"id":"shared","command":"playlist_preview","smart":{}}',
        ),
    )
    shared = [message for message in messages if message["id"] == "shared"]
    assert len(shared) == 1 and shared[0]["event"] == "result"
    assert (
        next(message for message in messages if message["event"] == "error")["id"] == ""
    )


def test_rejected_semantic_request_identity_is_consumed_once(tmp_path: Path) -> None:
    messages = run_helper(
        tmp_path,
        (
            b'{"version":1,"id":"rejected","command":"playlist_preview","smart":{}}',
            b'{"version":1,"id":"rejected","command":"hello"}',
            b'{"version":1,"id":"fresh","command":"hello"}',
        ),
    )
    rejected = [message for message in messages if message["id"] == "rejected"]
    assert len(rejected) == 1 and rejected[0]["code"] == "invalid_request"
    assert (
        next(message for message in messages if message["id"] == "fresh")["event"]
        == "result"
    )
