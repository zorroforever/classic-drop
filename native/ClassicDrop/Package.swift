// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ClassicDrop",
    defaultLocalization: "en",
    platforms: [.macOS("12.3")],
    products: [.executable(name: "ClassicDrop", targets: ["ClassicDrop"])],
    targets: [
        .target(name: "ClassicDropCore"),
        .executableTarget(name: "ClassicDrop", dependencies: ["ClassicDropCore"], resources: [.process("Resources")]),
        .testTarget(name: "ClassicDropCoreTests", dependencies: ["ClassicDropCore"]),
        .testTarget(name: "ClassicDropAppTests", dependencies: ["ClassicDrop"])
    ]
)
