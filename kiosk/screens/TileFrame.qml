import QtQuick
import "../theme"
import "../components"

// The chrome every Home tile shares: surface or accent fill, the small kind
// label with its on/off dot, and the round x that removes it while editing.
// The tile's own content goes inside.
Pressable {
    id: root

    property string kindLabel
    property bool active: false
    property bool editing: false
    readonly property color ink: active ? Theme.accentInk : Theme.text

    signal removeRequested()

    radius: Theme.radiusTile
    color: active ? Theme.accent : Theme.surface

    Txt {
        id: kind
        x: 24
        y: 24
        text: root.kindLabel.toUpperCase()
        color: root.ink
        opacity: 0.8
        font.pixelSize: 15
        font.weight: Font.DemiBold
        font.letterSpacing: 1.5
    }

    Rectangle {
        x: root.width - 24 - width
        y: 24 + (kind.implicitHeight - height) / 2
        width: 16
        height: 16
        radius: 8
        color: root.active ? Theme.accentInk : Theme.off
    }

    MouseArea {
        visible: root.editing
        x: root.width - 46
        y: -6
        width: 52
        height: 52
        onClicked: root.removeRequested()

        Rectangle {
            anchors.fill: parent
            radius: 26
            color: Theme.accent
            border.width: 4
            border.color: Theme.panel

            Txt {
                anchors.centerIn: parent
                text: "×"
                color: Theme.accentInk
                font.pixelSize: 28
                font.weight: Font.Bold
            }
        }
    }
}
