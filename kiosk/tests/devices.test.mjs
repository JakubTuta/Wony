import assert from "node:assert/strict"
import { test } from "node:test"

import {
    cap, confirmPhrase, domainLabel, findControl, needsConfirm, primaryAction, shapeFor, stateText,
} from "../lib/devices.mjs"

function control(overrides = {}) {
    return {
        entity_id: "light.lamp", name: "Lamp", domain: "light", state: "on", on: true, available: true,
        level: null, options: [], press: false, number: false, toggle: false, slider: false,
        guarded: false, target: null, current: null, ...overrides,
    }
}

test("locks and vacuums are never plain switches", () => {
    assert.equal(shapeFor(control({ domain: "lock", toggle: true })), "lock")
    assert.equal(shapeFor(control({ domain: "alarm_control_panel" })), "lock")
    assert.equal(shapeFor(control({ domain: "vacuum", toggle: true })), "vacuum")
})

test("shape follows the domain first, then the flags", () => {
    assert.equal(shapeFor(control({ domain: "cover" })), "cover")
    assert.equal(shapeFor(control({ domain: "valve" })), "cover")
    assert.equal(shapeFor(control({ domain: "climate" })), "climate")
    assert.equal(shapeFor(control({ press: true })), "press")
    assert.equal(shapeFor(control({ toggle: true, slider: true })), "toggle-level")
    assert.equal(shapeFor(control({ toggle: true })), "toggle")
    assert.equal(shapeFor(control({ domain: "select", options: ["a"] })), "options")
    assert.equal(shapeFor(control({ domain: "number", number: true })), "number")
    assert.equal(shapeFor(control({ domain: "sensor" })), "plain")
})

test("cap capitalises and unsnakes", () => {
    assert.equal(cap("water_heater"), "Water heater")
    assert.equal(cap(""), "")
})

test("domainLabel falls back to the capitalised domain", () => {
    assert.equal(domainLabel("cover"), "Blinds")
    assert.equal(domainLabel("sensor"), "Sensor")
})

test("state text carries the level or setpoint", () => {
    assert.equal(stateText(control({ domain: "cover", level: null, state: "open" }), "cover"), "Open")
    assert.equal(stateText(control({ domain: "cover", level: 0 }), "cover"), "Closed")
    assert.equal(stateText(control({ domain: "cover", level: 100 }), "cover"), "Open")
    assert.equal(stateText(control({ domain: "cover", level: 40 }), "cover"), "Open 40%")
    assert.equal(stateText(control({ domain: "climate", current: 20.5, state: "heat" }), "climate"), "Now 20.5° · Heat")
    assert.equal(stateText(control({ domain: "lock", on: false }), "lock"), "Locked")
    assert.equal(stateText(control({ level: 70, state: "on" }), "toggle-level"), "On · 70%")
    assert.equal(stateText(control({ state: "off", on: false, level: 70 }), "toggle-level"), "Off")
})

test("a tile's one tap does the sensible thing per domain", () => {
    assert.equal(primaryAction(control({ domain: "cover", level: 50 })), "close")
    assert.equal(primaryAction(control({ domain: "cover", level: 0 })), "open")
    assert.equal(primaryAction(control({ domain: "lock", on: true })), "lock")
    assert.equal(primaryAction(control({ domain: "lock", on: false })), "unlock")
    assert.equal(primaryAction(control({ domain: "vacuum", on: true })), "dock")
    assert.equal(primaryAction(control({ domain: "vacuum", on: false })), "start")
    assert.equal(primaryAction(control({ press: true })), "on")
    assert.equal(primaryAction(control()), "toggle")
})

test("guarded devices always confirm; the setting makes everything confirm", () => {
    assert.equal(needsConfirm(control({ guarded: true }), false), true)
    assert.equal(needsConfirm(control(), false), false)
    assert.equal(needsConfirm(control(), true), true)
})

test("confirm phrases name the verb", () => {
    assert.equal(confirmPhrase("toggle", "lamp", true), "Turn off lamp?")
    assert.equal(confirmPhrase("toggle", "lamp", false), "Turn on lamp?")
    assert.equal(confirmPhrase("unlock", "front door", false), "Unlock front door?")
    assert.equal(confirmPhrase("dock", "robo", false), "Send robo to dock?")
    assert.equal(confirmPhrase("stop", "blinds", false), "Stop blinds?")
})

test("findControl searches every room", () => {
    const panel = { areas: [
        { name: "A", devices: [{ name: "x", primary: control({ entity_id: "light.a" }), extras: [] }] },
        { name: "B", devices: [{ name: "y", primary: control({ entity_id: "light.b" }), extras: [] }] },
    ] }
    assert.equal(findControl(panel, "light.b").device.name, "y")
    assert.equal(findControl(panel, "light.zzz"), null)
    assert.equal(findControl(null, "light.a"), null)
})
