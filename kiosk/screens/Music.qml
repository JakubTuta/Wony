import QtQuick
import "../theme"
import "../state"
import "../components"
import "../lib/time.mjs" as Time

// Now playing: cover, transport, volume and a few playlists.
Item {
    id: root

    readonly property var track: Live.music.data
    readonly property bool active: track !== null && track.active === true
    readonly property var devices: Live.library.data ? Live.library.data.devices : []
    readonly property var playlists: Live.library.data ? Live.library.data.playlists.slice(0, 4) : []

    property bool busy: false
    // When the last poll arrived, and a once-a-second tick while playing, so the
    // labels advance between 5 s polls. The bar itself runs on one animation.
    property real fetchedAt: Date.now()
    property int tick: 0

    function progressMs() {
        root.tick
        if (!track)
            return 0
        return Math.min((track.progress_ms || 0) + (Date.now() - fetchedAt), track.duration_ms || 0)
    }

    // Park the bar where the track is now and let it run to the end.
    function syncBar() {
        fill.stop()
        var duration = track ? track.duration_ms || 0 : 0
        var done = track ? track.progress_ms || 0 : 0
        bar.width = duration > 0 ? trackBar.width * Math.min(done / duration, 1) : 0
        if (track && track.is_playing && duration > done) {
            fill.to = trackBar.width
            fill.duration = duration - done
            fill.restart()
        }
    }

    function act(name, args) {
        busy = true
        Api.invokeJob(name, args, function () {
            root.busy = false
            refreshLater.restart()
        })
    }

    Connections {
        target: Live.music
        function onDataChanged() {
            root.fetchedAt = Date.now()
            root.syncBar()
        }
    }

    Timer {
        id: refreshLater
        interval: 400
        onTriggered: Live.music.refresh()
    }

    Timer {
        running: root.active && root.track.is_playing === true
        repeat: true
        interval: 1000
        onTriggered: root.tick++
    }

    Txt {
        visible: !Live.music.loaded
        anchors.centerIn: parent
        text: "…"
        color: Theme.muted
    }

    Column {
        visible: Live.music.loaded && !root.active
        anchors.centerIn: parent
        width: parent.width - 80
        spacing: 12

        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            name: "music"
            size: 40
            color: Theme.muted
            opacity: 0.4
        }
        Txt {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Nothing playing"
            font.pixelSize: 30
            font.weight: Font.Bold
            font.letterSpacing: -0.3
            lh: 1.15
        }
        Txt {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Theme.muted
            font.pixelSize: 19
            lh: 1.4
            text: "Start something on any Spotify device — or run a routine that does — and it shows up here."
        }
    }

    Item {
        visible: Live.music.loaded && root.active
        anchors.fill: parent

        Column {
            width: 340
            spacing: 16

            Cover {
                width: 340
                height: 340
                radius: Theme.radiusTile
                backdrop: Theme.panel
                noteSize: 48
                source: root.track && root.track.art_url ? root.track.art_url : ""
            }

            Txt {
                text: "PLAYING ON"
                color: Theme.muted
                font.pixelSize: 15
                font.weight: Font.DemiBold
                font.letterSpacing: 1.5
            }

            Flow {
                width: parent.width
                spacing: 10

                Repeater {
                    model: root.devices

                    Pressable {
                        id: device
                        required property var modelData
                        height: 60
                        width: deviceName.implicitWidth + 40
                        radius: 30
                        color: modelData.active ? Theme.text : Theme.surface
                        onClicked: root.act("control_playback", { action: "transfer", value: modelData.name })

                        Txt {
                            id: deviceName
                            anchors.centerIn: parent
                            text: device.modelData.name
                            color: device.modelData.active ? Theme.panel : Theme.text
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                        }
                    }
                }
                Txt {
                    visible: root.devices.length === 0
                    text: "No devices found."
                    color: Theme.muted
                    font.pixelSize: 16
                }
            }
        }

        Column {
            x: 372
            width: parent.width - 372
            spacing: 22

            Column {
                width: parent.width
                spacing: 6

                Txt {
                    width: parent.width
                    text: root.track ? root.track.title || "" : ""
                    elide: Text.ElideRight
                    font.pixelSize: 48
                    font.weight: Font.Bold
                    font.letterSpacing: -0.96
                }
                Txt {
                    width: parent.width
                    text: root.track ? (root.track.artist || "") + (root.track.album ? " · " + root.track.album : "") : ""
                    elide: Text.ElideRight
                    color: Theme.muted
                    font.pixelSize: 24
                }
            }

            Column {
                width: parent.width
                spacing: 8

                Rectangle {
                    id: trackBar
                    width: parent.width
                    height: 10
                    radius: 5
                    color: Theme.surface
                    clip: true

                    onWidthChanged: root.syncBar()

                    Rectangle {
                        id: bar
                        height: parent.height
                        radius: 5
                        color: Theme.accent
                        NumberAnimation on width {
                            id: fill
                            running: false
                            easing.type: Easing.Linear
                        }
                    }
                }
                Item {
                    width: parent.width
                    height: timeLeft.implicitHeight

                    Txt {
                        id: timeLeft
                        text: Time.clockFromMs(root.progressMs())
                        color: Theme.muted
                        font.pixelSize: 17
                        tabular: true
                    }
                    Txt {
                        anchors.right: parent.right
                        text: Time.clockFromMs(root.track ? root.track.duration_ms || 0 : 0)
                        color: Theme.muted
                        font.pixelSize: 17
                        tabular: true
                    }
                }
            }

            Item {
                id: transport
                width: parent.width
                height: 112

                // '1fr 1.2fr 1.6fr 1.2fr 1fr' with 12 px gaps.
                readonly property real fr: (width - 48) / 6
                readonly property bool on: root.track !== null && root.track.is_playing === true

                Pressable {
                    x: 0
                    anchors.verticalCenter: parent.verticalCenter
                    width: transport.fr
                    height: 88
                    radius: 24
                    color: root.track && root.track.shuffle ? Theme.accent : Theme.surface2
                    opacity: root.busy ? 0.4 : 1
                    onClicked: root.act("control_playback", { action: "shuffle" })
                    Icon {
                        anchors.centerIn: parent
                        name: "shuffle"
                        size: 20
                        color: root.track && root.track.shuffle ? Theme.accentInk : Theme.text
                    }
                }
                Pressable {
                    x: transport.fr + 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: transport.fr * 1.2
                    height: 100
                    radius: 24
                    color: Theme.surface2
                    opacity: root.busy ? 0.4 : 1
                    onClicked: root.act("control_playback", { action: "previous" })
                    Icon { anchors.centerIn: parent; name: "skip-back"; size: 28 }
                }
                Pressable {
                    x: transport.fr * 2.2 + 24
                    anchors.verticalCenter: parent.verticalCenter
                    width: transport.fr * 1.6
                    height: 112
                    radius: Theme.radiusTile
                    color: Theme.accent
                    opacity: root.busy ? 0.4 : 1
                    onClicked: root.act("control_playback", { action: "toggle" })
                    Icon {
                        anchors.centerIn: parent
                        name: transport.on ? "pause" : "play"
                        size: 34
                        filled: true
                        color: Theme.accentInk
                    }
                }
                Pressable {
                    x: transport.fr * 3.8 + 36
                    anchors.verticalCenter: parent.verticalCenter
                    width: transport.fr * 1.2
                    height: 100
                    radius: 24
                    color: Theme.surface2
                    opacity: root.busy ? 0.4 : 1
                    onClicked: root.act("control_playback", { action: "next" })
                    Icon { anchors.centerIn: parent; name: "skip-forward"; size: 28 }
                }
                Pressable {
                    x: transport.fr * 5 + 48
                    anchors.verticalCenter: parent.verticalCenter
                    width: transport.fr
                    height: 88
                    radius: 24
                    color: root.track && root.track.liked ? Theme.accent : Theme.surface2
                    opacity: root.busy ? 0.4 : 1
                    onClicked: root.act("control_playback", { action: root.track && root.track.liked ? "unlike" : "like" })
                    Icon {
                        anchors.centerIn: parent
                        name: "heart"
                        size: 20
                        filled: root.track !== null && root.track.liked === true
                        color: root.track && root.track.liked ? Theme.accentInk : Theme.text
                    }
                }
            }

            Item {
                width: parent.width
                height: 72

                TextButton {
                    width: 88
                    height: 72
                    radius: 20
                    text: "−"
                    textSize: 34
                    textWeight: Font.Medium
                    onClicked: root.act("set_volume", { direction: "down" })
                }
                Column {
                    x: 104
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 208
                    spacing: 6

                    Rectangle {
                        width: parent.width
                        height: 14
                        radius: 7
                        color: Theme.surface
                        clip: true

                        Rectangle {
                            height: parent.height
                            radius: 7
                            width: parent.width * Math.max(0, Math.min(100, root.track && root.track.volume ? root.track.volume : 0)) / 100
                            color: Theme.text
                        }
                    }
                    Txt {
                        text: "Volume " + (root.track && root.track.volume ? root.track.volume : 0)
                        color: Theme.muted
                        font.pixelSize: 16
                    }
                }
                TextButton {
                    anchors.right: parent.right
                    width: 88
                    height: 72
                    radius: 20
                    text: "+"
                    textSize: 34
                    textWeight: Font.Medium
                    onClicked: root.act("set_volume", { direction: "up" })
                }
            }

            Row {
                spacing: 12

                Repeater {
                    model: root.playlists

                    Pressable {
                        id: playlist
                        required property var modelData
                        width: (root.width - 372 - 36) / 4
                        height: 76
                        radius: 20
                        color: Theme.surface
                        onClicked: root.act("play_songs", { title: modelData.name, content_type: "playlist" })

                        Txt {
                            x: 18
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 36
                            text: playlist.modelData.name
                            elide: Text.ElideRight
                            font.pixelSize: 19
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }
        }
    }
}
