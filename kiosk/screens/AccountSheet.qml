import QtQuick
import "../theme"
import "../state"
import "../components"

// Rename, re-authorize, make default or remove one Google account.
BottomSheet {
    id: root

    required property var account

    // Which action is running: rename, primary, authorize, remove, or "".
    property string busy: ""
    property bool confirmRemove: false
    property var result: null
    // Renaming or removing invalidates the name every other action here uses, so
    // those close the sheet rather than leaving it pointing at nothing.
    property bool modified: false

    signal finished(bool changed)

    title: account.name
    subtitle: account.email || "Not signed in yet"
    onClosed: root.finished(root.modified)

    function run(kind, args, thenClose) {
        busy = kind
        result = null
        Api.invokeJob("manage_google_accounts", args, function (response) {
            root.busy = ""
            root.modified = true
            if (response.ok && thenClose) {
                root.finished(true)
                return
            }
            root.result = {
                text: response.ok ? response.result || "Done." : response.error || "Failed.",
                ok: response.ok
            }
        })
    }

    function rename() {
        var next = newName.text.trim()
        if (!next || next === account.name)
            return
        run("rename", { action: "rename", name: account.name, new_name: next }, true)
    }

    Column {
        width: parent.width
        spacing: 4

        Txt {
            text: "Name"
            color: Theme.muted
            font.pixelSize: 15
            font.weight: Font.DemiBold
            lh: 1.4
        }
        Field {
            id: newName
            width: parent.width
            text: root.account.name
            placeholder: root.account.name
            onEdited: function (next) { newName.text = next }
            onAccepted: root.rename()
        }
    }

    Action {
        visible: newName.text.trim() !== root.account.name && newName.text.trim() !== ""
        width: parent.width
        label: "Save new name"
        busy: root.busy === "rename"
        enabled: root.busy === ""
        onActivated: root.rename()
    }

    Action {
        visible: !root.account.primary
        width: parent.width
        icon: "star"
        label: "Make this the default account"
        busy: root.busy === "primary"
        enabled: root.busy === ""
        onActivated: root.run("primary", { action: "set_primary", name: root.account.name }, true)
    }

    Action {
        width: parent.width
        icon: "refresh-cw"
        label: root.account.needs_sign_in ? "Sign in" : "Sign in again"
        busy: root.busy === "authorize"
        enabled: root.busy === ""
        onActivated: root.run("authorize", { action: "authorize", name: root.account.name }, false)
    }
    Txt {
        visible: root.account.needs_sign_in
        width: parent.width
        text: "Google signed Wony out of this account. Mail and calendar for it pause until you sign in again."
        color: Theme.warn
        font.pixelSize: 15
        font.weight: Font.DemiBold
        wrapMode: Text.Wrap
        lh: 1.4
    }

    Action {
        width: parent.width
        icon: "trash-2"
        danger: true
        label: root.confirmRemove ? "Yes, remove it" : "Remove account"
        busy: root.busy === "remove"
        enabled: root.busy === ""
        onActivated: {
            if (!root.confirmRemove) {
                root.confirmRemove = true
                return
            }
            root.run("remove", { action: "remove", name: root.account.name }, true)
        }
    }
    Txt {
        visible: root.confirmRemove && root.busy === ""
        width: parent.width
        text: "This deletes the saved sign-in. Wony stops reading this account's mail and calendar."
        color: Theme.muted
        font.pixelSize: 15
        font.weight: Font.DemiBold
        wrapMode: Text.Wrap
        lh: 1.4
    }

    SigningIn {
        visible: root.busy === "authorize"
        width: parent.width
    }
    Txt {
        visible: root.result !== null
        width: parent.width
        text: root.result ? root.result.text : ""
        color: root.result && !root.result.ok ? Theme.danger : Theme.text
        wrapMode: Text.Wrap
        lh: 1.4
    }
}
