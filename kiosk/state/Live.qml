pragma Singleton
import QtQuick

// One poll per live panel, shared by the header, Home, Rooms, Music and
// Macros, so two screens never poll the same data side by side.
QtObject {
    id: live

    // Nothing is shown while asleep or idle, so nothing is fetched.
    readonly property bool polling: !Wony.sleep.asleep && !Ui.idle

    readonly property Panel weather: Panel { key: "weather"; interval: 10 * 60000; active: live.polling }
    readonly property Panel agenda: Panel { key: "agenda"; interval: 5 * 60000; active: live.polling }
    readonly property Panel reminders: Panel { key: "reminders"; interval: 30000; active: live.polling }
    readonly property Panel devices: Panel { key: "devices"; interval: 30000; active: live.polling }
    readonly property Panel music: Panel { key: "music"; interval: 5000; active: live.polling }
    readonly property Panel library: Panel { key: "music_library"; interval: 5 * 60000; active: live.polling }
    readonly property Panel routines: Panel { key: "routines"; interval: 5 * 60000; active: live.polling }
}
