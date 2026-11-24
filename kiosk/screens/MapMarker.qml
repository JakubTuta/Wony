import QtQuick
import "../theme"
import "../components"

// One device on the map: a round button with its icon and name. Tapping it
// switches the device; while the map is being arranged it is dragged instead,
// and carries a button to take it off.
Item {
    id: root

    // A placement joined to its device (lib/homemap.mjs markers()).
    required property var marker
    required property real canvasWidth
    required property real canvasHeight
    property bool editing: false

    signal tapped()
    signal moved(real x, real y)
    signal removed()

    readonly property bool lit: marker.on && marker.available
    readonly property int size: 72

    // Fractions while a finger is moving it, so the marker follows without the
    // map rebuilding on every pixel.
    property bool dragging: false
    property real dragX: 0
    property real dragY: 0

    x: (dragging ? dragX : marker.x) * canvasWidth - size / 2
    y: (dragging ? dragY : marker.y) * canvasHeight - size / 2
    width: size
    height: size
    z: dragging ? 2 : 1

    Rectangle {
        id: disc
        anchors.fill: parent
        radius: width / 2
        color: root.lit ? Theme.accent : Theme.surface2
        border.width: 3
        border.color: root.lit ? Theme.accent : Theme.line
        opacity: root.marker.available ? 1 : 0.5
        scale: area.pressed && !root.editing ? 0.92 : (root.dragging ? 1.12 : 1)

        Behavior on scale { NumberAnimation { duration: 120 } }

        Icon {
            anchors.centerIn: parent
            name: root.marker.icon
            size: 34
            color: root.lit ? Theme.accentInk : Theme.text
        }
    }

    Rectangle {
        visible: root.marker.guarded
        x: root.size - 26
        y: root.size - 26
        width: 28
        height: 28
        radius: 14
        color: Theme.panel

        Icon { anchors.centerIn: parent; name: "lock"; size: 16; color: Theme.muted }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.size + 4
        width: Math.min(label.implicitWidth + 20, 200)
        height: 30
        radius: 15
        color: Qt.rgba(15 / 255, 38 / 255, 41 / 255, 0.88)

        Txt {
            id: label
            anchors.centerIn: parent
            width: parent.width - 20
            horizontalAlignment: Text.AlignHCenter
            text: root.marker.name
            elide: Text.ElideRight
            font.pixelSize: 17
            font.weight: Font.DemiBold
            lh: 1.2
        }
    }

    MouseArea {
        id: area
        x: -8
        y: -8
        width: root.size + 16
        height: root.size + 16

        property point origin
        property bool far: false

        onPressed: function (mouse) {
            origin = mapToItem(root.parent, mouse.x, mouse.y)
            far = false
        }
        onPositionChanged: function (mouse) {
            if (!root.editing || !pressed)
                return
            var at = mapToItem(root.parent, mouse.x, mouse.y)
            // A tap wobbles; only a real drag moves the device.
            if (!far && Math.abs(at.x - origin.x) + Math.abs(at.y - origin.y) < 12)
                return
            far = true
            root.dragging = true
            root.dragX = Math.min(1, Math.max(0, at.x / root.canvasWidth))
            root.dragY = Math.min(1, Math.max(0, at.y / root.canvasHeight))
        }
        onReleased: {
            if (root.dragging) {
                root.dragging = false
                root.moved(root.dragX, root.dragY)
            }
        }
        onClicked: if (!root.editing) root.tapped()
    }

    Pressable {
        visible: root.editing && !root.dragging
        x: root.size - 24
        y: -20
        width: 44
        height: 44
        radius: 22
        color: Theme.danger
        onClicked: root.removed()

        Icon { anchors.centerIn: parent; name: "x"; size: 22; color: Theme.accentInk }
    }
}
