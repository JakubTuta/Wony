import QtQuick
import "../theme"
import "../components"
import "../lib/devices.mjs" as Devices

// What one control can do, drawn as the widget its kind calls for: a level bar,
// a thermostat, blinds buttons, a mode list. Shared by every row of the device
// list. A control that is a plain switch has nothing here unless it is an extra,
// which carries its own name and switch (`label`).
Column {
    id: root

    required property var control
    property bool locksAllowed: false
    property string label: ""

    // act(action, value, option) runs straight away; guardedAct(action, yesLabel)
    // goes through the confirm sheet when the device or the Settings switch asks.
    signal act(string action, var value, var option)
    signal guardedAct(string action, string yesLabel)

    readonly property string shape: Devices.shapeFor(control)
    readonly property bool usable: control.available && !(control.guarded && !locksAllowed)
    readonly property bool hasSwitch: label !== "" && (shape === "toggle" || shape === "toggle-level")
    readonly property bool hasBody: usable && shape !== "toggle" && shape !== "plain"

    spacing: 12

    Item {
        visible: root.label !== ""
        width: parent.width
        height: visible ? 64 : 0

        Txt {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - (root.hasSwitch ? 124 : 0)
            text: root.label
            elide: Text.ElideRight
            color: Theme.muted
            font.pixelSize: 20
            font.weight: Font.DemiBold
        }
        ToggleSwitch {
            visible: root.hasSwitch
            anchors.right: parent.right
            checked: root.control.on
            enabled: root.usable
            onClicked: root.act("toggle", undefined, undefined)
        }
    }

    Item {
        id: body
        visible: root.hasBody
        width: parent.width
        height: !visible ? 0
              : root.shape === "options" ? optionsFlow.implicitHeight
              : root.shape === "number" ? 48 : 72

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
