import QtQuick
import "../theme"
import "../state"
import "../components"

// Your Home Assistant devices two ways. Map is a picture of your home where a
// tap switches a device; List is every device by room, with all it can do.
Item {
    id: root

    // "map" or "list". The map is the main view.
    property string mode: "map"
    property bool editing: false

    // { image, placements } once the server has answered, null before.
    property var homeMap: null
    property string mapError: ""
    // "", "saving", "saved" or "failed"
    property string saveState: ""
    property bool picking: false

    readonly property var panel: Live.devices.data
    readonly property bool hasDevices: panel !== null && panel.areas.length > 0
    readonly property bool hasMap: homeMap !== null && homeMap.image !== null
    readonly property var placedIds: homeMap ? homeMap.placements.map(function (p) { return p.entity_id }) : []
    readonly property var modes: [
        { id: "map", label: "Map", icon: "map" },
        { id: "list", label: "List", icon: "list" }
    ]

    onModeChanged: editing = false

    function loadMap() {
        Api.fetchHomeMap(function (result) {
            if (result.error) {
                root.mapError = result.error
                return
            }
            root.homeMap = result.data
            // A picture with nothing on it yet goes straight to placing devices.
            root.editing = result.data.image !== null && result.data.placements.length === 0
        })
    }

    function placementsEdited(placements) {
        homeMap = { image: homeMap.image, placements: placements }
        saveState = "saving"
        saveTimer.restart()
    }

    function save() {
        saveTimer.stop()
        Api.saveMapPlacements(homeMap.placements, function (result) {
            root.saveState = result.ok ? "saved" : "failed"
            if (!result.ok)
                Ui.toast(result.error)
        })
    }

    function pictureChosen(chosen) {
        picking = false
        homeMap = chosen
        mode = "map"
        editing = chosen.placements.length === 0 || editing
    }

    function askRemove() {
        Ui.confirm({
            title: "Remove the map?",
            sig: "Your devices stay in Home Assistant. Only the picture and where you put them goes.",
            yesLabel: "Remove",
            onConfirm: function () {
                saveTimer.stop()
                Api.deleteHomeMap(function (ok) {
                    if (!ok) {
                        Ui.toast("Could not remove the map.")
                        return
                    }
                    root.editing = false
                    root.saveState = ""
                    root.homeMap = { image: null, placements: [] }
                })
            }
        })
    }

    Component.onCompleted: loadMap()

    // Leaving with a change not yet sent would lose it.
    Component.onDestruction: {
        if (saveTimer.running)
            Api.saveMapPlacements(homeMap.placements, function () {})
    }

    Timer {
        id: saveTimer
        interval: 500
        onTriggered: root.save()
    }

    Item {
        id: toolbar
        width: parent.width
        height: 64

        Rectangle {
            width: 308
            height: 64
            radius: 32
            color: Theme.surface

            Row {
                x: 4
                y: 4
                spacing: 4

                Repeater {
                    model: root.modes

                    Pressable {
                        id: choice
                        required property var modelData
                        readonly property bool active: root.mode === modelData.id
                        width: 148
                        height: 56
                        radius: 28
                        color: active ? Theme.text : "transparent"
                        onClicked: root.mode = modelData.id

                        Row {
                            anchors.centerIn: parent
                            spacing: 10

                            Icon {
                                anchors.verticalCenter: parent.verticalCenter
                                name: choice.modelData.icon
                                size: 22
                                color: choice.active ? Theme.panel : Theme.muted
                            }
                            Txt {
                                text: choice.modelData.label
                                color: choice.active ? Theme.panel : Theme.text
                                font.pixelSize: 21
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }
        }

        Row {
            id: actions
            anchors.right: parent.right
            visible: root.mode === "map" && root.hasMap && root.hasDevices
            spacing: 12

            Txt {
                visible: root.editing && root.saveState !== ""
                anchors.verticalCenter: parent.verticalCenter
                color: root.saveState === "failed" ? Theme.warn : Theme.muted
                font.pixelSize: 18
                text: root.saveState === "saving" ? "Saving…"
                    : root.saveState === "failed" ? "Could not save" : "Saved"
            }
            TextButton {
                visible: root.editing
                text: "Change picture"
                onClicked: root.picking = true
            }
            TextButton {
                visible: root.editing
                text: "Remove map"
                onClicked: root.askRemove()
            }
            TextButton {
                color: root.editing ? Theme.accent : Theme.surface2
                textColor: root.editing ? Theme.accentInk : Theme.text
                text: root.editing ? "Done" : "Edit map"
                onClicked: root.editing = !root.editing
            }
        }
    }

    Item {
        id: content
        y: toolbar.height + 16
        width: parent.width
        height: parent.height - y

        Txt {
            visible: !root.hasDevices
            anchors.centerIn: parent
            color: Theme.muted
            text: Live.devices.error !== null && root.panel === null ? Live.devices.error
                : Live.devices.loaded ? "No devices found." : "Finding your devices…"
        }

        Loader {
            anchors.fill: parent
            active: root.hasDevices && root.mode === "list"
            sourceComponent: DeviceList { placed: root.placedIds }
        }

        Item {
            anchors.fill: parent
            visible: root.hasDevices && root.mode === "map"

            Txt {
                visible: root.homeMap === null
                anchors.centerIn: parent
                color: Theme.muted
                text: root.mapError || "Loading…"
            }

            MapStart {
                visible: root.homeMap !== null && !root.hasMap
                anchors.fill: parent
                onChoose: root.picking = true
            }

            Loader {
                anchors.fill: parent
                active: root.hasMap
                sourceComponent: HomeMap {
                    homeMap: root.homeMap
                    editing: root.editing
                    onPlacementsEdited: function (placements) { root.placementsEdited(placements) }
                }
            }
        }
    }

    Loader {
        active: root.picking
        sourceComponent: PictureSheet {
            onPicked: function (chosen) { root.pictureChosen(chosen) }
            onClosed: root.picking = false
        }
    }
}
