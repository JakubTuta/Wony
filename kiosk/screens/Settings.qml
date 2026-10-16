import QtQuick
import "../theme"
import "../state"
import "../components"

// Everything in config.yaml that a person should be able to change, on the
// screen itself. The Pi has no text editor: without this, switching the AI
// provider or allowing Wony to send email means finding another computer and
// editing a file over SSH.
Item {
    id: root

    property var settings: null
    // key -> value for every field changed since the last save.
    property var draft: ({})
    property var modules: []
    property bool modulesTouched: false
    property bool saving: false
    property string error: ""
    property string saved: "none"
    property string update: ""

    readonly property bool dirty: Object.keys(draft).length > 0 || modulesTouched

    function enabledModules(settings) {
        return settings.modules.filter(function (m) { return m.enabled }).map(function (m) { return m.key })
    }

    function load() {
        Api.fetchSettings(function (r) {
            if (r.error) {
                root.error = r.error
                return
            }
            root.settings = r.data
            root.modules = root.enabledModules(r.data)
        })
    }

    function setValue(key, value) {
        saved = "none"
        var next = Object.assign({}, draft)
        next[key] = value
        draft = next
    }

    function valueOf(field) {
        return field.key in draft ? draft[field.key] : field.value
    }

    function toggleModule(key) {
        saved = "none"
        modulesTouched = true
        modules = modules.indexOf(key) === -1 ? modules.concat([key]) : modules.filter(function (m) { return m !== key })
    }

    function save() {
        saving = true
        error = ""
        Api.saveSettings(draft, modulesTouched ? modules : undefined, function (r) {
            if (r.error) {
                root.saving = false
                root.error = r.error
                return
            }
            Api.fetchSettings(function (fresh) {
                root.saving = false
                if (fresh.error) {
                    root.error = fresh.error
                    return
                }
                root.settings = fresh.data
                root.modules = root.enabledModules(fresh.data)
                root.draft = ({})
                root.modulesTouched = false
                root.saved = r.result.restart_required ? "restart" : "ok"
            })
        })
    }

    Component.onCompleted: load()

    Column {
        visible: root.error !== "" && root.settings === null
        anchors.centerIn: parent
        width: parent.width - 64
        spacing: 8

        Icon { anchors.horizontalCenter: parent.horizontalCenter; name: "triangle-alert"; size: 40; color: Theme.muted }
        Txt {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: root.error
            color: Theme.muted
            lh: 1.4
        }
    }

    Txt {
        visible: root.error === "" && root.settings === null
        anchors.centerIn: parent
        text: "Reading settings…"
        color: Theme.muted
        lh: 1.4
    }

    Scroller {
        id: scroller
        visible: root.settings !== null
        anchors.fill: parent
        anchors.bottomMargin: bar.height
        contentHeight: sections.implicitHeight + 32

        Column {
            id: sections
            x: 16
            y: 16
            width: scroller.width - 32
            spacing: 20

            Repeater {
                model: root.settings ? root.settings.sections : []

                Column {
                    id: section
                    required property var modelData
                    width: sections.width
                    spacing: 8

                    Txt {
                        x: 4
                        text: section.modelData.title.toUpperCase()
                        color: Theme.muted
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        font.letterSpacing: 0.4
                        lh: 1.4
                    }
                    Rectangle {
                        width: parent.width
                        height: rows.implicitHeight + 2
                        radius: 12
                        color: Theme.surface
                        border.width: 1
                        border.color: Theme.line
                        clip: true

                        Column {
                            id: rows
                            x: 1
                            y: 1
                            width: parent.width - 2

                            Repeater {
                                model: section.modelData.fields

                                SettingRow {
                                    required property var modelData
                                    required property int index
                                    width: rows.width
                                    field: modelData
                                    first: index === 0
                                    value: root.valueOf(modelData)
                                    onChanged: function (key, next) { root.setValue(key, next) }
                                }
                            }
                        }
                    }
                }
            }

            Column {
                width: parent.width
                spacing: 8

                Txt {
                    x: 4
                    text: "FEATURES"
                    color: Theme.muted
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.4
                    lh: 1.4
                }
                Txt {
                    x: 4
                    width: parent.width - 8
                    text: "Switching one on needs its packages installed — run ./wony.sh setup if something stays unavailable. These take effect after a restart."
                    color: Theme.muted
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                    lh: 1.4
                }
                Rectangle {
                    width: parent.width
                    height: featureRows.implicitHeight + 2
                    radius: 12
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.line
                    clip: true

                    Column {
                        id: featureRows
                        x: 1
                        y: 1
                        width: parent.width - 2

                        Repeater {
                            model: root.settings ? root.settings.modules : []

                            Item {
                                id: feature
                                required property var modelData
                                required property int index
                                width: featureRows.width
                                height: featureText.implicitHeight + 24

                                Rectangle {
                                    visible: feature.index > 0
                                    width: parent.width
                                    height: 1
                                    color: Theme.line
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: root.toggleModule(feature.modelData.key)
                                }
                                Switch {
                                    x: 16
                                    anchors.verticalCenter: parent.verticalCenter
                                    checked: root.modules.indexOf(feature.modelData.key) !== -1
                                }
                                Column {
                                    id: featureText
                                    x: 76
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 92

                                    Txt {
                                        width: parent.width
                                        text: feature.modelData.label
                                        elide: Text.ElideRight
                                        lh: 1.4
                                    }
                                    Txt {
                                        width: parent.width
                                        text: feature.modelData.help
                                        color: Theme.muted
                                        font.pixelSize: 15
                                        font.weight: Font.DemiBold
                                        wrapMode: Text.Wrap
                                        lh: 1.4
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Column {
                width: parent.width
                spacing: 8

                Txt {
                    x: 4
                    text: "UPDATES"
                    color: Theme.muted
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.4
                    lh: 1.4
                }
                Rectangle {
                    width: parent.width
                    height: updateColumn.implicitHeight + 24
                    radius: 12
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.line

                    Column {
                        id: updateColumn
                        x: 16
                        y: 12
                        width: parent.width - 32
                        spacing: 8

                        Pressable {
                            width: checkRow.implicitWidth + 32
                            height: 44
                            radius: 12
                            border.width: 1
                            border.color: Theme.line
                            onClicked: {
                                root.update = "Checking…"
                                Api.checkUpdates(function (message) { root.update = message })
                            }

                            Row {
                                id: checkRow
                                anchors.centerIn: parent
                                spacing: 8
                                Icon { anchors.verticalCenter: parent.verticalCenter; name: "download"; size: 18 }
                                Txt { text: "Check for updates" }
                            }
                        }
                        Txt {
                            visible: root.update !== ""
                            width: parent.width
                            text: root.update
                            color: Theme.muted
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            wrapMode: Text.Wrap
                            lh: 1.4
                        }
                    }
                }
            }

            Txt {
                visible: root.error !== ""
                x: 4
                width: parent.width - 8
                text: root.error
                color: Theme.danger
                wrapMode: Text.Wrap
                font.pixelSize: 15
                font.weight: Font.DemiBold
                lh: 1.4
            }

            Txt {
                x: 4
                width: parent.width - 8
                text: "These are stored in " + (root.settings ? root.settings.config_file : "") + ", which you can still edit by hand."
                color: Theme.muted
                wrapMode: Text.Wrap
                font.pixelSize: 15
                font.weight: Font.DemiBold
                lh: 1.4
            }
        }
    }

    // Pinned at the bottom, so Save is never scrolled out of reach.
    Rectangle {
        id: bar
        visible: root.settings !== null
        anchors.bottom: parent.bottom
        width: parent.width
        height: 76
        color: Theme.bg

        Row {
            x: 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12

            Pressable {
                width: saveLabel.implicitWidth + 40
                height: 56
                radius: 12
                color: Theme.accent
                opacity: !root.dirty || root.saving ? 0.4 : 1
                enabled: root.dirty && !root.saving
                onClicked: root.save()

                Txt {
                    id: saveLabel
                    anchors.centerIn: parent
                    text: root.saving ? "Saving…" : "Save changes"
                    color: Theme.bg
                    lh: 1.4
                }
            }
            Row {
                visible: root.saved !== "none"
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    name: root.saved === "restart" ? "rotate-cw" : "check"
                    size: 16
                    color: Theme.muted
                }
                Txt {
                    text: root.saved === "restart" ? "Saved — restart Wony for all of it to apply." : "Saved."
                    color: Theme.muted
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    lh: 1.4
                }
            }
        }
    }
}
