import QtQuick
import "../theme"

// Text with the panel's face and colour. `lh` is a CSS-style line-height
// multiple (1.4 means 1.4 x the pixel size). The default is 1.5, what the web
// panel's layout was drawn with.
Text {
    property real lh: 1.5
    property bool tabular: false
    // The font's own line height as a multiple of its size (Figtree 1.2).
    property real naturalLine: 1.2

    color: Theme.text
    font.family: Theme.fontDisplay
    font.pixelSize: 20
    // Only Figtree 500/600/700 are bundled; this is what an unstyled label got on the web.
    font.weight: Font.Medium
    font.features: tabular ? { "tnum": 1 } : {}
    lineHeightMode: Text.FixedHeight
    lineHeight: lh * font.pixelSize

    // Qt puts all the extra of a fixed line height below the text, and never
    // makes a line shorter than the font's own; CSS splits extra leading above
    // and below. Moving the glyphs down by half the extra keeps them where the
    // web panel had them, without changing the box the layout sees.
    transform: Translate { y: Math.max(0, lh - naturalLine) * font.pixelSize / 2 }
}
