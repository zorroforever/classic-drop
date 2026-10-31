import XCTest
@testable import ClassicDropCore

final class ProtocolTests: XCTestCase {
    func testAudioFormatUsesActualPrecisionAndCompleteMixedSummaries() throws {
        func facts(_ json: String) throws -> AudioFormatDTO {
            try Wire.decoder.decode(AudioFormatDTO.self, from: Data(json.utf8))
        }
        let alac = try facts(#"{"id":"1","codec":"ALAC","bit_depth":24,"sample_rate_hz":96000,"detail":""}"#)
        let aac = try facts(#"{"id":"2","codec":"AAC","bit_depth":null,"sample_rate_hz":44100,"detail":""}"#)
        XCTAssertEqual(alac.bitDepthText, "24-bit")
        XCTAssertEqual(aac.bitDepthText, "—")
        XCTAssertEqual(aac.sampleRateText, "44.1 kHz")
        XCTAssertNil(audioFormatSummary(ids: ["1", "2"], formats: ["1": alac], unknown: "Unknown"))
        let summary = try XCTUnwrap(audioFormatSummary(ids: ["1", "2"], formats: ["1": alac, "2": aac], unknown: "Unknown"))
        XCTAssertTrue(summary.contains("AAC / ALAC"))
        XCTAssertTrue(summary.contains("24-bit / —"))
        XCTAssertTrue(summary.contains("44.1 kHz / 96 kHz"))
        let unknown = try facts(#"{"id":"3","codec":"","bit_depth":null,"sample_rate_hz":null,"detail":"broken"}"#)
        XCTAssertTrue(try XCTUnwrap(audioFormatSummary(ids: ["1", "3"], formats: ["1": alac, "3": unknown], unknown: "Unknown")).contains("Unknown"))
    }

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
