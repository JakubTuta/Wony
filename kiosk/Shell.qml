import QtQuick
import "theme"
import "state"
import "components"
import "screens"

// The 1280x800 panel: header, one screen at a time, the nav bar, and everything
// that can sit above them (sheets, toast, confirm, keyboard, idle clock, sleep).
Item {
    id: shell

    property string tab: "home"
    property bool editing: false
    property bool notifOpen: false

    readonly property int idleMinutes: Wony.config ? Wony.config.kiosk.idle_minutes : 15

    function changeTab(next) {
        tab = next
        editing = false
    }

    // Any touch counts as activity. A passive handler: it sees every press
    // without taking it from the tile underneath.
    PointHandler {
        onActiveChanged: {
            if (active && !Ui.idle)
                idleTimer.restart()
        }
    }

    // Idle after kiosk.idle_minutes of nobody touching the panel; 0 turns it off.
    Timer {
        id: idleTimer
        interval: Math.max(1, shell.idleMinutes) * 60000
        running: shell.idleMinutes > 0 && !Ui.idle && !Wony.sleep.asleep
        onTriggered: Ui.idle = true
    }

    function wake() {
        Ui.idle = false
        idleTimer.restart()
    }

    Header {
        id: header
        width: parent.width
        tab: shell.tab
        editing: shell.editing
        onToggleEdit: shell.editing = !shell.editing
        onOpenNotifications: shell.notifOpen = true
        onOpenSystem: shell.changeTab("system")
    }

    Item {
        id: main
        x: 32
        y: header.height + 4
        width: parent.width - 64
        height: nav.y - y - 24

        Loader {
            anchors.fill: parent
            active: shell.tab === "home"
            source: "screens/Home.qml"
            onLoaded: item.editing = Qt.binding(function () { return shell.editing })
        }
        Loader {
            anchors.fill: parent
            active: shell.tab === "rooms"
            source: "screens/Rooms.qml"
        }
        Loader {
            anchors.fill: parent
            active: shell.tab === "music"
            source: "screens/Music.qml"
        }
        Loader {
            anchors.fill: parent
            active: shell.tab === "macros"
            source: "screens/Macros.qml"
        }
        Loader {
            id: system
            anchors.fill: parent
            active: shell.tab === "system"
            source: "screens/System.qml"
        }
        Connections {
            target: system.item
            function onSleeping() { shell.changeTab("home") }
        }
    }

    NavBar {
        id: nav
        y: parent.height - height
        width: parent.width
        tab: shell.tab
        onChanged: function (next) { shell.changeTab(next) }
    }

    // Sheets move themselves in here, above the header and nav bar.
    Item {
        id: overlayLayer
        anchors.fill: parent
        z: 40
        Component.onCompleted: Ui.overlay = overlayLayer
    }

    Loader {
        active: shell.notifOpen
        sourceComponent: NotificationsSheet {
            onClosed: shell.notifOpen = false
        }
    }

    Loader {
        active: Ui.confirmRequest !== null
        sourceComponent: ConfirmSheet {
            request: Ui.confirmRequest
            onCanceled: Ui.confirmRequest = null
            onConfirmed: {
                var done = Ui.confirmRequest.onConfirm
                Ui.confirmRequest = null
                done()
            }
        }
    }

    Toast {
        z: 30
        x: (shell.width - width) / 2
        text: Ui.toastText
    }

    Keyboard {
        z: 44
        width: parent.width
    }

    // Never over a sheet in progress, and outranked only by sleep.
    Loader {
        active: Ui.idle && !Wony.sleep.asleep && !shell.notifOpen
        anchors.fill: parent
        z: 50
        sourceComponent: Ambient {
            onWake: shell.wake()
        }
    }

    // Above everything: asleep outranks idle.
    Loader {
        active: Wony.sleep.asleep
        anchors.fill: parent
        z: 60
        sourceComponent: SleepOverlay {
            onWake: {
                Wony.wakeUp()
                shell.wake()
            }
        }
    }

    // At boot the panel is up before the assistant is.
    Rectangle {
        visible: Wony.config === null
        anchors.fill: parent
        z: 100
        color: Theme.panel

        Txt {
            anchors.centerIn: parent
            text: "Starting Wony…"
            color: Theme.muted
            font.pixelSize: 30
            font.weight: Font.Bold
        }
    }
}
