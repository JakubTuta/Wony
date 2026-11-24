import assert from "node:assert/strict"
import { test } from "node:test"

import { areaLabel, iconFor, oneTap } from "../lib/devices.mjs"
import { fitRect, fraction, markers, placeAt, removeFrom, unplaced } from "../lib/homemap.mjs"

function control(overrides = {}) {
    return {
        entity_id: "light.lamp", name: "Lamp", domain: "light", state: "on", on: true, available: true,
        level: null, options: [], press: false, number: false, toggle: true, slider: false,
        guarded: false, target: null, current: null, ...overrides,
    }
}

function device(name, overrides) {
    return { name: name, primary: control({ name: name, ...overrides }), extras: [], readings: [] }
}

const PANEL = {
    areas: [
        { name: "Living room", devices: [
            device("Lamp", { entity_id: "light.lamp" }),
            device("Thermostat", { entity_id: "climate.main", domain: "climate", toggle: false }),
        ] },
        { name: "", devices: [device("Kettle", { entity_id: "switch.kettle", domain: "switch", on: false })] },
    ],
}

test("a wide picture in a tall box fills the width and is centred up and down", () => {
    assert.deepEqual(fitRect(400, 400, 200, 100), { x: 0, y: 100, width: 400, height: 200 })
})

test("a tall picture in a wide box fills the height and is centred left and right", () => {
    assert.deepEqual(fitRect(400, 200, 100, 200), { x: 150, y: 0, width: 100, height: 200 })
})

test("a picture whose size is not known yet has no box", () => {
    assert.deepEqual(fitRect(400, 200, 0, 0), { x: 0, y: 0, width: 0, height: 0 })
    assert.deepEqual(fitRect(0, 200, 10, 10), { x: 0, y: 0, width: 0, height: 0 })
})

test("a position is kept on the picture and rounded like the server does", () => {
    assert.equal(fraction(-3), 0)
    assert.equal(fraction(7), 1)
    assert.equal(fraction(0.123456), 0.1235)
})

test("placing a device twice moves it instead of adding another", () => {
    let placed = placeAt([], "light.lamp", 0.1, 0.2)
    placed = placeAt(placed, "switch.kettle", 0.5, 0.5)
    placed = placeAt(placed, "light.lamp", 0.9, 1.4)
    assert.deepEqual(placed, [
        { entity_id: "switch.kettle", x: 0.5, y: 0.5 },
        { entity_id: "light.lamp", x: 0.9, y: 1 },
    ])
})

test("removing a device leaves the others", () => {
    const placed = [{ entity_id: "a.b", x: 0, y: 0 }, { entity_id: "c.d", x: 1, y: 1 }]
    assert.deepEqual(removeFrom(placed, "a.b"), [{ entity_id: "c.d", x: 1, y: 1 }])
})

test("only devices one tap can switch are offered, and not twice", () => {
    assert.deepEqual(unplaced(PANEL, []).map((d) => d.entity_id), ["light.lamp", "switch.kettle"])
    assert.deepEqual(
        unplaced(PANEL, [{ entity_id: "light.lamp", x: 0.5, y: 0.5 }]).map((d) => d.entity_id),
        ["switch.kettle"],
    )
})

test("the room with no name is called Other", () => {
    assert.equal(unplaced(PANEL, [])[1].area, "Other")
    assert.equal(areaLabel({ name: "Hall" }), "Hall")
})

test("a lock, blinds and a vacuum can be placed; a thermostat and a mode list cannot", () => {
    assert.equal(oneTap(control({ domain: "lock", toggle: false, guarded: true })), true)
    assert.equal(oneTap(control({ domain: "cover", toggle: false })), true)
    assert.equal(oneTap(control({ domain: "vacuum", toggle: false })), true)
    assert.equal(oneTap(control({ domain: "button", toggle: false, press: true })), true)
    assert.equal(oneTap(control({ domain: "climate", toggle: false })), false)
    assert.equal(oneTap(control({ domain: "select", toggle: false, options: ["a"] })), false)
})

test("a placement carries what Home Assistant says about the device", () => {
    const [lamp, kettle] = markers(PANEL, [
        { entity_id: "light.lamp", x: 0.2, y: 0.4 },
        { entity_id: "switch.kettle", x: 0.6, y: 0.8 },
    ])
    assert.deepEqual([lamp.name, lamp.on, lamp.known, lamp.icon, lamp.x, lamp.y], ["Lamp", true, true, "lightbulb", 0.2, 0.4])
    assert.deepEqual([kettle.name, kettle.on, kettle.icon], ["Kettle", false, "power"])
})

test("a device Home Assistant no longer has stays on the map, marked unknown", () => {
    const [gone] = markers(PANEL, [{ entity_id: "light.gone", x: 0.5, y: 0.5 }])
    assert.deepEqual([gone.known, gone.available, gone.on, gone.name], [false, false, false, "Not in Home Assistant"])
})

test("a garage door does not get the blinds icon", () => {
    assert.equal(iconFor(control({ domain: "cover", guarded: true })), "warehouse")
    assert.equal(iconFor(control({ domain: "cover" })), "blinds")
    assert.equal(iconFor(control({ domain: "mystery" })), "plug")
})
