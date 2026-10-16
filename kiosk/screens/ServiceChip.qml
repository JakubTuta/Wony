import QtQuick
import "../theme"
import "../components"

// A Google service's sign-in at a glance: its icon, then a tick or a warning.
Rectangle {
    id: root

    property string icon
    property bool ok: false

    width: row.implicitWidth + 16
    height: 28
    radius: 14
    color: "transparent"
    border.width: 1
    border.color: ok ? Theme.line : Theme.warn

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 4

        Icon {
            anchors.verticalCenter: parent.verticalCenter
            name: root.icon
            size: 14
            color: root.ok ? Theme.muted : Theme.warn
        }
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            name: root.ok ? "check" : "triangle-alert"
            size: 12
            color: root.ok ? Theme.muted : Theme.warn
        }
    }
}
