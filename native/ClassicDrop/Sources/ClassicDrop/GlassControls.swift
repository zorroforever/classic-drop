import SwiftUI

/// Glass belongs to compact actions; native tables and navigation retain system surfaces.
struct GlassControls<Content: View>: View {
    @ViewBuilder var content: () -> Content
    var body: some View {
        if #available(macOS 26.0, *) {
            content().padding(8).glassEffect(.regular, in: RoundedRectangle(cornerRadius: 12))
        } else {
            content().padding(8).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
        }
    }
}
