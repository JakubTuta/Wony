import QtQuick

// One /api/panel/<key> read, refreshed on an interval. refresh() is also called
// right after an action: Home Assistant confirms a service call before the
// state settles, so acting is always followed by a re-read rather than a guess.
QtObject {
    id: panel

    property string key
    // Milliseconds between reads; 0 or less reads once.
    property int interval: 0
    // False while the panel is asleep or showing the idle clock.
    property bool active: true

    property var data: null
    property var error: null
    property bool loaded: false

    // Delegates only rebuild when the answer actually changed.
    property string _last: ""

    function refresh() {
        Api.fetchPanel(key, function (result) {
            panel.loaded = true
            var json = JSON.stringify(result)
            if (json === panel._last)
                return
            panel._last = json
            panel.data = result.data
            panel.error = result.error
        })
    }

    onActiveChanged: {
        if (active)
            refresh()
    }

    Component.onCompleted: {
        if (active)
            refresh()
    }

    property Timer _timer: Timer {
        interval: panel.interval
        repeat: true
        running: panel.active && panel.interval > 0
        onTriggered: panel.refresh()
    }
}
