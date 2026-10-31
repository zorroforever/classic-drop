import XCTest
@testable import ClassicDropCore

final class PlaylistProtocolTests: XCTestCase {
    func testRecursiveSmartRulesPreserveDecimalPlaylistIdentity() throws {
        let json = #"{"rules":{"kind":"group","match":"all","rules":[{"kind":"group","match":"any","rules":[{"kind":"rule","field":"playlist","operator":"is","value":{"kind":"playlist","value":"18446744073709551615"},"upper_value":null}]}]},"live_update":true,"match_rules":true,"checked_only":false,"limit":null,"editable":true,"supported":true,"support_reason":""}"#
        let smart = try Wire.decoder.decode(SmartPlaylistDTO.self, from: Data(json.utf8))
        let encoded = try Wire.encoder.encode(smart)
        let restored = try Wire.decoder.decode(SmartPlaylistDTO.self, from: encoded)
        XCTAssertEqual(smart, restored)
        XCTAssertTrue(String(decoding: encoded, as: UTF8.self).contains("18446744073709551615"))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertTrue(object.keys.contains("limit"))
    }

    func testEntryIdentityIsSeparateFromRepeatedTrackIdentity() throws {
        let json = #"[{"entry_id":"entry-a","track_id":"9007199254740993","position":0,"index":0,"missing_reference":true,"track":null},{"entry_id":"entry-b","track_id":"9007199254740993","position":1,"index":1,"missing_reference":true,"track":null}]"#
        let entries = try Wire.decoder.decode([PlaylistEntryDTO].self, from: Data(json.utf8))
        XCTAssertEqual(Set(entries.map(\.id)).count, 2)
        XCTAssertEqual(Set(entries.map(\.trackId)).count, 1)
    }

    func testPlaylistMutationCarriesBothRevisionsAndOccurrenceIDs() throws {
        var request = RequestDTO("playlist_edit", generation: "g")
        request.revision = "queue-r"
        request.playlistRevision = "playlist-r"
        var edit = PlaylistEditDTO(action: "remove_entries", playlistId: "-1")
        edit.entryIds = ["occurrence-2"]
        request.playlistEdit = edit
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: Wire.encoder.encode(request)) as? [String: Any])
        XCTAssertEqual(object["playlist_revision"] as? String, "playlist-r")
        let mutation = try XCTUnwrap(object["playlist_edit"] as? [String: Any])
        XCTAssertEqual(mutation["entry_ids"] as? [String], ["occurrence-2"])
    }
}
