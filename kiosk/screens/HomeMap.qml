import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/homemap.mjs" as HomeMapLib
import "../lib/tiles.mjs" as Tiles

// The map: the picture with your devices on it. Tapping a device switches it.
// While editing, a list of the devices not yet placed sits beside it: tap one,
// then tap the map where it is.
Item {
    id: root

    // { image: { url, width, height }, placements: [{ entity_id, x, y }] }
    required property var homeMap
    property bool editing: false

    // The new list of placements. The screen above saves it.
    signal placementsEdited(var placements)

    // The device waiting to be put down, or "".
    property string armedId: ""

    readonly property var panel: Live.devices.data
    readonly property var placements: homeMap.placements
    readonly property var markers: HomeMapLib.markers(panel, placements)
    readonly property var waiting: HomeMapLib.unplaced(panel, placements)
    readonly property string armedName: {
        for (var i = 0; i < waiting.length; i++) {
            if (waiting[i].entity_id === armedId)
                return waiting[i].name
        }
        return ""
    }

    onEditingChanged: armedId = ""

    function tapDevice(entityId) {
        var info = Tiles.describeTile("device:" + entityId, {
            devices: panel,
            locksAllowed: panel ? panel.locks_allowed : false,
            confirmAllDevices: Wony.config ? Wony.config.kiosk.confirm_all_devices : false
        })
        DeviceActions.tap(info.action)
    }

    Rectangle {
        id: stage
        width: parent.width - (root.editing ? 376 : 0)
        height: parent.height
        radius: Theme.radiusTile
        color: Theme.surface
        clip: true

        readonly property var fit: HomeMapLib.fitRect(width, height, root.homeMap.image.width, root.homeMap.image.height)

        Item {
            id: canvas
            x: stage.fit.x
            y: stage.fit.y
            width: stage.fit.width
            height: stage.fit.height

            Image {
                id: picture
                anchors.fill: parent
                source: Api.base + root.homeMap.image.url
                asynchronous: true
                fillMode: Image.Stretch
                // Decoded at about the size it is shown, not at the size of the file.
                sourceSize.width: 1280
            }

            MouseArea {
                anchors.fill: parent
                enabled: root.editing && root.armedId !== ""
                onClicked: function (mouse) {
                    root.placementsEdited(HomeMapLib.placeAt(
                        root.placements, root.armedId, mouse.x / canvas.width, mouse.y / canvas.height))
                    root.armedId = ""
                }
            }

            Repeater {
                model: root.markers

                MapMarker {
                    required property var modelData
                    marker: modelData
                    canvasWidth: canvas.width
                    canvasHeight: canvas.height
                    editing: root.editing
                    onTapped: root.tapDevice(modelData.entity_id)
                    onMoved: function (x, y) {
                        root.placementsEdited(HomeMapLib.placeAt(root.placements, modelData.entity_id, x, y))
                    }
                    onRemoved: root.placementsEdited(HomeMapLib.removeFrom(root.placements, modelData.entity_id))
                }
            }
        }

        Spinner {
            visible: picture.status === Image.Loading
            anchors.centerIn: parent
            size: 40
            color: Theme.muted
        }

        Txt {
            visible: picture.status === Image.Error
            anchors.centerIn: parent
            width: parent.width - 80
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Theme.muted
            text: "This screen could not show the picture. Run ./wony.sh doctor on the Pi."
        }

        // What to do next, floating where the eye already is.
        Rectangle {
            visible: root.editing && root.armedId !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            y: 16
            width: armedText.implicitWidth + 40
            height: 52
            radius: 26
            color: Theme.accent

            Txt {
                id: armedText
                anchors.centerIn: parent
                text: "Tap where " + root.armedName + " goes"
                color: Theme.accentInk
                font.weight: Font.Bold
            }
        }

        Rectangle {
            visible: !root.editing && root.markers.length === 0
            anchors.horizontalCenter: parent.horizontalCenter
            y: 16
            width: emptyText.implicitWidth + 40
            height: 52
            radius: 26
            color: Theme.panel

            Txt {
                id: emptyText
                anchors.centerIn: parent
                text: "No devices on the map yet. Tap Edit map to add some."
                color: Theme.muted
            }
        }
    }

    Rectangle {
        visible: root.editing
        x: stage.width + 16
        width: 360
        height: parent.height
        radius: Theme.radiusTile
        color: Theme.surface

        Column {
            id: intro
            x: 24
            y: 22
            width: parent.width - 48
            spacing: 6

            Txt {
                text: "Add devices"
                font.pixelSize: 26
                font.weight: Font.Bold
            }
            Txt {
                width: parent.width
                wrapMode: Text.Wrap
                color: root.armedId !== "" ? Theme.accent : Theme.muted
                font.pixelSize: 17
                lh: 1.35
                text: root.armedId !== ""
                    ? "Now tap the map where it is."
                    : "Tap a device, then tap the map where it is. Drag one on the map to move it."
            }
        }

        Txt {
            visible: root.waiting.length === 0
            x: 24
            y: intro.y + intro.height + 24
            width: parent.width - 48
            wrapMode: Text.Wrap
            color: Theme.muted
            text: root.placements.length > 0
                ? "Every device is on the map."
                : "No device here can be switched with one tap. Use the list for the rest."
        }

        Scroller {
            id: tray
            y: intro.y + intro.height + 16
            width: parent.width
            height: parent.height - y - 12
            contentHeight: waitingColumn.implicitHeight + 12

            Column {
                id: waitingColumn
                x: 16
                width: tray.width - 32
                spacing: 8

                Repeater {
                    model: root.waiting

                    Pressable {
                        id: item
                        required property var modelData
                        readonly property bool armed: root.armedId === modelData.entity_id
                        width: waitingColumn.width
                        height: 72
                        radius: 20
                        color: armed ? Theme.accent : Theme.surface2
                        onClicked: root.armedId = armed ? "" : modelData.entity_id

                        Icon {
                            x: 18
                            anchors.verticalCenter: parent.verticalCenter
                            name: item.modelData.icon
                            size: 28
                            color: item.armed ? Theme.accentInk : Theme.muted
                        }
                        Column {
                            x: 62
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 62 - 16

                            Txt {
                                width: parent.width
                                text: item.modelData.name
                                elide: Text.ElideRight
                                color: item.armed ? Theme.accentInk : Theme.text
                                font.pixelSize: 21
                                font.weight: Font.Bold
                                lh: 1.2
                            }
                            Txt {
                                width: parent.width
                                text: item.modelData.area
                                elide: Text.ElideRight
                                color: item.armed ? Theme.accentInk : Theme.muted
                                font.pixelSize: 15
                                lh: 1.2
                            }
                        }
                    }
                }
            }
        }
    }
}
