pragma Singleton
import QtQuick

// What sits above every screen: the toast, the confirm sheet, the keyboard and
// the idle flag. Any tile can ask for one without threading callbacks through
// the screens.
QtObject {
    id: ui

    // The full-frame layer that sheets reparent into, so they cover the header
    // and nav bar as well as their own screen. Set by Shell.
    property Item overlay: null

    // True once nobody has touched the panel for kiosk.idle_minutes.
    property bool idle: false

    property string toastText: ""
    // { title, sig, yesLabel, onConfirm } or null.
    property var confirmRequest: null

    // The Field that has the on-screen keyboard, and how much of the frame's
    // bottom the keyboard covers.
    property var keyTarget: null
    property int keyboardInset: 0

    function toast(text) {
        toastText = text
        toastTimer.restart()
    }

    function confirm(request) {
        confirmRequest = request
    }

    property Timer _toastTimer: Timer {
        id: toastTimer
        interval: 2600
        onTriggered: ui.toastText = ""
    }
}
