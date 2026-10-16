import QtQuick
import "../theme"
import "../components"

// A setting's name, a "needs restart" tag when the change only lands on restart,
// and its help line.
Column {
    id: root

    required property var field

    spacing: 0

    Row {
        spacing: 8

        Txt {
            text: root.field.label
            lh: 1.4
        }
        Txt {
            visible: root.field.restart
            text: "NEEDS RESTART"
            color: Theme.muted
            font.pixelSize: 15
            font.weight: Font.DemiBold
            lh: 1.4
            anchors.bottom: parent.bottom
        }
    }
    Txt {
        visible: root.field.help !== ""
        width: parent.width
        text: root.field.help
        color: Theme.muted
        font.pixelSize: 15
        font.weight: Font.DemiBold
        wrapMode: Text.Wrap
        lh: 1.4
    }
}
