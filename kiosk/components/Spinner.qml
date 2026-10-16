import QtQuick

// A turning refresh icon for anything in flight.
Icon {
    name: "refresh-cw"

    RotationAnimator on rotation {
        from: 0
        to: 360
        duration: 1000
        loops: Animation.Infinite
        running: parent.visible
    }
}
