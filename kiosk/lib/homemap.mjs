// The Smart home map: where a picture sits on the screen and which devices are
// on it. Pure functions, no Qt: `node --test kiosk/tests/` runs them.
import { areaLabel, findControl, iconFor, oneTap } from "./devices.mjs"

// The largest box of the picture's own shape that fits in the space, centred.
export function fitRect(boxWidth, boxHeight, imageWidth, imageHeight) {
    if (!(boxWidth > 0 && boxHeight > 0 && imageWidth > 0 && imageHeight > 0)) {
        return { x: 0, y: 0, width: 0, height: 0 }
    }
    const scale = Math.min(boxWidth / imageWidth, boxHeight / imageHeight)
    const width = imageWidth * scale
    const height = imageHeight * scale
    return { x: (boxWidth - width) / 2, y: (boxHeight - height) / 2, width: width, height: height }
}

// Positions are fractions of the picture, so they survive any screen and any
// replacement picture. The server rounds the same way.
export function fraction(value) {
    return Math.round(Math.min(1, Math.max(0, value)) * 10000) / 10000
}

// A device is in one place: putting it somewhere moves it.
export function placeAt(placements, entityId, x, y) {
    return removeFrom(placements, entityId).concat([{ entity_id: entityId, x: fraction(x), y: fraction(y) }])
}

export function removeFrom(placements, entityId) {
    return placements.filter((p) => p.entity_id !== entityId)
}

// Devices one tap can switch that are not on the map yet, by room.
export function unplaced(panel, placements) {
    const onMap = new Set(placements.map((p) => p.entity_id))
    const out = []
    for (const area of (panel && panel.areas) || []) {
        for (const device of area.devices) {
            const control = device.primary
            if (oneTap(control) && !onMap.has(control.entity_id)) {
                out.push({ entity_id: control.entity_id, name: device.name, area: areaLabel(area), icon: iconFor(control) })
            }
        }
    }
    return out
}

// Each placement with what Home Assistant says about it. A device that was
// removed from Home Assistant stays on the map, greyed out, until it is taken off.
export function markers(panel, placements) {
    return placements.map((p) => {
        const found = findControl(panel, p.entity_id)
        return {
            entity_id: p.entity_id,
            x: p.x,
            y: p.y,
            known: found !== null,
            name: found ? found.device.name : "Not in Home Assistant",
            icon: found ? iconFor(found.control) : "plug",
            on: found ? found.control.on : false,
            available: found ? found.control.available : false,
            guarded: found ? found.control.guarded : false,
        }
    })
}
