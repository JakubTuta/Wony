import QtQuick
import "../theme"
import "../state"

// The bell's list, dropping from the top right. A tap outside closes it.
Scrim {
    id: root

    signal closed()

    onDismissed: root.closed()

    Rectangle {
        x: parent.width - width - 32
        y: 100
        width: 560
        height: column.implicitHeight + 56
        radius: Theme.radiusSheet
        color: Theme.surface

        MouseArea { anchors.fill: parent }

        Column {
            id: column
            x: 28
            y: 28
            width: parent.width - 56
            spacing: 16

            Txt {
                text: "NOTIFICATIONS"
                color: Theme.muted
                font.pixelSize: 15
                font.weight: Font.DemiBold
                font.letterSpacing: 1.5
            }

            Txt {
                visible: Wony.notifications.length === 0
                topPadding: 12
                bottomPadding: 12
                text: "All caught up."
                color: Theme.muted
                font.pixelSize: 21
            }

            Scroller {
                visible: Wony.notifications.length > 0
                width: parent.width
                height: Math.min(560, list.implicitHeight)
                contentHeight: list.implicitHeight

                Column {
                    id: list
                    width: parent.width
                    spacing: 16

                    Repeater {
                        model: Wony.notifications

                        Rectangle {
                            id: row
                            required property var modelData
                            width: list.width
                            height: Math.max(text.implicitHeight + source.implicitHeight + 4, 64) + 36
                            radius: 22
                            color: Theme.surface2

                            Column {
                                x: 20
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 40 - (dismiss.visible ? dismiss.width + 16 : 0)
                                spacing: 4

                                Txt {
                                    id: text
                                    width: parent.width
                                    text: row.modelData.text
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 21
                                    font.weight: Font.DemiBold
                                    lh: 1.25
                                }
                                Txt {
                                    id: source
                                    width: parent.width
                                    text: row.modelData.source
                                    elide: Text.ElideRight
                                    color: Theme.muted
                                    font.pixelSize: 16
                                }
                            }

                            TextButton {
                                id: dismiss
                                visible: row.modelData.id !== null
                                anchors.right: parent.right
                                anchors.rightMargin: 20
                                anchors.verticalCenter: parent.verticalCenter
                                radius: 20
                                color: Theme.panel
                                text: "Dismiss"
                                textSize: 18
                                hPad: 20
                                onClicked: Wony.ack(row.modelData.id)
                            }
                        }
                    }
                }
            }
        }
    }
}
