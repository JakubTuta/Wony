import QtQuick
import "../theme"

// Everything not already on the Home screen, two to a row.
Scrim {
    id: root

    property var items: []
    signal picked(string id)
    signal closed()

    Rectangle {
        anchors.centerIn: parent
        width: 760
        height: column.implicitHeight + 64
        radius: Theme.radiusSheet
        color: Theme.surface

        MouseArea { anchors.fill: parent }

        Column {
            id: column
            x: 32
            y: 32
            width: parent.width - 64
            spacing: 18

            Item {
                width: parent.width
                height: 64

                Txt {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Add a tile"
                    font.pixelSize: 32
                    font.weight: Font.Bold
                }
                TextButton {
                    anchors.right: parent.right
                    text: "Close"
                    onClicked: root.closed()
                }
            }

            Txt {
                visible: root.items.length === 0
                text: "Every tile is already on the home screen."
                color: Theme.muted
            }

            Scroller {
                visible: root.items.length > 0
                width: parent.width
                height: Math.min(420, grid.implicitHeight)
                contentHeight: grid.implicitHeight

                Grid {
                    id: grid
                    columns: 2
                    spacing: 12

                    Repeater {
                        model: root.items

                        Pressable {
                            required property var modelData
                            width: (column.width - 12) / 2
                            height: 96
                            radius: 22
                            color: Theme.surface2
                            onClicked: root.picked(modelData.id)

                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                x: 22
                                width: parent.width - 44
                                spacing: 4

                                Txt {
                                    width: parent.width
                                    text: modelData.title
                                    elide: Text.ElideRight
                                    font.pixelSize: 22
                                    font.weight: Font.Bold
                                }
                                Txt {
                                    width: parent.width
                                    text: modelData.kind.toUpperCase()
                                    elide: Text.ElideRight
                                    color: Theme.muted
                                    font.pixelSize: 15
                                    font.letterSpacing: 1.2
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
