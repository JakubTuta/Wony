import QtQuick
import "../theme"
import "../state"

// A sheet rising from the bottom, for the Accounts forms. It lifts above the
// on-screen keyboard and scrolls its own content when it runs out of room.
// Declare content as children; `footer` is pinned below the scrolling part.
Scrim {
    id: root

    property string title
    property string subtitle
    default property alias content: body.data
    property alias footer: footerSlot.data

    signal closed()

    tint: Qt.rgba(0, 0, 0, 0.45)
    onDismissed: root.closed()

    Rectangle {
        id: sheet

        readonly property real available: Math.min(0.85 * root.height, root.height - Ui.keyboardInset - 16)

        width: parent.width
        // 24 px of the rounded bottom corners hang below the frame edge.
        height: Math.min(available, header.height + scroller.contentHeight + footerSlot.height) + 24
        y: parent.height - height + 24 - Ui.keyboardInset
        radius: 24
        color: Theme.surface

        Appear { target: sheet; rise: 24; duration: 240 }

        MouseArea { anchors.fill: parent }

        Rectangle {
            x: 24
            width: parent.width - 48
            height: 1
            color: Theme.line
        }

        Item {
            id: header
            width: parent.width
            height: 20 + titleText.implicitHeight + (subtitleText.visible ? subtitleText.implicitHeight : 0) + 8

            Column {
                x: 20
                y: 20
                width: parent.width - 40 - 44
                spacing: 0

                Txt {
                    id: titleText
                    width: parent.width
                    text: root.title
                    elide: Text.ElideRight
                    font.pixelSize: 30
                    font.weight: Font.Bold
                    font.letterSpacing: -0.3
                    lh: 1.15
                }
                Txt {
                    id: subtitleText
                    visible: root.subtitle !== ""
                    width: parent.width
                    text: root.subtitle
                    elide: Text.ElideRight
                    color: Theme.muted
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    lh: 1.4
                }
            }

            Pressable {
                x: parent.width - 12 - width
                y: 12
                width: 44
                height: 44
                radius: 22
                onClicked: root.closed()
                Icon { anchors.centerIn: parent; name: "x"; size: 22; color: Theme.muted }
            }
        }

        Scroller {
            id: scroller
            y: header.height
            width: parent.width
            height: parent.height - 24 - header.height - footerSlot.height
            contentHeight: body.implicitHeight + 12

            Column {
                id: body
                x: 20
                width: scroller.width - 40
                spacing: 12
            }
        }

        Item {
            id: footerSlot
            x: 20
            y: parent.height - 24 - height
            width: parent.width - 40
            height: childrenRect.height > 0 ? childrenRect.height + 16 : 0
        }
    }
}
