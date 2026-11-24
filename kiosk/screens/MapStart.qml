import QtQuick
import "../theme"
import "../components"

// What the map shows before there is one: what it is for, in three steps, and
// the button for the first.
Item {
    id: root

    signal choose()

    readonly property var steps: [
        { title: "Choose a picture", body: "A floor plan, or a photo of one." },
        { title: "Place your devices", body: "Tap a device, then tap where it is." },
        { title: "Tap to switch", body: "Tap a device on the map to turn it on or off." }
    ]

    Column {
        anchors.centerIn: parent
        width: parent.width
        spacing: 14

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 88
            height: 88
            radius: 44
            color: Theme.surface2

            Icon { anchors.centerIn: parent; name: "image-plus"; size: 44; color: Theme.accent }
        }

        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Put your home on a map"
            font.pixelSize: 38
            font.weight: Font.Bold
            lh: 1.2
        }

        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Switch lights, blinds and more right where they are."
            color: Theme.muted
            font.pixelSize: 21
        }

        Item { width: 1; height: 8 }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 16

            Repeater {
                model: root.steps

                Rectangle {
                    id: step
                    required property var modelData
                    required property int index
                    width: 360
                    height: 104
                    radius: 24
                    color: Theme.surface

                    Rectangle {
                        x: 20
                        y: 20
                        width: 40
                        height: 40
                        radius: 20
                        color: Theme.accent

                        Txt {
                            anchors.centerIn: parent
                            text: step.index + 1
                            color: Theme.accentInk
                            font.weight: Font.Bold
                            lh: 1
                        }
                    }
                    Column {
                        x: 76
                        y: 16
                        width: parent.width - 76 - 20
                        spacing: 2

                        Txt {
                            width: parent.width
                            text: step.modelData.title
                            elide: Text.ElideRight
                            font.pixelSize: 22
                            font.weight: Font.Bold
                            lh: 1.2
                        }
                        Txt {
                            width: parent.width
                            text: step.modelData.body
                            wrapMode: Text.Wrap
                            color: Theme.muted
                            font.pixelSize: 17
                            lh: 1.3
                        }
                    }
                }
            }
        }

        Item { width: 1; height: 8 }

        TextButton {
            anchors.horizontalCenter: parent.horizontalCenter
            height: 72
            hPad: 48
            color: Theme.accent
            textColor: Theme.accentInk
            text: "Choose a picture"
            textSize: 23
            textWeight: Font.Bold
            onClicked: root.choose()
        }
    }
}
