import QtQuick
import "../theme"
import "../state"
import "../components"

// What a DeviceRow shows once it is opened: every control the device has, what
// it reports, and its id.
Item {
    id: root

    required property var row

    implicitHeight: column.implicitHeight + 24

    Column {
        id: column
        x: 24
        width: root.width - 48
        spacing: 18

        DeviceControls {
            width: parent.width
            control: root.row.control
            locksAllowed: root.row.locksAllowed
            onAct: function (action, value, option) {
                DeviceActions.send(root.row.control.entity_id, action, value, option)
            }
            onGuardedAct: function (action, yesLabel) {
                DeviceActions.guarded(root.row.control, root.row.device.name, action, yesLabel)
            }
        }

        Repeater {
            model: root.row.device.extras

            DeviceControls {
                required property var modelData
                width: column.width
                control: modelData
                label: modelData.name
                locksAllowed: root.row.locksAllowed
                onAct: function (action, value, option) {
                    DeviceActions.send(modelData.entity_id, action, value, option)
                }
                onGuardedAct: function (action, yesLabel) {
                    DeviceActions.guarded(modelData, modelData.name, action, yesLabel)
                }
            }
        }

        Grid {
            visible: readings.count > 0
            width: parent.width
            columns: 2
            columnSpacing: 24
            rowSpacing: 8

            Repeater {
                id: readings
                model: root.row.device.readings || []

                Row {
                    required property var modelData
                    width: (column.width - 24) / 2
                    spacing: 10

                    Txt {
                        text: modelData.name
                        color: Theme.muted
                        font.pixelSize: 18
                    }
                    Txt {
                        text: modelData.value
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                        tabular: true
                    }
                }
            }
        }

        Txt {
            text: root.row.control.entity_id
            color: Theme.muted
            font.family: Theme.fontMono
            font.pixelSize: 15
        }
    }
}
