pragma Singleton
import QtQuick
import "../lib/devices.mjs" as Devices
import "../lib/jobs.mjs" as Jobs

// Switching a Home Assistant device, for every screen that can: Home tiles, the
// device list and the map. Each is a request to /api/devices/control followed by
// a re-read, because Home Assistant confirms a call before the state settles.
QtObject {
    // Straight to the device. Says why in a toast when it did not work.
    function send(entityId, action, value, option) {
        Api.controlDevice(entityId, action, value, option, function (result) {
            Live.devices.refresh()
            if (!result.ok)
                Ui.toast(result.text)
        })
    }

    // An action on a control that may have to be confirmed: a lock or an alarm
    // always asks, and so does everything when Settings says so.
    function guarded(control, name, action, yesLabel) {
        var confirmAll = Wony.config ? Wony.config.kiosk.confirm_all_devices : false
        if (!Devices.needsConfirm(control, confirmAll)) {
            send(control.entity_id, action, undefined, undefined)
            return
        }
        var spoken = name.toLowerCase()
        Ui.confirm({
            title: Devices.confirmPhrase(action, spoken, control.on),
            sig: Jobs.signature("control_home_device", { target: spoken, action: action }),
            yesLabel: yesLabel,
            onConfirm: function () { send(control.entity_id, action, undefined, undefined) }
        })
    }

    // What describeTile (lib/tiles.mjs) returns as a tile's tap: a notice, or a
    // device action that may have to be confirmed first.
    function tap(action) {
        if (action.type === "notice") {
            Ui.toast(action.text)
            return
        }
        var go = function () {
            Api.controlDevice(action.entityId, action.action, undefined, undefined, function (result) {
                Live.devices.refresh()
                if (action.confirm)
                    Ui.toast(result.text || action.name + " " + action.action + ".")
            })
        }
        if (action.confirm)
            Ui.confirm({ title: action.confirm.title, sig: action.confirm.sig, yesLabel: action.confirm.yesLabel, onConfirm: go })
        else
            go()
    }
}
