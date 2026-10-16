import QtQuick
import "../theme"

// A Pressable with one centred label, sized by its text plus `hPad` each side.
Pressable {
    id: root

    property alias text: label.text
    property color textColor: Theme.text
    property int textSize: 20
    property int textWeight: Font.DemiBold
    property int hPad: 24

    implicitWidth: label.implicitWidth + 2 * hPad
    implicitHeight: 64
    radius: height / 2
    color: Theme.surface2

    Txt {
        id: label
        anchors.centerIn: parent
        color: root.textColor
        font.pixelSize: root.textSize
        font.weight: root.textWeight
    }
}
