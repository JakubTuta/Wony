import QtQuick
import "../theme"

// Fades `target` in while it rises `rise` pixels: .fade-up (8) and .sheet-in
// (24) on the web. Declare it inside the item that should appear, with
// `target` set to that item.
ParallelAnimation {
    id: root

    property Item target
    property int rise: 8
    property int duration: 220
    property Translate shift: Translate {}

    running: true

    NumberAnimation {
        target: root.target
        property: "opacity"
        from: 0
        to: 1
        duration: root.duration
        easing.type: Easing.BezierSpline
        easing.bezierCurve: Theme.easeOutSoft
    }
    NumberAnimation {
        target: root.shift
        property: "y"
        from: root.rise
        to: 0
        duration: root.duration
        easing.type: Easing.BezierSpline
        easing.bezierCurve: Theme.easeOutSoft
    }

    Component.onCompleted: target.transform = [shift]
}
