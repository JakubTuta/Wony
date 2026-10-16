import QtQuick
import "../theme"
import "../state"

// A text field that types through Wony's own on-screen keyboard. `text` is set
// by the owner; `edited(text)` reports every change the person makes.
Rectangle {
    id: root

    property string text: ""
    property string placeholder: "not set"
    property bool multiline: false
    readonly property bool focused: input.activeFocus || area.activeFocus
    readonly property var inner: multiline ? area : input

    signal edited(string text)
    signal accepted()

    implicitHeight: multiline ? 108 : 48
    radius: 12
    color: Theme.surface2
    border.width: 1
    border.color: focused ? Theme.accent : Theme.line

    function insertText(s) {
        if (inner.selectedText)
            inner.remove(inner.selectionStart, inner.selectionEnd)
        inner.insert(inner.cursorPosition, s)
        root.edited(inner.text)
    }

    function backspace() {
        if (inner.selectedText)
            inner.remove(inner.selectionStart, inner.selectionEnd)
        else if (inner.cursorPosition > 0)
            inner.remove(inner.cursorPosition - 1, inner.cursorPosition)
        else
            return
        root.edited(inner.text)
    }

    // Done on the keyboard, or Enter on a real one.
    function done() {
        inner.focus = false
        if (Ui.keyTarget === root)
            Ui.keyTarget = null
        root.accepted()
    }

    onFocusedChanged: {
        if (focused)
            Ui.keyTarget = root
        else if (Ui.keyTarget === root)
            Ui.keyTarget = null
    }

    Component.onDestruction: {
        if (Ui.keyTarget === root)
            Ui.keyTarget = null
    }

    Txt {
        x: 16
        y: root.multiline ? 12 : (root.height - height) / 2
        text: root.placeholder
        color: Theme.muted
        lh: 1.4
        visible: root.inner.text.length === 0
    }

    TextInput {
        id: input
        visible: !root.multiline
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        verticalAlignment: TextInput.AlignVCenter
        clip: true
        text: root.text
        color: Theme.text
        font.family: Theme.fontDisplay
        font.pixelSize: 20
        font.weight: Font.Medium
        selectionColor: Theme.accent
        selectedTextColor: Theme.accentInk
        inputMethodHints: Qt.ImhNoPredictiveText
        activeFocusOnPress: false
        cursorDelegate: Rectangle { width: 2; color: Theme.accent }
        onTextEdited: root.edited(text)
        Keys.onReturnPressed: root.done()
    }

    TextEdit {
        id: area
        visible: root.multiline
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 12
        anchors.bottomMargin: 12
        wrapMode: TextEdit.Wrap
        clip: true
        text: root.text
        color: Theme.text
        font.family: Theme.fontDisplay
        font.pixelSize: 20
        font.weight: Font.Medium
        selectionColor: Theme.accent
        selectedTextColor: Theme.accentInk
        inputMethodHints: Qt.ImhNoPredictiveText
        activeFocusOnPress: false
        cursorDelegate: Rectangle { width: 2; color: Theme.accent }
        onTextChanged: if (activeFocus && text !== root.text) root.edited(text)
    }

    MouseArea {
        anchors.fill: parent
        onClicked: function (mouse) {
            root.inner.forceActiveFocus()
            if (root.multiline)
                area.cursorPosition = area.positionAt(mouse.x - area.x, mouse.y - area.y)
            else
                input.cursorPosition = input.positionAt(mouse.x - input.x)
        }
    }
}
