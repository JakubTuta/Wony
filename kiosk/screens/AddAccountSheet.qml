import QtQuick
import "../theme"
import "../state"
import "../components"

// Name a new Google account and sign it in.
BottomSheet {
    id: root

    property bool busy: false
    // { text, ok } once the job has answered.
    property var result: null

    // The account exists the moment add returns, whatever the sign-in did, so
    // the list behind is out of date either way.
    signal finished(bool changed)

    title: "Add account"
    subtitle: "Give it a short name"
    onClosed: root.finished(true)

    function add() {
        var label = name.text.trim()
        if (!label || busy)
            return
        busy = true
        result = null
        Api.invokeJob("manage_google_accounts", { action: "add", name: label }, function (response) {
            root.result = {
                text: response.ok ? response.result || "Done." : response.error || "Failed.",
                ok: response.ok
            }
            root.busy = false
        })
    }

    Field {
        id: name
        width: parent.width
        placeholder: "work, personal, …"
        onEdited: function (next) { name.text = next }
        onAccepted: root.add()
        Component.onCompleted: name.inner.forceActiveFocus()
    }
    Txt {
        width: parent.width
        text: "A label for you — the email address is filled in after you sign in."
        color: Theme.muted
        font.pixelSize: 15
        font.weight: Font.DemiBold
        wrapMode: Text.Wrap
        lh: 1.4
    }
    SigningIn {
        visible: root.busy
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

    footer: [
        Pressable {
            width: parent.width
            height: 56
            radius: 28
            color: Theme.accent
            opacity: enabled ? 1 : 0.5
            enabled: !root.busy && (root.result !== null || name.text.trim() !== "")
            onClicked: root.result ? root.finished(true) : root.add()

            Txt {
                anchors.centerIn: parent
                color: Theme.accentInk
                text: root.busy ? "Signing in…" : root.result ? "Done" : "Add and sign in"
            }
        }
    ]
}
