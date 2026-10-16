import QtQuick
import "../theme"
import "../state"

// Wony's own on-screen keyboard, docked to the bottom of the frame while a Field
// has focus. A key is [what it types or does, width in key units].
Rectangle {
    id: root

    readonly property bool open: Ui.keyTarget !== null
    property string mode: "abc"
    property bool shift: false

    readonly property int gap: 10
    readonly property int keyHeight: 72
    readonly property real unit: (width - 48 - 9 * gap) / 10
    readonly property var rows: layout(mode)

    height: 352
    color: Theme.panel
    y: open ? parent.height - height : parent.height
    visible: y < parent.height

    Behavior on y {
        NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
    }

    Binding {
        target: Ui
        property: "keyboardInset"
        value: root.open ? root.height : 0
    }

    onOpenChanged: {
        if (open) {
            mode = "abc"
            shift = false
        }
    }

    function chars(text, w) {
        return text.split(" ").map(function (c) { return [c, w === undefined ? 1 : w] })
    }

    function layout(page) {
        var bottom = function (left) {
            return [[left, 1.5], ["@mode:acc", 1.5], [",", 1], ["@space", 3], [".", 1], ["@done", 2]]
        }
        switch (page) {
        case "123":
            return [
                chars("1 2 3 4 5 6 7 8 9 0"),
                chars("- / : ; ( ) $ & @ \""),
                [["@mode:sym", 2]].concat(chars(". , ? ! ' _")).concat([["@back", 2]]),
                bottom("@mode:abc")
            ]
        case "sym":
            return [
                chars("[ ] { } # % ^ * + ="),
                chars("\\ | ~ < > € £ ¥ ° •"),
                [["@mode:123", 2]].concat(chars(". , ? ! ' \"")).concat([["@back", 2]]),
                bottom("@mode:abc")
            ]
        case "acc":
            return [
                chars("ą ć ę ł ń ó ś ź ż ß"),
                chars("à á â ä ç è é ê ë ì"),
                [["@shift", 1.5]].concat(chars("í î ï ñ ô ö ü")).concat([["@back", 1.5]]),
                bottom("@mode:abc")
            ]
        default:
            return [
                chars("q w e r t y u i o p"),
                chars("a s d f g h j k l"),
                [["@shift", 1.5]].concat(chars("z x c v b n m")).concat([["@back", 1.5]]),
                bottom("@mode:123")
            ]
        }
    }

    function label(key) {
        if (key.indexOf("@mode:") === 0)
            return { abc: "ABC", "123": "123", sym: "#+=", acc: "àé" }[key.slice(6)]
        if (key === "@done")
            return "Done"
        if (key === "@space")
            return ""
        return shift ? key.toUpperCase() : key
    }

    function press(key) {
        var target = Ui.keyTarget
        if (!target)
            return
        if (key === "@shift") {
            shift = !shift
        } else if (key === "@back") {
            target.backspace()
        } else if (key === "@space") {
            target.insertText(" ")
        } else if (key === "@done") {
            target.done()
        } else if (key.indexOf("@mode:") === 0) {
            mode = key.slice(6)
            shift = false
        } else {
            target.insertText(shift ? key.toUpperCase() : key)
            shift = false
        }
    }

    Rectangle {
        width: parent.width
        height: 1
        color: Theme.line
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 14
        spacing: root.gap

        Repeater {
            model: root.rows

            Row {
                id: keyRow
                required property var modelData
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: root.gap

                Repeater {
                    model: keyRow.modelData

                    Pressable {
                        id: key
                        required property var modelData
                        readonly property string id: modelData[0]
                        readonly property bool special: id.charAt(0) === "@"

                        width: modelData[1] * root.unit + (modelData[1] - 1) * root.gap
                        height: root.keyHeight
                        radius: 16
                        pressEffect: false
                        color: id === "@done" ? Theme.accent
                             : pressed ? Theme.line
                             : special && id !== "@space" ? Theme.surface : Theme.surface2

                        onClicked: root.press(id)
                        onPressedChanged: {
                            if (id === "@back" && pressed)
                                hold.restart()
                            else
                                hold.stop()
                        }

                        // Holding backspace keeps deleting.
                        Timer {
                            id: hold
                            interval: 400
                            repeat: true
                            onTriggered: {
                                interval = 60
                                root.press("@back")
                            }
                            onRunningChanged: if (!running) interval = 400
                        }

                        Txt {
                            anchors.centerIn: parent
                            visible: key.id !== "@back" && key.id !== "@shift"
                            text: root.label(key.id)
                            color: key.id === "@done" ? Theme.accentInk : Theme.text
                            font.pixelSize: key.special ? 22 : 32
                            font.weight: key.special ? Font.DemiBold : Font.Medium
                        }
                        Icon {
                            anchors.centerIn: parent
                            visible: key.id === "@back" || key.id === "@shift"
                            name: key.id === "@back" ? "delete" : "arrow-big-up"
                            filled: key.id === "@shift" && root.shift
                            size: 30
                        }
                    }
                }
            }
        }
    }
}
