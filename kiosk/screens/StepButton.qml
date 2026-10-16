import QtQuick
import "../theme"
import "../components"

// The small outlined - and + of a number setting.
Pressable {
    property alias text: label.text

    width: 44
    height: 44
    radius: 12
    border.width: 1
    border.color: Theme.line

    Txt {
        id: label
        anchors.centerIn: parent
    }
}
