# Classic Drop application icon

The editable source is `classic-drop.svg`: an original silver player and blue
drop designed for Classic Drop. The artwork contains no Apple logo or exported
SF Symbols and is distributed under this repository's GPL-3.0-or-later license.

`classic-drop.png` is the 1024-pixel transparent Qt application icon.
`classic-drop.icns` contains the macOS application icon representations.
The native SwiftUI app uses `classic-drop-glass.svg` and its generated PNG and
ICNS counterparts. Its glass-inspired artwork preserves the player and drop
motif while distinguishing the native shell.
Both are generated from the SVG with the existing QtSvg and Pillow dependencies:

```shell
uv run python scripts/render_classic_drop_icon.py
```

The source checkout uses the PNG through `classic_drop.branding`. The macOS bundle
uses the original ICNS through `packaging/classic-drop.spec`; the native build
uses the glass ICNS. Launch the `.app` for the
Classic Drop name and application identity in the macOS application switcher;
running the Python interpreter directly is a developer mode.
