import QtQuick
import "../theme"
import "../components"

// One Google account in the list: initial, name, address, and a chip per
// service that says whether its sign-in is good.
Pressable {
    id: root

    required property var account
    required property var services

    height: 66
    radius: 12
    color: Theme.surface
    border.width: 1
    border.color: Theme.line

    Rectangle {
        x: 16
        anchors.verticalCenter: parent.verticalCenter
        width: 40
        height: 40
        radius: 20
        color: Theme.surface2
        border.width: 1
        border.color: Theme.line

        Txt {
            anchors.centerIn: parent
            text: root.account.name.slice(0, 1).toUpperCase()
        }
    }

    Column {
        x: 68
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - 68 - chips.width - 32

        Row {
            spacing: 6

            Txt {
                id: nameText
                text: root.account.name
                lh: 1.4
                width: Math.min(implicitWidth, root.width - 68 - chips.width - 32 - (root.account.primary ? 20 : 0))
                elide: Text.ElideRight
            }
            Icon {
                visible: root.account.primary
                anchors.verticalCenter: parent.verticalCenter
                name: "star"
                size: 14
                color: Theme.accent
                filled: true
            }
        }
        Txt {
            width: parent.width
            elide: Text.ElideRight
            color: root.account.needs_sign_in ? Theme.warn : Theme.muted
            font.pixelSize: 15
            font.weight: Font.DemiBold
            lh: 1.4
            text: root.account.needs_sign_in ? "Needs signing in — tap to sign in again"
                : root.account.email || "Signed in"
        }
    }

    Row {
        id: chips
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6

        ServiceChip {
            visible: root.services.gmail
            icon: "mail"
            ok: !root.account.needs_sign_in && root.account.modules.gmail
        }
        ServiceChip {
            visible: root.services.calendar
            icon: "calendar"
            ok: !root.account.needs_sign_in && root.account.modules.calendar
        }
    }
}
