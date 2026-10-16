import {
    cap, confirmPhrase, domainLabel, findControl, needsConfirm, primaryAction, shapeFor, stateText,
} from "./devices.mjs"
import { signature } from "./jobs.mjs"
import { upcomingTime } from "./time.mjs"

const STATIC_TILES = [
    { id: "timer:10", kind: "Timer", title: "10 minute timer" },
    { id: "music", kind: "Music", title: "Play / pause" },
    { id: "volume", kind: "Volume", title: "Volume" },
    { id: "sleep", kind: "Sleep", title: "Sleep" },
]

// Everything worth offering as a tile, built fresh from live data: a routine
// or a device the user just added shows up in "+ Add tile" without a code change.
export function candidateTiles(routines, devices) {
    const out = []
    for (const r of routines) {
        out.push({ id: "routine:" + r.name, kind: "Routine", title: r.name })
    }
    for (const area of (devices && devices.areas) || []) {
        for (const device of area.devices) {
            out.push({
                id: "device:" + device.primary.entity_id,
                kind: domainLabel(device.primary.domain),
                title: device.name,
            })
        }
    }
    return out.concat(STATIC_TILES)
}

export function parseTileId(id) {
    const i = id.indexOf(":")
    return i === -1 ? { kind: id, arg: "" } : { kind: id.slice(0, i), arg: id.slice(i + 1) }
}

// Up to 6 tiles for a first run: whichever of these exist, in this order, so a
// house with no locks gets a shorter starter grid instead of a dead tile.
export function seedTiles(routines, devices) {
    const all = ((devices && devices.areas) || []).flatMap((a) => a.devices)
    const byDomain = (domain) => all.find((d) => d.primary.domain === domain)

    const out = []
    const light = byDomain("light") || byDomain("switch")
    if (light) out.push("device:" + light.primary.entity_id)
    const cover = byDomain("cover")
    if (cover) out.push("device:" + cover.primary.entity_id)
    const lock = byDomain("lock")
    if (lock) out.push("device:" + lock.primary.entity_id)
    for (const r of routines.slice(0, 2)) out.push("routine:" + r.name)
    out.push("timer:10")
    // Not 'music': the Now Playing card is always on screen and already has
    // play/pause. Volume has no control anywhere else.
    out.push("volume")
    return out.slice(0, 6)
}

function truncate(text, n) {
    return text.length > n ? text.slice(0, n - 1) + "…" : text
}

// What one tile shows and what a tap on it should do. Returns plain data: the
// QML side owns toasts, confirm sheets and network calls. `action` is
// { type, ... } where type is one of routine, device, timer-start, timer-cancel,
// music, sleep, volume, notice.
export function describeTile(id, ctx) {
    const { kind, arg } = parseTileId(id)
    const routines = (ctx.routines && ctx.routines.routines) || []
    const reminders = (ctx.reminders && ctx.reminders.reminders) || []

    if (kind === "routine") {
        const routine = routines.find((r) => r.name.toLowerCase() === arg.toLowerCase())
        const title = routine ? routine.name : arg
        return {
            kindLabel: "Routine",
            title: title,
            sub: routine ? truncate(routine.steps, 42) : "Routine not found",
            active: false,
            action: { type: "routine", name: title },
        }
    }

    if (kind === "device") {
        const found = findControl(ctx.devices, arg)
        if (!found) {
            return {
                kindLabel: "Device",
                title: arg,
                sub: "Unavailable",
                active: false,
                action: { type: "notice", text: "That device is no longer available." },
            }
        }
        const control = found.control
        const name = found.device.name
        const shape = shapeFor(control)
        const blocked = control.guarded && !ctx.locksAllowed
        const action = primaryAction(control)

        let tap
        if (!control.available) {
            tap = { type: "notice", text: name + " is unavailable." }
        } else if (blocked) {
            tap = { type: "notice", text: "Locks are off in Settings." }
        } else if (needsConfirm(control, ctx.confirmAllDevices)) {
            tap = {
                type: "device",
                entityId: control.entity_id,
                name: name,
                action: action,
                confirm: {
                    title: confirmPhrase(action, name.toLowerCase(), control.on),
                    sig: signature("control_home_device", { target: name.toLowerCase(), action: action }),
                    yesLabel: cap(action),
                },
            }
        } else {
            tap = { type: "device", entityId: control.entity_id, name: name, action: action, confirm: null }
        }
        return {
            kindLabel: cap(control.domain),
            title: name,
            sub: blocked ? "Locks off in Settings" : stateText(control, shape),
            active: control.on,
            action: tap,
        }
    }

    if (kind === "timer") {
        const minutes = Number(arg) || 10
        const text = minutes + " minute timer"
        const running = reminders.find((r) => r.text === text && !!r.next_run)
        return {
            kindLabel: "Timer",
            title: text,
            sub: running ? upcomingTime(running.next_run, ctx.now) + " left · tap to cancel" : "Tap to start",
            active: !!running,
            action: running
                ? {
                    type: "timer-cancel",
                    id: running.id,
                    confirm: {
                        title: "Cancel the timer?",
                        sig: signature("manage_reminders", { action: "cancel", id_or_text: text }),
                        yesLabel: "Cancel timer",
                    },
                }
                : { type: "timer-start", minutes: minutes, text: text },
        }
    }

    if (kind === "volume") {
        const level = ctx.music ? ctx.music.volume : null
        return {
            kindLabel: "Volume",
            title: "Volume",
            sub: level === null || level === undefined ? "—" : level + "%",
            active: false,
            action: { type: "volume" },
        }
    }

    if (kind === "music") {
        const np = ctx.music
        return {
            kindLabel: "Music",
            title: "Play / pause",
            sub: np && np.active ? np.title + " · " + (np.is_playing ? "playing" : "paused") : "Nothing playing",
            active: !!(np && np.is_playing),
            action: { type: "music" },
        }
    }

    return { kindLabel: "Sleep", title: "Sleep", sub: "Tap to sleep", active: false, action: { type: "sleep" } }
}
