import QtQuick
import "../theme"
import "../components"

// Shown while a consent flow is open. The browser window opens over the panel,
// so the screen says where the sign-in actually went.
Column {
    spacing: 8

    Spinner {
        anchors.horizontalCenter: parent.horizontalCenter
        size: 22
        color: Theme.accent
    }
    Txt {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "Finish signing in in the browser window."
        wrapMode: Text.Wrap
        lh: 1.4
    }
    Txt {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "Pick the Google account you want, then come back here."
        color: Theme.muted
        font.pixelSize: 15
        font.weight: Font.DemiBold
        wrapMode: Text.Wrap
        lh: 1.4
    }
}
