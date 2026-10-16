import QtQuick
import QtQuick.Shapes
import "../theme"
import "../icons/Icons.mjs" as Icons

// A lucide icon from Icons.mjs. `filled` fills the outline in the same colour
// (play, pause, heart, star). CurveRenderer keeps the curves smooth on the GPU
// at any size, without a texture per icon size.
Item {
    id: root

    property string name
    property real size: 24
    property color color: Theme.text
    property bool filled: false

    implicitWidth: size
    implicitHeight: size

    Shape {
        width: 24
        height: 24
        scale: root.size / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeColor: root.color
            strokeWidth: 2
            fillColor: root.filled ? root.color : "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathSvg {
                path: Icons.paths[root.name] || ""
            }
        }
    }
}
