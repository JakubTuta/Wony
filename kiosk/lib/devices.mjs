// Which widget a Home Assistant entity draws as, and the words around it.
// Pure functions, no Qt: `node --test kiosk/tests/` runs them.

// Locks and vacuums are never generic switches, whatever flags they also carry.
export function shapeFor(control) {
    if (control.domain === "lock" || control.domain === "alarm_control_panel") return "lock"
    if (control.domain === "vacuum") return "vacuum"
    if (control.domain === "cover" || control.domain === "valve") return "cover"
    if (control.domain === "climate" || control.domain === "water_heater") return "climate"
    if (control.press) return "press"
    if (control.toggle) return control.slider ? "toggle-level" : "toggle"
    if (control.options.length > 0) return "options"
    if (control.number) return "number"
    return "plain"
}

const DOMAIN_LABELS = {
    light: "Light",
    switch: "Switch",
    fan: "Fan",
    cover: "Blinds",
    valve: "Valve",
    lock: "Lock",
    climate: "Climate",
    water_heater: "Water heater",
    media_player: "Media",
    vacuum: "Vacuum",
    lawn_mower: "Mower",
    scene: "Scene",
    script: "Script",
    automation: "Automation",
    button: "Button",
    alarm_control_panel: "Alarm",
    humidifier: "Humidifier",
}

export function domainLabel(domain) {
    return DOMAIN_LABELS[domain] ?? domain.charAt(0).toUpperCase() + domain.slice(1)
}

export function cap(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1).replace(/_/g, " ") : text
}

// The state line under a device's name: what Home Assistant reports, plus a
// level or a setpoint when there is one.
export function stateText(control, shape) {
    switch (shape) {
    case "cover":
        if (control.level === null) return cap(control.state)
        if (control.level <= 0) return "Closed"
        if (control.level >= 100) return "Open"
        return "Open " + control.level + "%"
    case "climate":
        return control.current !== null
            ? "Now " + control.current + "° · " + cap(control.state)
            : cap(control.state)
    case "lock":
        return control.on ? "Unlocked" : "Locked"
    case "toggle-level":
        return control.on && control.level !== null
            ? cap(control.state) + " · " + control.level + "%"
            : cap(control.state)
    default:
        return cap(control.state)
    }
}

// One tap's worth of action for a Home tile: a tile has room for one gesture.
// The device list draws its own per-shape controls instead.
export function primaryAction(control) {
    switch (control.domain) {
    case "cover":
    case "valve":
        return control.level !== null && control.level > 0 ? "close" : "open"
    case "lock":
    case "alarm_control_panel":
        return control.on ? "lock" : "unlock"
    case "vacuum":
        return control.on ? "dock" : "start"
    default:
        return control.press ? "on" : "toggle"
    }
}

// Locks and alarms always ask first; the Settings switch makes everything ask.
export function needsConfirm(control, confirmAllDevices) {
    return control.guarded || confirmAllDevices
}

// The confirm sheet's question, phrased for the verb rather than the entity id.
export function confirmPhrase(action, name, currentlyOn) {
    switch (action) {
    case "toggle":
        return "Turn " + (currentlyOn ? "off" : "on") + " " + name + "?"
    case "lock":
        return "Lock " + name + "?"
    case "unlock":
        return "Unlock " + name + "?"
    case "dock":
        return "Send " + name + " to dock?"
    case "start":
        return "Start " + name + "?"
    case "open":
        return "Open " + name + "?"
    case "close":
        return "Close " + name + "?"
    default:
        return cap(action) + " " + name + "?"
    }
}

// A Home tile only knows the entity id it was configured with, so look it up
// in every room.
export function findControl(panel, entityId) {
    const areas = (panel && panel.areas) || []
    for (const area of areas) {
        for (const device of area.devices) {
            if (device.primary.entity_id === entityId) return { device: device, control: device.primary }
        }
    }
    return null
}

// The lucide icon for what a device is, so a row or a map marker reads at a glance.
const ICONS = {
    light: "lightbulb",
    switch: "power",
    input_boolean: "power",
    cover: "blinds",
    climate: "thermometer",
    media_player: "tv",
    remote: "tv",
    lock: "lock",
    alarm_control_panel: "shield-check",
    fan: "fan",
    vacuum: "bot",
    lawn_mower: "bot",
    scene: "clapperboard",
    script: "workflow",
    automation: "workflow",
    siren: "siren",
    humidifier: "droplets",
    water_heater: "droplets",
    valve: "droplets",
    button: "circle-dot",
    select: "sliders-horizontal",
    input_select: "sliders-horizontal",
    number: "sliders-horizontal",
    input_number: "sliders-horizontal",
}

export function iconFor(control) {
    // A garage door or gate is a cover, but a blind icon would be the wrong promise.
    if (control.domain === "cover" && control.guarded) return "warehouse"
    return ICONS[control.domain] ?? "plug"
}

// Shapes where one tap has an obvious meaning (primaryAction). A thermostat or a
// mode list needs a choice, so those stay in the list.
const ONE_TAP_SHAPES = ["toggle", "toggle-level", "press", "lock", "cover", "vacuum"]

export function oneTap(control) {
    return ONE_TAP_SHAPES.includes(shapeFor(control))
}

export function areaLabel(area) {
    return area.name || "Other"
}
