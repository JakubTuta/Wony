import QtQuick
import "../theme"

// The on/off pill used in Settings. Display only: the row around it takes the tap.
Rectangle {
    id: root

    property bool checked: false

    width: 48
    height: 28
    radius: 14
    color: checked ? Theme.accent : Theme.line

    Behavior on color { ColorAnimation { duration: 150 } }

    Rectangle {
        y: 4
        x: root.checked ? 28 : 4
        width: 20
        height: 20
        radius: 10
        color: Theme.bg

        Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
    }
}
