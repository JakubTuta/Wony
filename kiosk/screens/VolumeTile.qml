import QtQuick
import "../theme"
import "../state"
import "../components"

// The one tile with a widget in it rather than a single tap: a slider has no
// sensible single gesture. Its - and + presses are separate buttons, disabled
// while editing so a tap that lands on them does not move the volume.
TileFrame {
    id: root

    readonly property var volume: Live.music.data && Live.music.data.volume !== undefined
                                  ? Live.music.data.volume : null

    kindLabel: "Volume"
    pressEffect: false

    function step(direction) {
        Api.invokeJob("set_volume", { direction: direction }, function () {
            Live.music.refresh()
        })
    }

    Column {
        x: 24
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        width: parent.width - 48
        spacing: 10

        Txt {
            text: root.volume === null ? "—" : root.volume + "%"
            font.pixelSize: 30
            font.weight: Font.Bold
            font.letterSpacing: -0.3
            lh: 1.1
            tabular: true
        }

        Item {
            width: parent.width
            height: 48

            TextButton {
                width: 52
                height: 48
                radius: 16
                text: "−"
                textSize: 22
                textWeight: Font.Medium
                opacity: root.editing ? 0.4 : 1
                enabled: !root.editing
                onClicked: root.step("down")
            }
            Rectangle {
                x: 62
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 124
                height: 10
                radius: 5
                color: Theme.panel
                clip: true

                Rectangle {
                    height: parent.height
                    radius: 5
                    width: parent.width * (root.volume === null ? 0 : root.volume) / 100
                    color: Theme.accent
                }
            }
            TextButton {
                anchors.right: parent.right
                width: 52
                height: 48
                radius: 16
                text: "+"
                textSize: 22
                textWeight: Font.Medium
                opacity: root.editing ? 0.4 : 1
                enabled: !root.editing
                onClicked: root.step("up")
            }
        }
    }
}
