import QtQuick
import "../theme"
import "../components"

// Settings and Accounts behind the gear, plus the Sleep button.
Item {
    id: root

    property string section: "settings"
    property bool sleepOpen: false

    // The panel has gone dark; Shell takes the screen back to Home.
    signal sleeping()

    Row {
        id: pills
        spacing: 12

        Repeater {
            model: [["settings", "Settings"], ["accounts", "Accounts"]]

            Pressable {
                id: pill
                required property var modelData
                readonly property bool active: root.section === modelData[0]
                height: 64
                width: pillLabel.implicitWidth + 56
                radius: 34
                color: active ? Theme.text : Theme.surface
                onClicked: root.section = modelData[0]

                Txt {
                    id: pillLabel
                    anchors.centerIn: parent
                    text: pill.modelData[1]
                    color: pill.active ? Theme.panel : Theme.text
                    font.pixelSize: 19
                    font.weight: Font.DemiBold
                }
            }
        }

        Pressable {
            height: 64
            width: sleepRow.implicitWidth + 56
            radius: 34
            color: Theme.surface
            onClicked: root.sleepOpen = true

            Row {
                id: sleepRow
                anchors.centerIn: parent
                spacing: 8
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "moon"; size: 18 }
                Txt { text: "Sleep"; font.pixelSize: 19; font.weight: Font.DemiBold }
            }
        }
    }

    Rectangle {
        y: pills.height + 16
        width: parent.width
        height: parent.height - y
        radius: Theme.radiusTile
        color: Theme.surface
        clip: true

        Loader {
            anchors.fill: parent
            source: root.section === "settings" ? "Settings.qml" : "Accounts.qml"
        }
    }

    Loader {
        active: root.sleepOpen
        sourceComponent: SleepSheet {
            onSleeping: {
                root.sleepOpen = false
                root.sleeping()
            }
            onClosed: root.sleepOpen = false
        }
    }
}
