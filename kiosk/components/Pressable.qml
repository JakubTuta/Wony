import QtQuick
import "../theme"

// A tappable surface: shrinks to 96% under the finger, like .press on the web.
// Put content inside it; set `enabled: false` to grey out and ignore taps.
Rectangle {
    id: root

    signal clicked()
    readonly property bool pressed: area.pressed
    property bool pressEffect: true

    color: "transparent"
    scale: pressEffect && area.pressed ? 0.96 : 1

    Behavior on scale {
        NumberAnimation {
            duration: 120
            easing.type: Easing.BezierSpline
            easing.bezierCurve: Theme.easeOutSoft
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: root.enabled
        onClicked: root.clicked()
    }
}
