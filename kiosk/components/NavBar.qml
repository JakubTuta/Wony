import QtQuick
import "../theme"

// The four tabs along the bottom. Settings and Accounts live behind the gear.
Item {
    id: root

    property string tab: "home"
    signal changed(string next)

    height: 112

    readonly property var tabs: [
        { id: "home", label: "Home" },
        { id: "rooms", label: "Rooms" },
        { id: "music", label: "Music" },
        { id: "macros", label: "Macros" }
    ]

    Row {
        x: 32
        width: parent.width - 64
        height: 92
        spacing: 12

        Repeater {
            model: root.tabs

            Pressable {
                id: item
                required property var modelData
                readonly property bool active: root.tab === modelData.id
                width: (parent.width - 36) / 4
                height: 92
                radius: 24
                color: active ? Theme.surface2 : "transparent"
                onClicked: root.changed(modelData.id)

                Row {
                    anchors.centerIn: parent
                    spacing: 12

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 12
                        height: 12
                        radius: 6
                        color: item.active ? Theme.accent : "transparent"
                    }
                    Txt {
                        text: item.modelData.label
                        color: item.active ? Theme.text : Theme.muted
                        font.pixelSize: 23
                        font.weight: Font.Bold
                    }
                }
            }
        }
    }
}
