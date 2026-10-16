import QtQuick
import "../theme"
import "../components"
import "../lib/devices.mjs" as Devices

// One physical thing in a room, drawn as the widget its kind calls for.
Rectangle {
    id: root

    required property var device
    property bool locksAllowed: false

    // act(action, value, option) runs straight away; guardedAct(action, yesLabel)
    // goes through the confirm sheet when the device or the Settings switch asks.
    signal act(string action, var value, var option)
    signal guardedAct(string action, string yesLabel)

    readonly property var control: device.primary
    readonly property string shape: Devices.shapeFor(control)
    readonly property bool blocked: control.guarded && !locksAllowed
    readonly property bool disabled: !control.available || blocked
    readonly property bool usable: !disabled

    radius: Theme.radiusTile
    color: Theme.surface
    clip: true

    Item {
        id: header
        x: 24
        y: 22
        width: parent.width - 48
        height: Math.max(64, names.implicitHeight)

        Column {
            id: names
            width: parent.width - (toggle.visible ? toggle.width + 12 : 0)
            spacing: 4

            Row {
                width: parent.width
                spacing: 6

                Icon {
                    visible: root.control.guarded
                    anchors.verticalCenter: parent.verticalCenter
                    name: "lock"
                    size: 16
                    color: Theme.muted
                }
                Txt {
                    width: parent.width - (root.control.guarded ? 22 : 0)
                    text: root.device.name
                    elide: Text.ElideRight
                    font.pixelSize: 26
                    font.weight: Font.Bold
                }
            }
            Txt {
                width: parent.width
                elide: Text.ElideRight
                color: root.control.on ? Theme.accent : Theme.muted
                text: root.blocked ? "Locked off in Settings"
                    : root.disabled ? "Unavailable"
                    : Devices.stateText(root.control, root.shape)
            }
        }

        Pressable {
            id: toggle
            visible: root.shape === "toggle" || root.shape === "toggle-level"
            anchors.right: parent.right
            width: 112
            height: 64
            radius: 32
            color: root.control.on ? Theme.accent : Theme.off
            opacity: root.disabled ? 0.4 : 1
            enabled: root.usable
            onClicked: root.act("toggle", undefined, undefined)

            Rectangle {
                width: 52
                height: 52
                radius: 26
                color: Theme.text
                y: 6
                x: root.control.on ? parent.width - width - 6 : 6
                Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
            }
        }
    }

    Item {
        id: body
        x: 24
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 22
        width: parent.width - 48
        height: root.shape === "options" ? optionsFlow.implicitHeight
              : root.shape === "number" ? 48 : 72
        visible: root.usable && root.shape !== "toggle" && root.shape !== "plain"

        // − bar +   (toggle-level and climate)
        Row {
            visible: root.shape === "toggle-level" || root.shape === "climate"
            anchors.fill: parent
            spacing: 14

            TextButton {
                width: 80
                height: 72
                radius: 20
                text: "−"
                textSize: 34
                textWeight: Font.Medium
                onClicked: root.shape === "climate"
                    ? root.act("set", (root.control.target === null ? 20 : root.control.target) - 0.5, undefined)
                    : root.act("on", Math.max(0, (root.control.level || 0) - 10), undefined)
            }
            Item {
                width: parent.width - 188
                height: 72

                Rectangle {
                    visible: root.shape === "toggle-level"
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: 16
                    radius: 8
                    color: Theme.panel
                    clip: true

                    Rectangle {
                        height: parent.height
                        radius: 8
                        width: parent.width * (root.control.on ? (root.control.level || 0) : 0) / 100
                        color: Theme.accent
                    }
                }
                Txt {
                    visible: root.shape === "climate"
                    anchors.fill: parent
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: root.control.target !== null ? root.control.target.toFixed(1) + "°" : "—"
                    font.pixelSize: 44
                    font.weight: Font.Bold
                    tabular: true
                }
            }
            TextButton {
                width: 80
                height: 72
                radius: 20
                text: "+"
                textSize: 34
                textWeight: Font.Medium
                onClicked: root.shape === "climate"
                    ? root.act("set", (root.control.target === null ? 20 : root.control.target) + 0.5, undefined)
                    : root.act("on", Math.min(100, (root.control.level || 0) + 10), undefined)
            }
        }

        Row {
            visible: root.shape === "cover"
            anchors.fill: parent
            spacing: 12

            Repeater {
                model: [["Open", "open"], ["Stop", "stop"], ["Close", "close"]]

                TextButton {
                    required property var modelData
                    width: (body.width - 24) / 3
                    height: 72
                    radius: 20
                    text: modelData[0]
                    textSize: 21
                    onClicked: root.act(modelData[1], undefined, undefined)
                }
            }
        }

        TextButton {
            visible: root.shape === "lock"
            anchors.fill: parent
            radius: 20
            text: root.control.on ? "Lock" : "Unlock"
            textSize: 21
            onClicked: root.guardedAct(root.control.on ? "lock" : "unlock", root.control.on ? "Lock" : "Unlock")
        }

        Row {
            visible: root.shape === "vacuum"
            anchors.fill: parent
            spacing: 12

            TextButton {
                width: (body.width - 12) / 2
                height: 72
                radius: 20
                color: Theme.accent
                textColor: Theme.accentInk
                text: "Start cleaning"
                textSize: 21
                textWeight: Font.Bold
                onClicked: root.act("start", undefined, undefined)
            }
            TextButton {
                width: (body.width - 12) / 2
                height: 72
                radius: 20
                text: "Send to dock"
                textSize: 21
                onClicked: root.act("dock", undefined, undefined)
            }
        }

        TextButton {
            visible: root.shape === "press"
            anchors.fill: parent
            radius: 20
            text: "Activate"
            textSize: 21
            onClicked: root.act("on", undefined, undefined)
        }

        Flow {
            id: optionsFlow
            visible: root.shape === "options"
            width: parent.width
            spacing: 8

            Repeater {
                model: root.control.options

                TextButton {
                    required property string modelData
                    height: 48
                    hPad: 16
                    radius: 12
                    color: root.control.state === modelData ? Theme.accent : Theme.surface2
                    textColor: root.control.state === modelData ? Theme.accentInk : Theme.muted
                    text: modelData
                    textSize: 18
                    onClicked: root.act("set", undefined, modelData)
                }
            }
        }

        Row {
            visible: root.shape === "number"
            anchors.right: parent.right
            spacing: 12

            TextButton {
                width: 48
                height: 48
                radius: 12
                text: "−"
                textSize: 22
                textWeight: Font.Medium
                onClicked: root.act("set", Number(root.control.state) - 1, undefined)
            }
            Txt {
                width: 64
                height: 48
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                text: root.control.state
                tabular: true
            }
            TextButton {
                width: 48
                height: 48
                radius: 12
                text: "+"
                textSize: 22
                textWeight: Font.Medium
                onClicked: root.act("set", Number(root.control.state) + 1, undefined)
            }
        }
    }
}
