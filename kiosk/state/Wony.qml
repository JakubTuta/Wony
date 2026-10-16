pragma Singleton
import QtQuick
import QtWebSockets

// The connection to Wony: config, the notification list, deep sleep, and the
// one WebSocket every runPrompt() shares.
QtObject {
    id: wony

    readonly property var awake: ({
        asleep: false, since: null, wake_at: null, display: "", paused_jobs: [], last_wake: null
    })

    // null until /api/config first answers: the panel shows "Starting Wony"
    // meanwhile, because at boot it comes up before the assistant does.
    property var config: null
    property bool connected: false
    property var notifications: []
    readonly property int unreadCount: notifications.length
    // Deep sleep lives here because every client sleeps together: the server
    // broadcasts it, and a second screen must not stay lit.
    property var sleep: awake

    // Every runPrompt() in flight, by its own session id. A tile tap and a
    // routine from Macros can wait at once, and turn frames go to every client.
    property var _pending: ({})
    property int _retryDelay: 1000

    function start(apiUrl) {
        Api.base = apiUrl
        _loadConfig()
        socket.active = true
    }

    function _loadConfig() {
        Api.fetchConfig(function (config) {
            wony.config = config
        })
    }

    function _handle(event) {
        switch (event.type) {
        case "turn":
            _finish(event.session_id, { ok: true, text: event.assistant })
            break
        case "error":
            _finish(event.session_id, { ok: false, text: event.data })
            break
        case "sleep":
            sleep = event
            break
        case "notification":
            notifications = [event].concat(notifications)
            break
        default:
            // delta, state, cancel and diagnostics: the panel shows no live
            // transcript and no thinking indicator.
            break
        }
    }

    function _finish(sessionId, result) {
        var done = sessionId ? _pending[sessionId] : undefined
        if (!done)
            return
        delete _pending[sessionId]
        done(result)
    }

    function _onConnect() {
        Api.fetchNotifications(function (list) {
            wony.notifications = list
        })
        // A screen that restarted has to find out it is meant to be dark: the
        // sleep event only reaches clients that were connected when it fired.
        Api.fetchSleep(function (state) {
            if (state)
                wony.sleep = state
        })
    }

    // Sends a sentence through the agent, the only way a routine runs on a panel
    // with no keyboard of its own. done({ ok, text }) fires when the reply (or a
    // turn error) comes back.
    function runPrompt(message, done) {
        var text = message.trim()
        if (!text || !connected) {
            done({ ok: false, text: "Not connected." })
            return
        }
        var sid = Date.now() + "-" + Math.random().toString(36).slice(2, 8)
        _pending[sid] = done
        socket.sendTextMessage(JSON.stringify({ type: "chat", message: text, session_id: sid }))
    }

    function ack(id) {
        notifications = notifications.filter(function (n) { return n.id !== id })
        Api.ackNotification(id)
    }

    function ackAll() {
        notifications = []
        Api.ackAllNotifications()
    }

    // Optimistic: the overlay comes off on the touch, not on the round trip,
    // because the panel is already lighting up and a screen that stays black for
    // another 200 ms reads as a device that did not hear you.
    function wakeUp() {
        sleep = awake
        Api.endSleep(function (state) {
            if (state)
                wony.sleep = state
        })
    }

    property WebSocket _socket: WebSocket {
        id: socket
        url: Api.wsUrl
        active: false
        onStatusChanged: function (status) {
            if (status === WebSocket.Open) {
                wony._retryDelay = 1000
                wony.connected = true
                wony._onConnect()
            } else if (status === WebSocket.Closed || status === WebSocket.Error) {
                wony.connected = false
                if (!retry.running)
                    retry.start()
            }
        }
        onTextMessageReceived: function (message) {
            try {
                wony._handle(JSON.parse(message))
            } catch (e) {
                // A malformed frame: nothing useful to do with it.
            }
        }
    }

    // The Pi outlives its router, so reconnect for as long as it takes.
    property Timer _retry: Timer {
        id: retry
        interval: wony._retryDelay
        onTriggered: {
            wony._retryDelay = Math.min(wony._retryDelay * 2, 20000)
            socket.active = false
            socket.active = true
        }
    }

    // Until the assistant is up there is no config to wait on.
    property Timer _configRetry: Timer {
        interval: 2000
        repeat: true
        running: wony.config === null && Api.base !== ""
        onTriggered: wony._loadConfig()
    }
}
