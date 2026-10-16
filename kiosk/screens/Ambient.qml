import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/time.mjs" as Time

// The screen when nobody has touched the panel. Always dark: this is the surface
// that stays lit all night. Any touch dismisses it, and that touch does not fall
// through to what was underneath.
Rectangle {
    id: root

    signal wake()

    color: Theme.panel

    property var cards: []
    readonly property var newest: Wony.notifications.length > 0 ? Wony.notifications[0] : null

    function load() {
        Api.fetchAmbient(function (list) {
            root.cards = list
        })
    }

    Component.onCompleted: load()

    // The server caches these anyway; this is just how often the screen asks.
    Timer {
        running: true
        repeat: true
        interval: 10 * 60 * 1000
        onTriggered: root.load()
    }

    Appear { target: root }

    MouseArea {
        anchors.fill: parent
        onClicked: root.wake()
    }

    Column {
        anchors.centerIn: parent
        spacing: 32

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 4

            Txt {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Time.clock(Clock.now)
                font.pixelSize: 52
                font.weight: Font.Bold
                font.letterSpacing: -1.04
                lh: 1
                tabular: true
            }
            Txt {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Time.dayName(Clock.now)
                color: Theme.muted
                lh: 1.4
            }
        }

        Column {
            visible: root.cards.length > 0 || root.newest !== null
            anchors.horizontalCenter: parent.horizontalCenter
            width: 672
            spacing: 12

            Repeater {
                model: root.cards

                Column {
                    required property var modelData
                    width: 672
                    spacing: 4

                    Txt {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: modelData.label.toUpperCase()
                        color: Theme.muted
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.4
                        lh: 1.4
                    }
                    Txt {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: modelData.text
                        wrapMode: Text.Wrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        lh: 1.4
                    }
                }
            }

            Row {
                visible: root.newest !== null
                anchors.horizontalCenter: parent.horizontalCenter
                topPadding: 4
                spacing: 12

                Icon {
                    y: 2 + parent.topPadding
                    name: "bell"
                    size: 18
                    color: Theme.accent
                }
                Column {
                    width: Math.min(620, newestText.implicitWidth)

                    Txt {
                        id: newestText
                        width: parent.width
                        text: root.newest ? root.newest.text : ""
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        lh: 1.4
                    }
                    Txt {
                        visible: Wony.notifications.length > 1
                        text: "and " + (Wony.notifications.length - 1) + " more waiting"
                        color: Theme.muted
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        lh: 1.4
                    }
                }
            }
        }
    }

    Txt {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        text: "Touch anywhere"
        color: Theme.muted
        opacity: 0.5
        font.pixelSize: 15
        font.weight: Font.DemiBold
        lh: 1.4
    }
}
