import QtQuick
import "../theme"

// The large on/off pill on a device, sized for a finger. Tapping it only asks:
// the screen decides what to do and the knob follows the device's own state.
Pressable {
    id: root

    property bool checked: false

    width: 112
    height: 64
    radius: 32
    color: checked ? Theme.accent : Theme.off
    opacity: enabled ? 1 : 0.4

    Rectangle {
        width: 52
        height: 52
        radius: 26
        color: Theme.text
        y: 6
        x: root.checked ? parent.width - width - 6 : 6
        Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
    }
}
