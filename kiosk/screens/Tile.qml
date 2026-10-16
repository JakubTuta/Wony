import QtQuick
import "../state"
import "../components"
import "../lib/tiles.mjs" as Tiles

// A Home tile that does one thing when tapped. What it shows and does comes
// from lib/tiles.mjs; Home carries out the action.
TileFrame {
    id: root

    required property string tileId
    // Home's once-a-second count; only timer tiles read it.
    property int tick: 0

    signal tapped(var action)

    readonly property bool counting: tileId.indexOf("timer:") === 0
    // Timer tiles recount every second; reading tick only for them keeps the rest still.
    readonly property real now: counting ? (tick, Date.now()) : Date.now()
    readonly property var info: {
        return Tiles.describeTile(tileId, {
            routines: Live.routines.data,
            devices: Live.devices.data,
            reminders: Live.reminders.data,
            music: Live.music.data,
            locksAllowed: Live.devices.data ? Live.devices.data.locks_allowed : false,
            confirmAllDevices: Wony.config ? Wony.config.kiosk.confirm_all_devices : false,
            now: now
        })
    }

    kindLabel: info.kindLabel
    active: info.active
    onClicked: if (!editing) tapped(info.action)

    Column {
        x: 24
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        width: parent.width - 48
        spacing: 6

        Txt {
            width: parent.width
            text: root.info.title
            color: root.ink
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            font.pixelSize: 30
            font.weight: Font.Bold
            font.letterSpacing: -0.3
            lh: 1.1
        }
        Txt {
            width: parent.width
            text: root.info.sub
            color: root.ink
            opacity: 0.85
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
            font.pixelSize: 19
            tabular: true
        }
    }
}
