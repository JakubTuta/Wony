import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/layout.mjs" as Layout
import "../lib/tiles.mjs" as Tiles
import "../lib/time.mjs" as Time

// The tile grid on the left; what is playing and what is coming up on the right.
Item {
    id: root

    property bool editing: false

    // null until the saved layout (or the first-run starter set) is known.
    property var tileIds: null
    property bool addOpen: false
    property bool sleepOpen: false
    // Counts seconds so timer tiles and the "Coming up" countdowns move.
    property int tick: 0

    readonly property int columns: Wony.config ? Wony.config.kiosk.home_columns : 3
    readonly property var music: Live.music.data
    readonly property int gridCount: (tileIds ? tileIds.length : 0) + (editing ? 1 : 0)

    // Reminders and calendar events together, soonest three. Only the data
    // decides the list; the countdown text re-reads tick by itself.
    readonly property var upcoming: {
        var items = []
        var reminders = Live.reminders.data ? Live.reminders.data.reminders : []
        for (var i = 0; i < reminders.length; i++) {
            var r = reminders[i]
            if (!r.next_run)
                continue
            items.push({
                key: "r-" + r.id,
                iso: r.next_run,
                whenMs: new Date(r.next_run).getTime(),
                title: r.text || (r.action_job ? "Run " + r.action_job : "Timer"),
                meta: "Reminder"
            })
        }
        var events = Live.agenda.data ? Live.agenda.data.events : []
        for (var j = 0; j < events.length; j++) {
            var e = events[j]
            items.push({
                key: "e-" + e.id,
                iso: e.start,
                whenMs: new Date(e.start).getTime(),
                title: e.title,
                meta: e.location || e.account || "Calendar"
            })
        }
        items.sort(function (a, b) { return a.whenMs - b.whenMs })
        return items.slice(0, 3)
    }

    function persist(next) {
        tileIds = next
        Api.saveKioskTiles(next)
    }

    function removeTile(id) {
        persist(tileIds.filter(function (t) { return t !== id }))
    }

    function addTile(id) {
        persist(tileIds.concat([id]))
        addOpen = false
    }

    function candidates() {
        var all = Tiles.candidateTiles(Live.routines.data ? Live.routines.data.routines : [], Live.devices.data)
        return all.filter(function (item) { return tileIds.indexOf(item.id) === -1 })
    }

    // First run: nobody has arranged a layout yet, so seed one from whatever this
    // house actually has. One-off reads rather than the live polls, since this
    // only ever runs once.
    function loadTiles() {
        Api.fetchKioskTiles(function (saved) {
            if (saved !== null) {
                root.tileIds = saved
                return
            }
            Api.fetchPanel("devices", function (devices) {
                Api.fetchPanel("routines", function (routines) {
                    var seed = Tiles.seedTiles(routines.data ? routines.data.routines : [], devices.data)
                    root.persist(seed)
                })
            })
        })
    }

    function run(action) {
        switch (action.type) {
        case "routine":
            Ui.toast("Running " + action.name)
            Wony.runPrompt("run my " + action.name + " routine", function (res) {
                if (!res.ok)
                    Ui.toast(res.text || "That did not work.")
            })
            break
        case "notice":
            Ui.toast(action.text)
            break
        case "device":
            var go = function () {
                Api.controlDevice(action.entityId, action.action, undefined, undefined, function (r) {
                    Live.devices.refresh()
                    if (action.confirm)
                        Ui.toast(r.text || action.name + " " + action.action + ".")
                })
            }
            if (action.confirm)
                Ui.confirm({ title: action.confirm.title, sig: action.confirm.sig, yesLabel: action.confirm.yesLabel, onConfirm: go })
            else
                go()
            break
        case "timer-start":
            Api.invokeJob("add_reminder", { when: "in " + action.minutes + " minutes", text: action.text }, function () {
                Live.reminders.refresh()
            })
            Ui.toast(action.minutes + " minute timer started")
            break
        case "timer-cancel":
            Ui.confirm({
                title: action.confirm.title,
                sig: action.confirm.sig,
                yesLabel: action.confirm.yesLabel,
                onConfirm: function () {
                    Api.invokeJob("manage_reminders", { action: "cancel", id_or_text: action.id }, function () {
                        Live.reminders.refresh()
                    })
                }
            })
            break
        case "music":
            transport("toggle")
            break
        case "sleep":
            sleepOpen = true
            break
        }
    }

    function transport(action) {
        Api.invokeJob("control_playback", { action: action }, function () {
            Live.music.refresh()
        })
    }

    Component.onCompleted: loadTiles()

    Timer {
        running: true
        repeat: true
        interval: 1000
        onTriggered: root.tick++
    }

    // ── Tiles ───────────────────────────────────────────────────────────────

    Item {
        id: tilesArea
        width: parent.width - 380
        height: parent.height

        Column {
            visible: root.tileIds !== null && root.tileIds.length === 0 && !root.editing
            anchors.centerIn: parent
            spacing: 8

            Txt {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "No tiles yet"
                font.pixelSize: 30
                font.weight: Font.Bold
                font.letterSpacing: -0.3
                lh: 1.15
            }
            Txt {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Tap Edit, then + Add tile, to build your home screen."
                color: Theme.muted
                font.pixelSize: 18
            }
        }

        Scroller {
            id: scroller
            anchors.fill: parent
            visible: root.gridCount > 0
            readonly property real cell: Layout.rowHeight(root.gridCount, root.columns, height, 16, 140)
            contentHeight: Layout.gridHeight(root.gridCount, root.columns, cell, 16)

            Grid {
                columns: root.columns
                spacing: 16

                Repeater {
                    model: root.tileIds

                    Item {
                        id: slot
                        required property string modelData
                        width: (tilesArea.width - (root.columns - 1) * 16) / root.columns
                        height: scroller.cell

                        Loader {
                            anchors.fill: parent
                            sourceComponent: slot.modelData === "volume" ? volumeTile : plainTile
                        }

                        Component {
                            id: plainTile
                            Tile {
                                tileId: slot.modelData
                                tick: root.tick
                                editing: root.editing
                                onTapped: function (action) { root.run(action) }
                                onRemoveRequested: root.removeTile(slot.modelData)
                            }
                        }
                        Component {
                            id: volumeTile
                            VolumeTile {
                                editing: root.editing
                                onRemoveRequested: root.removeTile("volume")
                            }
                        }
                    }
                }

                DashedBox {
                    visible: root.editing
                    width: (tilesArea.width - (root.columns - 1) * 16) / root.columns
                    height: scroller.cell
                    radius: Theme.radiusTile
                    onClicked: root.addOpen = true

                    Txt {
                        anchors.centerIn: parent
                        text: "+ Add tile"
                        color: Theme.muted
                        font.pixelSize: 26
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
    }

    // ── Right column ────────────────────────────────────────────────────────

    Column {
        x: parent.width - 360
        width: 360
        height: parent.height
        spacing: 16

        Rectangle {
            width: parent.width
            height: nowPlaying.implicitHeight + 44
            radius: Theme.radiusTile
            color: Theme.surface

            Column {
                id: nowPlaying
                x: 22
                y: 22
                width: parent.width - 44
                spacing: 18

                Row {
                    width: parent.width
                    spacing: 16

                    Cover {
                        width: 84
                        height: 84
                        radius: 16
                        source: root.music && root.music.art_url ? root.music.art_url : ""
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 100
                        spacing: 4

                        Txt {
                            width: parent.width
                            text: root.music && root.music.title ? root.music.title : "Nothing playing"
                            elide: Text.ElideRight
                            font.pixelSize: 24
                            font.weight: Font.Bold
                        }
                        Txt {
                            width: parent.width
                            text: root.music && root.music.artist ? root.music.artist : ""
                            elide: Text.ElideRight
                            color: Theme.muted
                            font.pixelSize: 18
                        }
                    }
                }

                Item {
                    width: parent.width
                    height: 72

                    // '1fr 1.3fr 1fr' with 10 px gaps.
                    readonly property real fr: (width - 20) / 3.3

                    Pressable {
                        width: parent.fr
                        height: 72
                        radius: 20
                        color: Theme.surface2
                        onClicked: root.transport("previous")
                        Icon { anchors.centerIn: parent; name: "skip-back"; size: 22 }
                    }
                    Pressable {
                        x: parent.fr + 10
                        width: parent.fr * 1.3
                        height: 72
                        radius: 20
                        color: Theme.accent
                        onClicked: root.transport("toggle")
                        Icon {
                            anchors.centerIn: parent
                            name: root.music && root.music.is_playing ? "pause" : "play"
                            size: 24
                            filled: true
                            color: Theme.accentInk
                        }
                    }
                    Pressable {
                        x: parent.fr * 2.3 + 20
                        width: parent.fr
                        height: 72
                        radius: 20
                        color: Theme.surface2
                        onClicked: root.transport("next")
                        Icon { anchors.centerIn: parent; name: "skip-forward"; size: 22 }
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: parent.height - y
            radius: Theme.radiusTile
            color: Theme.surface

            Column {
                x: 22
                y: 22
                width: parent.width - 44
                spacing: 16

                Txt {
                    text: "COMING UP"
                    color: Theme.muted
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.5
                }

                Txt {
                    visible: root.upcoming.length === 0
                    text: "Nothing on the way."
                    color: Theme.muted
                    font.pixelSize: 17
                }

                Column {
                    width: parent.width
                    spacing: 12

                    Repeater {
                        model: root.upcoming

                        Item {
                            id: item
                            required property var modelData
                            width: parent.width
                            height: info.implicitHeight

                            Txt {
                                width: 88
                                text: { root.tick; return Time.upcomingTime(item.modelData.iso) }
                                color: Theme.accent
                                font.weight: Font.Bold
                                tabular: true
                            }
                            Column {
                                id: info
                                x: 104
                                width: parent.width - 104
                                spacing: 2

                                Txt {
                                    width: parent.width
                                    text: item.modelData.title
                                    elide: Text.ElideRight
                                    font.weight: Font.DemiBold
                                }
                                Txt {
                                    width: parent.width
                                    text: item.modelData.meta
                                    elide: Text.ElideRight
                                    color: Theme.muted
                                    font.pixelSize: 16
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── Sheets ──────────────────────────────────────────────────────────────

    Loader {
        active: root.addOpen
        sourceComponent: AddTileSheet {
            items: root.candidates()
            onPicked: function (id) { root.addTile(id) }
            onClosed: root.addOpen = false
        }
    }

    Loader {
        active: root.sleepOpen
        sourceComponent: SleepSheet {
            onSleeping: root.sleepOpen = false
            onClosed: root.sleepOpen = false
        }
    }
}
