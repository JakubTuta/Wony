import assert from "node:assert/strict"
import { test } from "node:test"

import { candidateTiles, describeTile, parseTileId, seedTiles } from "../lib/tiles.mjs"
import { signature } from "../lib/jobs.mjs"

function device(entityId, domain, name, extra = {}) {
    return {
        name,
        primary: {
            entity_id: entityId, name, domain, state: "off", on: false, available: true, level: null,
            options: [], press: false, number: false, toggle: true, slider: false, guarded: false,
            target: null, current: null, ...extra,
        },
        extras: [],
    }
}

const devices = { locks_allowed: true, areas: [
    { name: "Hall", devices: [
        device("lock.front", "lock", "Front door", { guarded: true, toggle: false }),
        device("light.lamp", "light", "Lamp"),
    ] },
] }
const routines = [{ name: "Good night", steps: "Lights off, door locked." }, { name: "movies", steps: "x" }]

test("tile ids split at the first colon", () => {
    assert.deepEqual(parseTileId("routine:good night"), { kind: "routine", arg: "good night" })
    assert.deepEqual(parseTileId("device:light.a:b"), { kind: "device", arg: "light.a:b" })
    assert.deepEqual(parseTileId("volume"), { kind: "volume", arg: "" })
})

test("a first run is seeded from what the house has, six at most", () => {
    const seed = seedTiles(routines, devices)
    assert.deepEqual(seed, [
        "device:light.lamp", "device:lock.front", "routine:Good night", "routine:movies", "timer:10", "volume",
    ])
    assert.deepEqual(seedTiles([], null), ["timer:10", "volume"])
})

test("everything can be offered as a tile", () => {
    const ids = candidateTiles(routines, devices).map((t) => t.id)
    assert.ok(ids.includes("routine:Good night"))
    assert.ok(ids.includes("device:lock.front"))
    for (const fixed of ["timer:10", "music", "volume", "sleep"]) assert.ok(ids.includes(fixed))
})

test("a routine tile runs the routine by name", () => {
    const tile = describeTile("routine:good night", { routines: { routines } })
    assert.equal(tile.title, "Good night")
    assert.deepEqual(tile.action, { type: "routine", name: "Good night" })
    assert.equal(describeTile("routine:gone", { routines: { routines } }).sub, "Routine not found")
})

test("a guarded device asks first, with the job signature", () => {
    const tile = describeTile("device:lock.front", { devices, locksAllowed: true, confirmAllDevices: false })
    assert.equal(tile.sub, "Locked")
    assert.equal(tile.action.type, "device")
    assert.equal(tile.action.confirm.title, "Unlock front door?")
    assert.equal(tile.action.confirm.sig, 'control_home_device(target="front door", action="unlock")')
})

test("a plain device runs straight away unless the setting asks", () => {
    const quiet = describeTile("device:light.lamp", { devices, confirmAllDevices: false })
    assert.equal(quiet.action.confirm, null)
    const careful = describeTile("device:light.lamp", { devices, confirmAllDevices: true })
    assert.equal(careful.action.confirm.title, "Turn on lamp?")
})

test("a lock is blocked until Settings allows it", () => {
    const tile = describeTile("device:lock.front", { devices, locksAllowed: false })
    assert.equal(tile.sub, "Locks off in Settings")
    assert.deepEqual(tile.action, { type: "notice", text: "Locks are off in Settings." })
})

test("a missing device says so", () => {
    const tile = describeTile("device:light.gone", { devices })
    assert.equal(tile.sub, "Unavailable")
    assert.equal(tile.action.type, "notice")
})

test("a timer tile starts, then counts down and offers to cancel", () => {
    const idle = describeTile("timer:5", { reminders: { reminders: [] } })
    assert.equal(idle.sub, "Tap to start")
    assert.deepEqual(idle.action, { type: "timer-start", minutes: 5, text: "5 minute timer" })

    const now = Date.parse("2026-10-16T10:00:00")
    const reminders = { reminders: [{ id: "r1", text: "5 minute timer", next_run: "2026-10-16T10:04:30" }] }
    const running = describeTile("timer:5", { reminders, now })
    assert.equal(running.sub, "4:30 left · tap to cancel")
    assert.equal(running.active, true)
    assert.equal(running.action.type, "timer-cancel")
    assert.equal(running.action.id, "r1")
})

test("music and volume tiles read the playing track", () => {
    const music = { active: true, title: "Song", is_playing: true, volume: 40 }
    assert.equal(describeTile("music", { music }).sub, "Song · playing")
    assert.equal(describeTile("music", { music: { active: false } }).sub, "Nothing playing")
    assert.equal(describeTile("volume", { music }).sub, "40%")
    assert.equal(describeTile("volume", { music: null }).sub, "—")
})

test("job signatures skip empty arguments", () => {
    assert.equal(signature("routine", { name: "briefing" }), 'routine(name="briefing")')
    assert.equal(signature("x", { a: 1, b: "", c: null, d: true }), "x(a=1, d=true)")
    assert.equal(signature("x"), "x()")
})
