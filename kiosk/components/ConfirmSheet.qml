import QtQuick
import "../theme"

// "Are you sure?" for anything that locks, unlocks or cancels.
Scrim {
    id: root

    required property var request
    signal canceled()
    signal confirmed()

    z: 42

    Rectangle {
        anchors.centerIn: parent
        width: 680
        height: column.implicitHeight + 72
        radius: Theme.radiusSheet
        color: Theme.surface

        MouseArea { anchors.fill: parent }

        Column {
            id: column
            x: 36
            y: 36
            width: parent.width - 72
            spacing: 18

            Txt {
                text: "CONFIRM"
                color: Theme.accent
                font.pixelSize: 15
                font.weight: Font.DemiBold
                font.letterSpacing: 1.5
            }
            Txt {
                width: parent.width
                text: root.request.title
                font.pixelSize: 38
                font.weight: Font.Bold
                lh: 1.15
                wrapMode: Text.Wrap
            }
            Txt {
                width: parent.width
                text: root.request.sig
                color: Theme.muted
                font.family: Theme.fontMono
                naturalLine: 1.31
                font.pixelSize: 16
                wrapMode: Text.WrapAnywhere
            }
            Row {
                width: parent.width
                topPadding: 10
                spacing: 16

                TextButton {
                    width: (parent.width - 16) / 2
                    height: 100
                    radius: 24
                    text: "Cancel"
                    textSize: 26
                    textWeight: Font.Bold
                    onClicked: root.canceled()
                }
                TextButton {
                    width: (parent.width - 16) / 2
                    height: 100
                    radius: 24
                    color: Theme.accent
                    textColor: Theme.accentInk
                    text: root.request.yesLabel
                    textSize: 26
                    textWeight: Font.Bold
                    onClicked: root.confirmed()
                }
            }
        }
    }
}
