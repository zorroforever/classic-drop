import XCTest
@testable import ClassicDropCore

final class ProtocolTests: XCTestCase {
    func testFramingHandlesSplitUnicodeAndMultipleLines() throws {
        var decoder = LineDecoder()
        let data = Data("{\"name\":\"夜曲\"}\n{\"ok\":true}\n".utf8)
        XCTAssertTrue(try decoder.append(data.prefix(11)).isEmpty)
        let lines = try decoder.append(data.dropFirst(11))
        XCTAssertEqual(lines.count, 2)
        XCTAssertEqual(String(data: lines[0], encoding: .utf8), "{\"name\":\"夜曲\"}")
    }

    func testFramingRejectsOversizedUnterminatedMessage() throws {
        var decoder = LineDecoder()
        XCTAssertThrowsError(try decoder.append(Data(repeating: 65, count: 1_048_577)))
    }

    func testTrackIDsNeverRoundThroughFloatingPoint() throws {
        let json = """
        {"id":"18446744073709551615","title":"夜曲","artist":"N","album":"A","album_artist":"N","album_id":"a","genre":"","year":2024,"track_number":1,"disc_number":1,"length_ms":3000,"size_bytes":200,"artwork_id":"9007199254740993","source":""}
        """
        let track = try Wire.decoder.decode(TrackDTO.self, from: Data(json.utf8))
        XCTAssertEqual(track.id, "18446744073709551615")
        XCTAssertEqual(track.artworkId, "9007199254740993")
    }

    func testStageCompletionDoesNotFinishOperation() throws {
        var task = TaskState(id: "current", command: "commit")
        task.receive(id: "old", sequence: 10, progress: ProgressDTO(phase: "write", fraction: 1))
        XCTAssertNil(task.progress)
        task.receive(id: "current", sequence: 11, progress: ProgressDTO(phase: "write", fraction: 1))
        XCTAssertTrue(task.running)
        task.receive(id: "current", sequence: 9, progress: ProgressDTO(phase: "old", fraction: 0))
        XCTAssertEqual(task.progress?.phase, "write")
        task.finish(code: "recovery_required", detail: "Check recovery")
        XCTAssertFalse(task.running)
        XCTAssertEqual(task.outcome, "recovery_required")
    }
}
