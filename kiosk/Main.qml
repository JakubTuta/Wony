import QtQuick
import QtQuick.Window
import "theme"
import "state"

// Wony's touch panel. Run by wony.py panel:
//   qml6 kiosk/Main.qml -- --api http://127.0.0.1:8000 [--windowed]
//
// The panel is authored at 1280x800 and scaled as one object to whatever screen
// it runs on, on an always-black backdrop.
Window {
    id: win

    // Value after `name` on the command line, or "" when it is absent.
    function argument(name) {
        var args = Qt.application.arguments
        var at = args.indexOf(name)
        return at === -1 || at + 1 >= args.length ? "" : args[at + 1]
    }

    readonly property bool windowed: Qt.application.arguments.indexOf("--windowed") !== -1
    property bool ready: false

    title: "Wony"
    visible: true
    color: "black"
    width: Theme.frameWidth
    height: Theme.frameHeight
    visibility: windowed ? Window.Windowed : Window.FullScreen

    Component.onCompleted: {
        Wony.start(argument("--api") || "http://127.0.0.1:8000")
        ready = true
    }

    Rectangle {
        id: frame

        anchors.centerIn: parent
        width: Theme.frameWidth
        height: Theme.frameHeight
        scale: Math.min(win.width / width, win.height / height)
        color: Theme.panel
        clip: true

        Loader {
            anchors.fill: parent
            active: win.ready
            source: "Shell.qml"
        }
    }

    // No pointer on a touch panel.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        cursorShape: win.windowed ? Qt.ArrowCursor : Qt.BlankCursor
    }
}
