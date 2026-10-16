import QtQuick
import "../theme"
import "../components"

// One line of the Settings list, drawn for the kind of value it holds.
Item {
    id: root

    required property var field
    property var value: null
    // The first row of a section has no divider above it.
    property bool first: false

    signal changed(string key, var value)

    readonly property string text: value === null || value === undefined ? "" : String(value)
    readonly property real number: typeof value === "number" ? value : Number(value || 0)
    readonly property string kind: field.kind

    implicitHeight: content.implicitHeight + 24
    height: implicitHeight

    function step(direction) {
        var size = field.step === null ? 1 : field.step
        var low = field.min === null ? -Infinity : field.min
        var high = field.max === null ? Infinity : field.max
        var next = Number((number + direction * size).toFixed(3))
        changed(field.key, Math.min(high, Math.max(low, next)))
    }

    Rectangle {
        visible: !root.first
        width: parent.width
        height: 1
        color: Theme.line
    }

    Column {
        id: content
        x: 16
        y: 12
        width: parent.width - 32
        spacing: 8

        // toggle
        Item {
            visible: root.kind === "toggle"
            width: parent.width
            height: visible ? toggleLabel.implicitHeight : 0

            MouseArea {
                anchors.fill: parent
                anchors.margins: -12
                onClicked: root.changed(root.field.key, !root.value)
            }
            Switch {
                id: toggleSwitch
                anchors.verticalCenter: parent.verticalCenter
                checked: Boolean(root.value)
            }
            SettingLabel {
                id: toggleLabel
                x: toggleSwitch.width + 12
                width: parent.width - x
                field: root.field
            }
        }

        // choice: a row of buttons rather than a dropdown, which would open a
        // list too small to hit reliably on a touch screen.
        SettingLabel {
            visible: root.kind === "choice"
            width: parent.width
            field: root.field
        }
        Flow {
            visible: root.kind === "choice"
            width: parent.width
            spacing: 8

            Repeater {
                model: root.kind === "choice" ? root.field.choices : []

                Pressable {
                    id: choice
                    required property string modelData
                    readonly property bool selected: root.text === modelData
                    height: 44
                    width: choiceLabel.implicitWidth + 32
                    radius: 12
                    border.width: 1
                    border.color: selected ? Theme.accent : Theme.line
                    onClicked: root.changed(root.field.key, modelData)

                    Txt {
                        id: choiceLabel
                        anchors.centerIn: parent
                        text: choice.modelData
                        color: choice.selected ? Theme.accent : Theme.muted
                    }
                }
            }
        }

        // number
        Item {
            visible: root.kind === "number"
            width: parent.width
            height: visible ? Math.max(44, numberLabel.implicitHeight) : 0

            SettingLabel {
                id: numberLabel
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 44 * 2 - 64 - 24
                field: root.field
            }
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                StepButton { text: "−"; onClicked: root.step(-1) }
                Txt {
                    width: 64
                    height: 44
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: root.number
                    tabular: true
                }
                StepButton { text: "+"; onClicked: root.step(1) }
            }
        }

        // text and longtext
        SettingLabel {
            visible: root.kind === "text" || root.kind === "longtext"
            width: parent.width
            field: root.field
        }
        Field {
            visible: root.kind === "text" || root.kind === "longtext"
            width: parent.width
            multiline: root.kind === "longtext"
            text: root.text
            onEdited: function (next) { root.changed(root.field.key, next) }
        }
    }
}
