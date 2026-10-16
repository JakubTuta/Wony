import QtQuick
import "../theme"
import "../state"
import "../lib/time.mjs" as Time

// Choosing how the night goes. A sheet rather than a one-tap tile, because
// sending the panel dark is the one thing on it that looks broken if it was
// not meant, and the wake time is worth asking: "until I touch it" is not
// always the right answer at 23:00 on a work night.
Scrim {
    id: root

    property string wakeAt: ""
    property bool scheduled: false
    property string error: ""
    property bool busy: false

    signal sleeping()
    signal closed()

    onDismissed: root.closed()

    Component.onCompleted: {
        Api.fetchSleep(function (state) {
            if (state && state.last_wake) {
                root.wakeAt = state.last_wake
                root.scheduled = true
            }
        })
    }

    function go() {
        busy = true
        error = ""
        Api.startSleep(scheduled ? wakeAt : "", function (result) {
            root.busy = false
            if (result.error) {
                root.error = result.error
                return
            }
            root.sleeping()
        })
    }

    Rectangle {
        anchors.centerIn: parent
        width: 600
        height: column.implicitHeight + 72
        radius: Theme.radiusSheet
        color: Theme.surface

        MouseArea { anchors.fill: parent }

        Column {
            id: column
            x: 36
            y: 36
            width: parent.width - 72
            spacing: 20

            Column {
                width: parent.width
                spacing: 8

                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    name: "moon"
                    size: 36
                    color: Theme.muted
                }
                Txt {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Sleep"
                    font.pixelSize: 26
                    font.weight: Font.Bold
                }
                Txt {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: Theme.muted
                    font.pixelSize: 17
                    lh: 1.5
                    text: "The screen goes dark and nothing shuts down — your timers still go off, and it comes back the moment you touch the glass."
                }
            }

            Column {
                width: parent.width
                spacing: 8

                Repeater {
                    model: [
                        { label: "Until I touch the screen", timed: false },
                        { label: "Wake me at a time", timed: true }
                    ]

                    Pressable {
                        id: option
                        required property var modelData
                        readonly property bool selected: root.scheduled === modelData.timed
                        width: parent.width
                        height: 64
                        radius: 20
                        color: Theme.surface2
                        border.width: 2
                        border.color: selected ? Theme.accent : "transparent"
                        onClicked: {
                            root.scheduled = modelData.timed
                            if (modelData.timed && !root.wakeAt)
                                root.wakeAt = "07:00"
                        }

                        Txt {
                            x: 20
                            anchors.verticalCenter: parent.verticalCenter
                            text: option.modelData.label
                            font.pixelSize: 19
                        }
                        Rectangle {
                            visible: option.selected
                            anchors.right: parent.right
                            anchors.rightMargin: 20
                            anchors.verticalCenter: parent.verticalCenter
                            width: 12
                            height: 12
                            radius: 6
                            color: Theme.accent
                        }
                    }
                }
            }

            Column {
                visible: root.scheduled
                width: parent.width
                spacing: 12

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 20

                    Pressable {
                        width: 64
                        height: 64
                        radius: 32
                        color: Theme.surface2
                        onClicked: root.wakeAt = Time.shiftClock(root.wakeAt || "07:00", -15)
                        Icon { anchors.centerIn: parent; name: "minus"; size: 22 }
                    }
                    Txt {
                        width: 128
                        height: 64
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        text: root.wakeAt || "07:00"
                        font.pixelSize: 34
                        font.weight: Font.Bold
                        tabular: true
                    }
                    Pressable {
                        width: 64
                        height: 64
                        radius: 32
                        color: Theme.surface2
                        onClicked: root.wakeAt = Time.shiftClock(root.wakeAt || "07:00", 15)
                        Icon { anchors.centerIn: parent; name: "plus"; size: 22 }
                    }
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 8

                    Repeater {
                        model: ["06:00", "07:00", "08:00"]

                        Pressable {
                            id: preset
                            required property string modelData
                            height: 48
                            width: presetLabel.implicitWidth + 32
                            radius: 24
                            color: Theme.surface2
                            border.width: 2
                            border.color: root.wakeAt === modelData ? Theme.accent : "transparent"
                            onClicked: root.wakeAt = modelData

                            Txt {
                                id: presetLabel
                                anchors.centerIn: parent
                                text: preset.modelData
                                font.pixelSize: 16
                                font.weight: Font.DemiBold
                                tabular: true
                            }
                        }
                    }
                }
            }

            Txt {
                visible: root.error !== ""
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: root.error
                color: Theme.danger
                font.pixelSize: 16
            }

            Pressable {
                width: parent.width
                height: 64
                radius: 24
                color: Theme.accent
                opacity: root.busy ? 0.6 : 1
                enabled: !root.busy
                onClicked: root.go()

                Row {
                    anchors.centerIn: parent
                    spacing: 8

                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: "moon"
                        size: 18
                        color: Theme.accentInk
                    }
                    Txt {
                        text: root.busy ? "Going dark…" : "Sleep now"
                        color: Theme.accentInk
                        font.pixelSize: 20
                        font.weight: Font.Bold
                    }
                }
            }
        }
    }
}
