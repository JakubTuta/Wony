import assert from "node:assert/strict"
import { test } from "node:test"

import { candidateTiles, describeTile, parseTileId, starterTiles } from "../lib/tiles.mjs"
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

test("an unarranged Home starts with what the house has, then fills two rows", () => {
    assert.deepEqual(starterTiles(routines, devices, 3), [
        "device:light.lamp", "device:lock.front", "routine:Good night", "routine:movies", "timer:10", "volume",
    ])
})

test("a house with nothing connected still gets a full first screen", () => {
    assert.deepEqual(starterTiles([], null, 3), ["timer:10", "volume", "sleep", "timer:5", "timer:30", "music"])
    assert.deepEqual(starterTiles([], { areas: [] }, 3), starterTiles([], null, 3))
})

test("the starter set is two rows of the chosen width, or all it has", () => {
    assert.equal(starterTiles(routines, devices, 4).length, 8)
    assert.equal(starterTiles(routines.slice(0, 1), null, 4).length, 8)
    assert.equal(starterTiles([], null, 4).length, 7)
})

test("everything can be offered as a tile", () => {
    const ids = candidateTiles(routines, devices).map((t) => t.id)
    assert.ok(ids.includes("routine:Good night"))
    assert.ok(ids.includes("device:lock.front"))
    for (const fixed of ["timer:5", "timer:10", "timer:15", "timer:30", "music", "volume", "sleep"]) {
        assert.ok(ids.includes(fixed), fixed)
    }
})

test("a starter tile that is removed can be added back", () => {
    const offered = candidateTiles(routines, devices).map((t) => t.id)
    for (const id of starterTiles(routines, devices, 4)) assert.ok(offered.includes(id), id)
    for (const id of starterTiles([], null, 4)) assert.ok(offered.includes(id), id)
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
