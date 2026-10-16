import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/devices.mjs" as Devices
import "../lib/jobs.mjs" as Jobs
import "../lib/layout.mjs" as Layout

// Every room's devices, one room at a time.
Item {
    id: root

    property string room: ""

    readonly property var panel: Live.devices.data
    readonly property var areas: panel ? panel.areas : []
    readonly property bool confirmAll: Wony.config ? Wony.config.kiosk.confirm_all_devices : false
    readonly property bool locksAllowed: panel ? panel.locks_allowed : false
    readonly property var activeArea: {
        for (var i = 0; i < areas.length; i++) {
            if ((areas[i].name || "Other") === room)
                return areas[i]
        }
        return areas.length > 0 ? areas[0] : null
    }
    readonly property var devices: activeArea ? activeArea.devices : []

    function act(control, action, value, option) {
        Api.controlDevice(control.entity_id, action, value, option, function (r) {
            Live.devices.refresh()
            if (!r.ok)
                Ui.toast(r.text)
        })
    }

    function guardedAct(device, action, yesLabel) {
        var control = device.primary
        if (!Devices.needsConfirm(control, confirmAll)) {
            act(control, action, undefined, undefined)
            return
        }
        var name = device.name.toLowerCase()
        Ui.confirm({
            title: Devices.confirmPhrase(action, name, control.on),
            sig: Jobs.signature("control_home_device", { target: name, action: action }),
            yesLabel: yesLabel,
            onConfirm: function () { root.act(control, action, undefined, undefined) }
        })
    }

    Txt {
        visible: Live.devices.error !== null && root.panel === null
        anchors.centerIn: parent
        text: Live.devices.error || ""
        color: Theme.muted
    }

    Txt {
        visible: root.areas.length === 0 && !(Live.devices.error !== null && root.panel === null)
        anchors.centerIn: parent
        text: Live.devices.loaded ? "No devices found." : "Finding your devices…"
        color: Theme.muted
    }

    Column {
        visible: root.areas.length > 0
        anchors.fill: parent
        spacing: 18

        Flickable {
            width: parent.width
            height: 68
            contentWidth: pills.width
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            flickableDirection: Flickable.HorizontalFlick

            Row {
                id: pills
                spacing: 12

                Repeater {
                    model: root.areas

                    Pressable {
                        id: pill
                        required property var modelData
                        readonly property bool active: (modelData.name || "Other") === (root.activeArea ? root.activeArea.name || "Other" : "")
                        height: 68
                        width: pillLabel.implicitWidth + 56
                        radius: 34
                        color: active ? Theme.text : Theme.surface
                        onClicked: root.room = modelData.name || "Other"

                        Txt {
                            id: pillLabel
                            anchors.centerIn: parent
                            text: pill.modelData.name || "Other"
                            color: pill.active ? Theme.panel : Theme.text
                            font.pixelSize: 21
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }
        }

        Scroller {
            id: scroller
            width: parent.width
            height: parent.height - 68 - 18
            // Cards share the height until they would get too small to fit their
            // controls; then the list scrolls.
            readonly property real cell: Layout.rowHeight(root.devices.length, 2, height, 16, 200)
            contentHeight: Layout.gridHeight(root.devices.length, 2, cell, 16)

            Grid {
                columns: 2
                spacing: 16

                Repeater {
                    model: root.devices

                    DeviceCard {
                        required property var modelData
                        device: modelData
                        locksAllowed: root.locksAllowed
                        width: (root.width - 16) / 2
                        height: scroller.cell
                        onAct: function (action, value, option) { root.act(modelData.primary, action, value, option) }
                        onGuardedAct: function (action, yesLabel) { root.guardedAct(modelData, action, yesLabel) }
                    }
                }
            }
        }
    }
}
