import QtQuick
import "../state"
import "../lib/time.mjs" as Time

// The black page that catches the tap that wakes the device.
//
// With the panel powered down there is nothing to see here, and that is the
// point: the touchscreen is a separate input device and keeps reporting touches
// whether the backlight is on or not, so something has to still be there to
// receive one. It covers everything so the touch cannot land on a tile the
// sleeper cannot see. It is also the whole feature on a machine where no display
// backend worked: black page, same wake gesture, just a screen that stayed lit.
Rectangle {
    id: root

    signal wake()

    color: "black"

    // A moment of visible text first, so a mistaken tap on Sleep has an obvious
    // way out and does not look like a crash.
    property bool hint: true

    Timer {
        running: true
        interval: 4000
        onTriggered: root.hint = false
    }

    MouseArea {
        anchors.fill: parent
        onClicked: root.wake()
    }

    Column {
        anchors.centerIn: parent
        spacing: 12

        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Sleeping"
            color: "white"
            font.pixelSize: 30
            font.weight: Font.Bold
            lh: 1.15
            opacity: root.hint ? 0.6 : 0
            Behavior on opacity { NumberAnimation { duration: 1000 } }
        }
        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            color: "white"
            font.pixelSize: 15
            font.weight: Font.DemiBold
            opacity: root.hint ? 0.4 : 0
            Behavior on opacity { NumberAnimation { duration: 1000 } }
            text: Wony.sleep.wake_at
                ? "Waking at " + Time.clock(new Date(Wony.sleep.wake_at)) + " — or touch anywhere"
                : "Touch anywhere"
        }
    }
}
