import QtQuick
import "../theme"

// The pill above the nav, used for every fire-and-forget action ("Running
// Good night", "10 minute timer started"): the panel has no chat transcript to
// show it in instead.
Item {
    id: root

    property string text

    visible: text !== ""
    width: pill.width
    height: pill.height
    y: Theme.frameHeight - 28 - height

    onTextChanged: {
        if (text !== "")
            appear.restart()
    }

    Rectangle {
        id: pill
        width: label.implicitWidth + 60
        height: label.implicitHeight + 36
        radius: 40
        color: Theme.text

        Txt {
            id: label
            anchors.centerIn: parent
            text: root.text
            color: Theme.panel
            font.pixelSize: 21
            font.weight: Font.DemiBold
        }
    }

    Appear {
        id: appear
        target: root
        running: false
    }
}
