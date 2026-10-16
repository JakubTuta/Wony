import QtQuick
import "../theme"
import "../state"

// The dimmed backdrop every sheet sits on. It moves itself into the shell's
// overlay layer so it covers the header and nav bar, not just its own screen,
// and swallows taps so nothing underneath is pressed. `dismissed` fires when
// the backdrop (not the sheet) is tapped.
Rectangle {
    id: root

    property color tint: Theme.scrim
    signal dismissed()

    parent: Ui.overlay
    anchors.fill: parent
    color: tint
    z: 40

    MouseArea {
        anchors.fill: parent
        onClicked: root.dismissed()
    }
}
