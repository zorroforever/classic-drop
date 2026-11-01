import XCTest
@testable import ClassicDrop

final class ImportSourceTests: XCTestCase {
    @MainActor
    func testPlaylistImportAcceptsFilesAndFoldersTogether() {
        let model = AppModel(client: StubConnection())
        let panel = model.importSourcePanel(folder: false, playlistId: "new-playlist")

        XCTAssertTrue(panel.canChooseFiles)
        XCTAssertTrue(panel.canChooseDirectories)
        XCTAssertTrue(panel.allowsMultipleSelection)
    }

    @MainActor
    func testLibraryImportKeepsSeparateFileAndFolderPickers() {
        let model = AppModel(client: StubConnection())
        let files = model.importSourcePanel(folder: false)
        XCTAssertTrue(files.canChooseFiles)
        XCTAssertFalse(files.canChooseDirectories)

        let folders = model.importSourcePanel(folder: true)
        XCTAssertFalse(folders.canChooseFiles)
        XCTAssertTrue(folders.canChooseDirectories)
        XCTAssertTrue(folders.allowsMultipleSelection)
    }
}
