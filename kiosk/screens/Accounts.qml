import QtQuick
import "../theme"
import "../state"
import "../components"

// Add, rename, re-authorize and remove Google accounts by hand.
//
// All of this can be said to Wony in a sentence, but signing in cannot: it needs
// a browser window and a label typed in, and asking for that in prose is a worse
// version of a form. Every action here runs the same job the chat would have
// run, so nothing about accounts is implemented twice.
Item {
    id: root

    property var snapshot: null
    property bool loading: true
    property string error: ""
    property var editing: null
    property bool adding: false

    function load(first) {
        Api.fetchPanel("accounts", function (result) {
            root.snapshot = result.data
            if (first) {
                root.error = result.error || ""
                root.loading = false
            }
        })
    }

    // The list only re-reads after a change: accounts change when someone
    // changes them, not on their own.
    function close(changed) {
        editing = null
        adding = false
        if (changed)
            load(false)
    }

    Component.onCompleted: load(true)

    Component {
        id: empty

        Column {
            property string title
            property string body
            spacing: 8

            Txt {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: parent.title
                font.pixelSize: 30
                font.weight: Font.Bold
                font.letterSpacing: -0.3
                lh: 1.15
                wrapMode: Text.Wrap
            }
            Txt {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: parent.body
                color: Theme.muted
                lh: 1.4
                wrapMode: Text.Wrap
            }
        }
    }

    Txt {
        visible: root.loading
        anchors.centerIn: parent
        text: "Loading accounts…"
        color: Theme.muted
        lh: 1.4
    }

    Loader {
        active: !root.loading && root.snapshot === null
        anchors.centerIn: parent
        width: parent.width - 64
        sourceComponent: empty
        onLoaded: {
            item.title = "Accounts are switched off"
            item.body = root.error || "Add google_accounts to enabled_modules in config.yaml, then restart Wony."
        }
    }

    Loader {
        active: !root.loading && root.snapshot !== null && !root.snapshot.credentials_ready
        anchors.centerIn: parent
        width: parent.width - 64
        sourceComponent: empty
        onLoaded: {
            item.title = "Google isn't set up yet"
            item.body = "Create an OAuth client in Google Cloud Console, download it, and save it as credentials/google_credentials.json. Then come back here."
        }
    }

    Item {
        visible: !root.loading && root.snapshot !== null && root.snapshot.credentials_ready
        anchors.fill: parent

        Loader {
            active: parent.visible && root.snapshot.accounts.length === 0
            anchors.centerIn: parent
            width: parent.width - 64
            sourceComponent: empty
            onLoaded: {
                item.title = "No accounts yet"
                item.body = "Add one to let Wony read your mail and calendar."
            }
        }

        Scroller {
            id: list
            anchors.fill: parent
            anchors.bottomMargin: 74
            contentHeight: rows.implicitHeight + 16

            Column {
                id: rows
                x: 12
                y: 12
                width: list.width - 24
                spacing: 6

                Repeater {
                    model: root.snapshot ? root.snapshot.accounts : []

                    AccountRow {
                        required property var modelData
                        width: rows.width
                        account: modelData
                        services: root.snapshot.services
                        onClicked: root.editing = modelData
                    }
                }
            }
        }

        Pressable {
            x: 12
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            width: parent.width - 24
            height: 56
            radius: 28
            color: Theme.accent
            onClicked: root.adding = true

            Row {
                anchors.centerIn: parent
                spacing: 8
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "user-plus"; size: 20; color: Theme.accentInk }
                Txt { text: "Add account"; color: Theme.accentInk }
            }
        }
    }

    Loader {
        active: root.adding
        sourceComponent: AddAccountSheet {
            onFinished: function (changed) { root.close(changed) }
        }
    }

    Loader {
        active: root.editing !== null
        sourceComponent: AccountSheet {
            account: root.editing
            onFinished: function (changed) { root.close(changed) }
        }
    }
}
