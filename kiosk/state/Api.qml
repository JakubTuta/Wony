pragma Singleton
import QtQuick

// Everything the panel can do goes through here, to the same /api/* the old
// web page used. Calls take a callback instead of returning a Promise (QML has
// none). Reads never throw: a screen always has something to render, and
// "Home Assistant is not enabled" is as much an answer as a device list.
QtObject {
    // http://127.0.0.1:8000, set by Main.qml from --api.
    property string base: ""
    readonly property string wsUrl: base.replace(/^http/, "ws") + "/api/ws"

    readonly property string failed: "That did not work."
    readonly property string unreachable: "Wony is not responding."

    // done(status, data): status 0 means nobody answered.
    function request(method, path, body, done) {
        var xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE)
                return
            var data = null
            try {
                data = JSON.parse(xhr.responseText)
            } catch (e) {
                data = null
            }
            if (done)
                done(xhr.status, data)
        }
        xhr.open(method, base + "/api" + path)
        if (body !== undefined)
            xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(body === undefined ? null : JSON.stringify(body))
    }

    function _detail(status, data) {
        if (status === 0)
            return unreachable
        return (data && data.detail) || failed
    }

    function fetchConfig(done) {
        request("GET", "/config", undefined, function (status, data) {
            done(status === 200 ? data : null)
        })
    }

    // The saved Home layout, or null when nobody has arranged one yet.
    function fetchKioskTiles(done) {
        request("GET", "/kiosk/tiles", undefined, function (status, data) {
            done(status === 200 && data ? data.tiles : null)
        })
    }

    function saveKioskTiles(tiles) {
        request("POST", "/kiosk/tiles", { tiles: tiles })
    }

    function fetchAmbient(done) {
        request("GET", "/ambient", undefined, function (status, data) {
            done(status === 200 && data && data.cards ? data.cards : [])
        })
    }

    function fetchNotifications(done) {
        request("GET", "/notifications?include_acknowledged=false", undefined, function (status, data) {
            done(status === 200 && data && data.notifications ? data.notifications : [])
        })
    }

    function ackNotification(id) {
        request("POST", "/notifications/" + id + "/ack")
    }

    function ackAllNotifications() {
        request("POST", "/notifications/ack-all")
    }

    // done({ data, error }): error is null when data is present.
    function fetchPanel(key, done) {
        request("GET", "/panel/" + key, undefined, function (status, data) {
            if (status === 200)
                done({ data: data, error: null })
            else
                done({ data: null, error: _detail(status, data) })
        })
    }

    // done({ ok, text })
    function controlDevice(entityId, action, value, option, done) {
        var body = { entity_id: entityId, action: action }
        if (value !== undefined)
            body.value = value
        if (option !== undefined)
            body.option = option
        request("POST", "/devices/control", body, function (status, data) {
            if (status === 200 && data)
                done(data)
            else
                done({ ok: false, text: _detail(status, data) })
        })
    }

    function fetchSleep(done) {
        request("GET", "/sleep", undefined, function (status, data) {
            done(status === 200 && data ? data : null)
        })
    }

    // wakeAt is "HH:MM", a duration like "8h", or "" for "until I touch it".
    // done({ state, error })
    function startSleep(wakeAt, done) {
        request("POST", "/sleep", { wake_at: wakeAt }, function (status, data) {
            if (status === 200)
                done({ state: data, error: null })
            else
                done({ state: null, error: _detail(status, data) })
        })
    }

    // Harmless when nothing is asleep: the overlay posts it on any touch.
    function endSleep(done) {
        request("POST", "/wake", undefined, function (status, data) {
            done(status === 200 && data ? data : null)
        })
    }

    // done({ ok, result, error })
    function invokeJob(name, args, done) {
        request("POST", "/invoke", { name: name, args: args }, function (status, data) {
            if (status === 200 && data)
                done(data)
            else
                done({ ok: false, result: "", error: (data && data.detail) || (status === 0 ? unreachable : "Request failed") })
        })
    }

    function fetchSettings(done) {
        request("GET", "/settings", undefined, function (status, data) {
            if (status === 200)
                done({ data: data, error: null })
            else
                done({ data: null, error: _detail(status, data) })
        })
    }

    // done({ result, error }): result is { written, restart_required }.
    function saveSettings(updates, modules, done) {
        request("POST", "/settings", { updates: updates, modules: modules === undefined ? null : modules },
                function (status, data) {
            if (status === 200)
                done({ result: data, error: null })
            else
                done({ result: null, error: (data && data.detail) || "Could not save those settings." })
        })
    }

    // One sentence about whether a newer Wony is waiting. Never updates anything.
    function checkUpdates(done) {
        request("GET", "/updates", undefined, function (status, data) {
            done(status === 200 && data ? data.message : "Could not check for updates.")
        })
    }
}
