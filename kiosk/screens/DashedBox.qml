import QtQuick
import QtQuick.Shapes
import "../theme"
import "../components"

// A dashed rounded outline (the "+ Add tile" slot): QML borders cannot dash.
Pressable {
    id: root

    property int lineWidth: 3
    property color lineColor: Theme.line

    function outline(w, h, r) {
        var x0 = lineWidth / 2, y0 = lineWidth / 2
        var x1 = w - lineWidth / 2, y1 = h - lineWidth / 2
        return "M" + (x0 + r) + " " + y0 + " H" + (x1 - r) + " A" + r + " " + r + " 0 0 1 " + x1 + " " + (y0 + r)
            + " V" + (y1 - r) + " A" + r + " " + r + " 0 0 1 " + (x1 - r) + " " + y1
            + " H" + (x0 + r) + " A" + r + " " + r + " 0 0 1 " + x0 + " " + (y1 - r)
            + " V" + (y0 + r) + " A" + r + " " + r + " 0 0 1 " + (x0 + r) + " " + y0 + " Z"
    }

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeColor: root.lineColor
            strokeWidth: root.lineWidth
            strokeStyle: ShapePath.DashLine
            dashPattern: [2, 2]
            fillColor: "transparent"

            PathSvg {
                path: root.outline(root.width, root.height, root.radius - root.lineWidth / 2)
            }
        }
    }
}
