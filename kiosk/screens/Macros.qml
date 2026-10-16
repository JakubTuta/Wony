import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/layout.mjs" as Layout

// Routines, and one-tap timers.
Item {
    id: root

    readonly property var quickTimers: [1, 5, 10, 15, 30, 60]
    readonly property var routines: Live.routines.data ? Live.routines.data.routines : []

    function runRoutine(name) {
        Ui.toast("Running " + name)
        Wony.runPrompt("run my " + name + " routine", function (res) {
            if (!res.ok)
                Ui.toast(res.text || "That did not work.")
        })
    }

    function startTimer(minutes) {
        var text = minutes + " minute timer"
        Api.invokeJob("add_reminder", { when: "in " + minutes + " minutes", text: text }, function () {
            Live.reminders.refresh()
        })
        Ui.toast(minutes + " minute timer started")
    }

    Txt {
        id: routinesLabel
        text: "ROUTINES"
        color: Theme.muted
        font.pixelSize: 15
        font.weight: Font.DemiBold
        font.letterSpacing: 1.5
    }

    Item {
        id: area
        anchors.top: routinesLabel.bottom
        anchors.topMargin: 14
        anchors.bottom: timersLabel.top
        anchors.bottomMargin: 20
        width: parent.width

        Txt {
            visible: root.routines.length === 0
            anchors.centerIn: parent
            text: Live.routines.loaded ? "No routines yet." : "Checking…"
            color: Theme.muted
            font.pixelSize: 19
        }

        Scroller {
            id: scroller
            anchors.fill: parent
            visible: root.routines.length > 0
            readonly property real cell: Layout.rowHeight(root.routines.length, 3, height, 16, 120)
            contentHeight: Layout.gridHeight(root.routines.length, 3, cell, 16)

            Grid {
                columns: 3
                spacing: 16

                Repeater {
                    model: root.routines

                    Pressable {
                        id: card
                        required property var modelData
                        width: (area.width - 32) / 3
                        height: scroller.cell
                        radius: Theme.radiusTile
                        color: Theme.surface
                        clip: true
                        onClicked: root.runRoutine(modelData.name)

                        Txt {
                            x: 24
                            y: 22
                            width: parent.width - 48
                            text: card.modelData.name
                            font.pixelSize: 28
                            font.weight: Font.Bold
                            font.capitalization: Font.Capitalize
                            elide: Text.ElideRight
                        }
                        Txt {
                            x: 24
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 22
                            width: parent.width - 48
                            text: card.modelData.steps
                            color: Theme.muted
                            font.pixelSize: 17
                            lh: 1.35
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }

    Txt {
        id: timersLabel
        anchors.bottom: timers.top
        anchors.bottomMargin: 14
        text: "QUICK TIMERS"
        color: Theme.muted
        font.pixelSize: 15
        font.weight: Font.DemiBold
        font.letterSpacing: 1.5
    }

    Row {
        id: timers
        anchors.bottom: parent.bottom
        spacing: 12

        Repeater {
            model: root.quickTimers

            TextButton {
                required property int modelData
                width: (root.width - 60) / 6
                height: 88
                radius: 24
                text: modelData + " min"
                textSize: 26
                textWeight: Font.Bold
                onClicked: root.startTimer(modelData)
            }
        }
    }
}
