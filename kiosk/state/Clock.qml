pragma Singleton
import QtQuick

// The current time, updated once a minute on the minute boundary. Nothing on
// the panel shows seconds, and a repaint every second on a Pi is a repaint
// every second for nothing.
QtObject {
    id: clock

    property date now: new Date()

    property Timer _tick: Timer {
        running: true
        interval: 60000 - (Date.now() % 60000) + 50
        onTriggered: {
            clock.now = new Date()
            interval = 60000 - (Date.now() % 60000) + 50
            restart()
        }
    }
}
