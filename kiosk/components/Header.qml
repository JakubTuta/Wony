import QtQuick
import "../theme"
import "../state"
import "../lib/time.mjs" as Time

// Clock and date on the left, weather and the next event under them; the
// connection warning, Edit, Settings and the bell on the right.
Item {
    id: root

    property string tab: "home"
    property bool editing: false

    signal toggleEdit()
    signal openNotifications()
    signal openSystem()

    height: 96

    readonly property string summary: {
        var parts = []
        var w = Live.weather.data
        if (w && !w.error && w.temperature !== null)
            parts.push(Math.round(w.temperature) + "°" + (w.description ? " · " + w.description : ""))
        var events = Live.agenda.data && Live.agenda.data.events
        if (events && events.length > 0)
            parts.push("Next: " + events[0].title + " " + Time.clock(new Date(events[0].start)))
        return parts.join(" · ")
    }

    Row {
        x: 32
        anchors.verticalCenter: parent.verticalCenter
        spacing: 28

        Txt {
            id: clockText
            anchors.verticalCenter: parent.verticalCenter
            text: Time.clock(Clock.now)
            font.pixelSize: 52
            font.weight: Font.Bold
            font.letterSpacing: -1.04
            lh: 1
            tabular: true
        }

        Column {
            anchors.verticalCenter: parent.verticalCenter
            width: root.width - 32 - 28 - clockText.width - actions.width - 24 - 32
            spacing: 2

            Txt {
                width: parent.width
                text: Time.dayName(Clock.now)
                elide: Text.ElideRight
                font.weight: Font.DemiBold
            }
            Txt {
                visible: root.summary !== ""
                width: parent.width
                text: root.summary
                elide: Text.ElideRight
                color: Theme.muted
                font.pixelSize: 18
            }
        }
    }

    Row {
        id: actions
        anchors.right: parent.right
        anchors.rightMargin: 32
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12

        Item {
            visible: !Wony.connected
            width: 64
            height: 64
            Icon { anchors.centerIn: parent; name: "wifi-off"; size: 22; color: Theme.warn }
        }

        Pressable {
            visible: root.tab === "home"
            width: editLabel.implicitWidth + 52
            height: 64
            radius: 32
            color: root.editing ? Theme.surface2 : "transparent"
            border.width: 2
            border.color: Theme.line
            onClicked: root.toggleEdit()

            Txt {
                id: editLabel
                anchors.centerIn: parent
                text: root.editing ? "Done" : "Edit"
                font.weight: Font.DemiBold
            }
        }

        Pressable {
            width: 64
            height: 64
            radius: 32
            color: Theme.surface
            onClicked: root.openSystem()
            Icon { anchors.centerIn: parent; name: "settings"; size: 22; color: Theme.muted }
        }

        Pressable {
            id: bellButton
            readonly property bool unread: Wony.unreadCount > 0
            width: Math.max(64, bell.implicitWidth + 44)
            height: 64
            radius: 32
            color: unread ? Theme.accent : Theme.surface
            onClicked: root.openNotifications()

            Row {
                id: bell
                anchors.centerIn: parent
                spacing: 10

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 12
                    height: 12
                    radius: 6
                    color: bellButton.unread ? Theme.accentInk : Theme.off
                }
                Txt {
                    text: Wony.unreadCount
                    color: bellButton.unread ? Theme.accentInk : Theme.muted
                    font.weight: Font.Bold
                }
            }
        }
    }
}
