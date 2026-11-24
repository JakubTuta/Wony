import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/devices.mjs" as Devices

// One device in the list: its name and state, a switch when it is a plain
// on/off, and everything else once it is opened.
Rectangle {
    id: root

    required property var device
    property bool locksAllowed: false
    property bool expanded: false
    property bool isOnMap: false

    signal tapped()
    // Once the row has grown, so the list can bring it into view.
    signal opened()

    readonly property var control: device.primary
    readonly property string shape: Devices.shapeFor(control)
    readonly property bool blocked: control.guarded && !locksAllowed
    readonly property bool disabled: !control.available || blocked
    readonly property bool lit: control.on && !disabled
    readonly property bool hasSwitch: shape === "toggle" || shape === "toggle-level"

    onExpandedChanged: if (expanded) opened()

    implicitHeight: column.implicitHeight
    radius: Theme.radiusTile
    color: Theme.surface
    clip: true

    Column {
        id: column
        width: parent.width

        Pressable {
            id: header
            width: parent.width
            height: 96
            pressEffect: false
            onClicked: root.tapped()

            Rectangle {
                x: 24
                anchors.verticalCenter: parent.verticalCenter
                width: 56
                height: 56
                radius: 28
                color: root.lit ? Theme.accent : Theme.surface2

                Icon {
                    anchors.centerIn: parent
                    name: Devices.iconFor(root.control)
                    size: 28
                    color: root.lit ? Theme.accentInk : Theme.muted
                }
            }

            Column {
                x: 96
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 96 - (root.hasSwitch ? 112 + 12 : 0) - 24 - 36 - 12
                spacing: 2

                Txt {
                    width: parent.width
                    text: root.device.name
                    elide: Text.ElideRight
                    font.pixelSize: 24
                    font.weight: Font.Bold
                    lh: 1.2
                }
                Txt {
                    width: parent.width
                    elide: Text.ElideRight
                    color: root.lit ? Theme.accent : Theme.muted
                    font.pixelSize: 18
                    lh: 1.3
                    text: (root.blocked ? "Locked off in Settings"
                        : !root.control.available ? "Unavailable"
                        : Devices.stateText(root.control, root.shape)) + (root.isOnMap ? " · On map" : "")
                }
            }

            ToggleSwitch {
                visible: root.hasSwitch
                anchors.verticalCenter: parent.verticalCenter
                x: parent.width - 24 - 36 - 12 - width
                checked: root.control.on
                enabled: !root.disabled
                onClicked: DeviceActions.send(root.control.entity_id, "toggle", undefined, undefined)
            }

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                x: parent.width - 24 - width
                name: "chevron-down"
                size: 36
                color: Theme.muted
                rotation: root.expanded ? 180 : 0
                Behavior on rotation { NumberAnimation { duration: 150 } }
            }
        }

        Loader {
            active: root.expanded
            width: parent.width
            height: item ? (item as DeviceDetails).implicitHeight : 0
            sourceComponent: DeviceDetails {
                row: root
                width: column.width
            }
        }
    }
}
