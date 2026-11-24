import QtQuick
import "../theme"
import "../state"

// The pictures on this device that could become the map: the Pictures,
// Downloads and Desktop folders, and any USB stick. The panel has no file
// picker, so the list comes from Wony and a tap names one by id.
Scrim {
    id: root

    signal picked(var homeMap)
    signal closed()

    property var pictures: []
    property bool loading: true
    // The id being opened, or "".
    property string opening: ""
    property string problem: ""

    function reload() {
        loading = true
        problem = ""
        Api.fetchMapPictures(function (result) {
            root.pictures = result.pictures
            root.problem = result.error || ""
            root.loading = false
        })
    }

    function pick(id) {
        opening = id
        problem = ""
        Api.importMapPicture(id, function (result) {
            root.opening = ""
            if (result.error)
                root.problem = result.error
            else
                root.picked(result.data)
        })
    }

    function sizeText(bytes) {
        return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB"
    }

    Component.onCompleted: reload()

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
                    text: "Choose a picture"
                    font.pixelSize: 32
                    font.weight: Font.Bold
                }
                Row {
                    anchors.right: parent.right
                    spacing: 12

                    TextButton {
                        text: "Refresh"
                        enabled: !root.loading && root.opening === ""
                        onClicked: root.reload()
                    }
                    TextButton {
                        text: "Close"
                        onClicked: root.closed()
                    }
                }
            }

            Txt {
                visible: root.problem !== ""
                width: parent.width
                text: root.problem
                color: Theme.warn
                wrapMode: Text.Wrap
            }

            Txt {
                visible: root.loading
                text: "Looking for pictures…"
                color: Theme.muted
            }

            Txt {
                visible: !root.loading && root.pictures.length === 0
                width: parent.width
                wrapMode: Text.Wrap
                color: Theme.muted
                lh: 1.4
                text: "No pictures found. Copy a PNG, JPG or WebP file (up to 15 MB) into the Pictures "
                    + "folder on this device, or onto a USB stick that is plugged in, then tap Refresh."
            }

            Scroller {
                visible: root.pictures.length > 0
                width: parent.width
                height: Math.min(380, list.implicitHeight)
                contentHeight: list.implicitHeight

                Column {
                    id: list
                    width: parent.width
                    spacing: 10

                    Repeater {
                        model: root.pictures

                        Pressable {
                            id: row
                            required property var modelData
                            width: list.width
                            height: 84
                            radius: 22
                            color: Theme.surface2
                            enabled: root.opening === ""
                            opacity: root.opening === "" || root.opening === modelData.id ? 1 : 0.5
                            onClicked: root.pick(modelData.id)

                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                x: 24
                                width: parent.width - 48
                                spacing: 2

                                Txt {
                                    width: parent.width
                                    text: row.modelData.name
                                    elide: Text.ElideMiddle
                                    font.pixelSize: 22
                                    font.weight: Font.Bold
                                    lh: 1.2
                                }
                                Txt {
                                    width: parent.width
                                    text: root.opening === row.modelData.id
                                        ? "Opening…"
                                        : row.modelData.place + "  ·  " + root.sizeText(row.modelData.size)
                                    color: Theme.muted
                                    font.pixelSize: 17
                                    lh: 1.3
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
