import assert from "node:assert/strict"
import { test } from "node:test"

import { rowHeight, gridHeight } from "../lib/layout.mjs"
import { clock, clockFromMs, dayName, secondsUntil, shiftClock, upcomingTime } from "../lib/time.mjs"

test("clock is English 12-hour", () => {
    assert.equal(clock(new Date(2026, 9, 16, 20, 5)), "08:05 PM")
    assert.equal(clock(new Date(2026, 9, 16, 0, 7)), "12:07 AM")
    assert.equal(clock(new Date(2026, 9, 16, 12, 0)), "12:00 PM")
})

test("the day reads like the header", () => {
    assert.equal(dayName(new Date(2026, 9, 16)), "Friday, October 16")
})

test("mm:ss pads seconds and never goes negative", () => {
    assert.equal(clockFromMs(61000), "1:01")
    assert.equal(clockFromMs(251000), "4:11")
    assert.equal(clockFromMs(-5000), "0:00")
})

test("seconds until floors at zero", () => {
    const now = Date.parse("2026-10-16T10:00:00")
    assert.equal(secondsUntil("2026-10-16T10:01:00", now), 60)
    assert.equal(secondsUntil("2026-10-16T09:00:00", now), 0)
})

test("coming up counts down within the hour and shows a clock beyond it", () => {
    const now = Date.parse("2026-10-16T10:00:00")
    assert.equal(upcomingTime("2026-10-16T10:07:00", now), "7:00")
    assert.equal(upcomingTime("2026-10-16T19:30:00", now), "07:30 PM")
})

test("wake times shift around midnight in both directions", () => {
    assert.equal(shiftClock("07:00", 15), "07:15")
    assert.equal(shiftClock("23:50", 15), "00:05")
    assert.equal(shiftClock("00:05", -15), "23:50")
    assert.equal(shiftClock("nonsense", 15), "nonsense")
})

test("grid rows share the height until they would be too small", () => {
    assert.equal(rowHeight(6, 3, 564, 16, 140), 274)
    assert.equal(rowHeight(30, 3, 564, 16, 140), 140)
    assert.equal(rowHeight(0, 3, 564, 16, 140), 564)
    assert.equal(gridHeight(6, 3, 274, 16), 564)
    assert.equal(gridHeight(0, 3, 274, 16), 0)
})
