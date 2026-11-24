import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/devices.mjs" as Devices

// Every device, room by room. A row opens for its brightness, modes and what
// the device reports; one is open at a time so the list stays short.
Item {
    id: root

    // Entity ids that are on the map, so a row can say so.
    property var placed: []

    property string openId: ""

    readonly property var panel: Live.devices.data
    readonly property var areas: panel ? panel.areas : []
    readonly property bool locksAllowed: panel ? panel.locks_allowed : false

    // The row only has its full height after the next layout pass.
    Timer {
        id: revealTimer
        property Item row: null
        interval: 50
        onTriggered: scroller.reveal(row)
    }

    Scroller {
        id: scroller
        anchors.fill: parent
        contentHeight: rooms.implicitHeight + 8

        Column {
            id: rooms
            width: scroller.width
            spacing: 28

            Repeater {
                model: root.areas

                Column {
                    id: room
                    required property var modelData
                    width: rooms.width
                    spacing: 12

                    Txt {
                        text: Devices.areaLabel(room.modelData).toUpperCase() + "  ·  " + room.modelData.devices.length
                        color: Theme.muted
                        font.pixelSize: 16
                        font.weight: Font.Bold
                        font.letterSpacing: 1.4
                    }

                    Repeater {
                        model: room.modelData.devices

                        DeviceRow {
                            id: row
                            required property var modelData
                            width: room.width
                            device: modelData
                            locksAllowed: root.locksAllowed
                            expanded: root.openId === modelData.primary.entity_id
                            isOnMap: root.placed.indexOf(modelData.primary.entity_id) !== -1
                            onTapped: root.openId = expanded ? "" : modelData.primary.entity_id
                            onOpened: {
                                revealTimer.row = row
                                revealTimer.restart()
                            }
                        }
                    }
                }
            }
        }
    }
}
