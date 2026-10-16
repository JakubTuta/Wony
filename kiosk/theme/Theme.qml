pragma Singleton
import QtQuick

// Palette, type and motion for the whole panel. Dark only: this panel hangs on
// a wall, and there is no "the room got bright" moment that would make a light
// face worth having.
QtObject {
    readonly property color bg: "#081a1c"
    readonly property color panel: "#0f2629"
    readonly property color surface: "#173538"
    readonly property color surface2: "#1f4347"
    readonly property color line: "#2a5256"
    readonly property color off: "#2e5256"
    readonly property color text: "#eaf2f2"
    readonly property color muted: "#9fb8ba"
    readonly property color accent: "#f4928b"
    readonly property color accentInk: "#34110f"
    readonly property color scrim: Qt.rgba(5 / 255, 18 / 255, 20 / 255, 0.72)
    // Used only by Settings and Accounts, which the design leaves unstyled.
    readonly property color warn: "#e3b562"
    readonly property color danger: "#ef6f66"

    readonly property string fontDisplay: "Figtree"
    readonly property string fontMono: "IBM Plex Mono"

    readonly property int radiusTile: 28
    readonly property int radiusSheet: 32

    // The Frame is authored at 1280x800 and scaled as one object.
    readonly property int frameWidth: 1280
    readonly property int frameHeight: 800

    // cubic-bezier(.2, .8, .2, 1)
    readonly property var easeOutSoft: [0.2, 0.8, 0.2, 1, 1, 1]

    // Static TTFs, loaded once for the whole app. Names are Figtree and IBM Plex Mono.
    property list<FontLoader> fonts: [
        FontLoader { source: Qt.resolvedUrl("../fonts/Figtree-Medium.ttf") },
        FontLoader { source: Qt.resolvedUrl("../fonts/Figtree-SemiBold.ttf") },
        FontLoader { source: Qt.resolvedUrl("../fonts/Figtree-Bold.ttf") },
        FontLoader { source: Qt.resolvedUrl("../fonts/IBMPlexMono-Regular.ttf") },
        FontLoader { source: Qt.resolvedUrl("../fonts/IBMPlexMono-Medium.ttf") }
    ]
}
