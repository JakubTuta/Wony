import QtQuick
import "../state"

// A vertical Flickable without rubber-banding, that keeps the field being typed
// into above the on-screen keyboard.
Flickable {
    id: root

    // The on-screen keyboard is open on a field inside this scroller.
    property bool keyboardInside: false

    clip: true
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.VerticalFlick
    contentWidth: width
    // Room to scroll the last field up past the keyboard.
    bottomMargin: keyboardInside ? Ui.keyboardInset : 0

    function _owns(item) {
        for (var p = item; p; p = p.parent) {
            if (p === root.contentItem)
                return true
        }
        return false
    }

    function reveal(item) {
        if (!item || !Ui.overlay)
            return
        var covered = Math.max(0, root.mapToItem(Ui.overlay, 0, root.height).y
                               - (Ui.overlay.height - Ui.keyboardInset))
        var top = item.mapToItem(root.contentItem, 0, 0).y - 24
        var bottom = item.mapToItem(root.contentItem, 0, item.height).y + 24
        var target = root.contentY
        if (bottom > root.contentY + root.height - covered)
            target = bottom - (root.height - covered)
        if (top < target)
            target = top
        slide.to = Math.max(-root.topMargin, target)
        slide.restart()
    }

    NumberAnimation {
        id: slide
        target: root
        property: "contentY"
        duration: 180
        easing.type: Easing.OutCubic
    }

    Connections {
        target: Ui
        function onKeyTargetChanged() {
            root.keyboardInside = Ui.keyTarget !== null && root._owns(Ui.keyTarget)
            if (root.keyboardInside)
                Qt.callLater(function () { root.reveal(Ui.keyTarget) })
        }
    }
}
