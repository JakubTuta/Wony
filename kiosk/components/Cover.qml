import QtQuick
import QtQuick.Shapes
import "../theme"

// Album art with rounded corners, or a music note while there is none. The
// corners are a ring of `backdrop` colour drawn over the square image: cheaper
// than masking it, which would render the picture into an offscreen texture.
Item {
    id: root

    property url source
    property real radius: 16
    // The colour behind the cover, so the corner ring blends in.
    property color backdrop: Theme.surface
    property real noteSize: 28

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: Theme.surface2
    }

    Icon {
        anchors.centerIn: parent
        visible: art.status !== Image.Ready
        name: "music"
        size: root.noteSize
        color: Theme.muted
        opacity: 0.5
    }

    Image {
        id: art
        anchors.fill: parent
        source: root.source
        asynchronous: true
        fillMode: Image.PreserveAspectCrop
        // Decoded at the size it is shown, not at the 640 px Spotify sends.
        sourceSize.width: root.width
        sourceSize.height: root.height
    }

    Shape {
        anchors.fill: parent
        visible: art.status === Image.Ready
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: root.backdrop
            strokeColor: "transparent"
            fillRule: ShapePath.OddEvenFill

            PathSvg {
                readonly property real w: root.width
                readonly property real h: root.height
                readonly property real r: root.radius
                path: "M0 0H" + w + "V" + h + "H0Z"
                    + " M" + r + " 0H" + (w - r) + "A" + r + " " + r + " 0 0 1 " + w + " " + r
                    + "V" + (h - r) + "A" + r + " " + r + " 0 0 1 " + (w - r) + " " + h
                    + "H" + r + "A" + r + " " + r + " 0 0 1 0 " + (h - r)
                    + "V" + r + "A" + r + " " + r + " 0 0 1 " + r + " 0Z"
            }
        }
    }
}
