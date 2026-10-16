import QtQuick
import "../theme"
import "../components"

// A full-width pill button for the Accounts forms. Shows a spinner and
// "Working..." while its job runs.
Pressable {
    id: root

    property string icon
    property string label
    property bool busy: false
    property bool danger: false

    signal activated()

    height: 56
    radius: 28
    color: danger ? "transparent" : Theme.surface2
    border.width: 1
    border.color: danger ? Theme.danger : Theme.line
    opacity: enabled ? 1 : 0.5
    onClicked: root.activated()

    Row {
        anchors.centerIn: parent
        spacing: 8

        Spinner {
            visible: root.busy
            anchors.verticalCenter: parent.verticalCenter
            size: 18
            color: root.danger ? Theme.danger : Theme.text
        }
        Icon {
            visible: !root.busy && root.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: root.icon
            size: 18
            color: root.danger ? Theme.danger : Theme.text
        }
        Txt {
            text: root.busy ? "Working…" : root.label
            color: root.danger ? Theme.danger : Theme.text
        }
    }
}
