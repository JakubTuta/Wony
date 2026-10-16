// Time formatting by hand rather than Date.toLocale*: the panel always shows
// English "08:05 PM", whatever locale the Pi is set to, and this way node can
// test it.

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
const MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

function pad(n) {
    return n < 10 ? "0" + n : String(n)
}

// "08:05 PM"
export function clock(date) {
    const hours = date.getHours() % 12 || 12
    return pad(hours) + ":" + pad(date.getMinutes()) + " " + (date.getHours() < 12 ? "AM" : "PM")
}

// "Friday, October 16"
export function dayName(date) {
    return WEEKDAYS[date.getDay()] + ", " + MONTHS[date.getMonth()] + " " + date.getDate()
}

// mm:ss, for a track's progress or a timer's countdown while it is under an hour.
export function clockFromMs(ms) {
    const total = Math.max(0, Math.round(ms / 1000))
    return Math.floor(total / 60) + ":" + pad(total % 60)
}

// Seconds remaining until an ISO datetime, floored at 0.
export function secondsUntil(iso, now = Date.now()) {
    return Math.max(0, Math.round((new Date(iso).getTime() - now) / 1000))
}

// "Coming up" shows a countdown for what is about to happen and a plain clock
// time for what is further out: a reminder nine hours away does not need to be
// read down to the second.
export function upcomingTime(iso, now = Date.now()) {
    const seconds = secondsUntil(iso, now)
    if (seconds < 3600) return clockFromMs(seconds * 1000)
    return clock(new Date(iso))
}

// Move an "HH:MM" by some minutes, wrapping at midnight in both directions.
export function shiftClock(time, minutes) {
    const [h, m] = time.split(":").map(Number)
    if (Number.isNaN(h) || Number.isNaN(m)) return time
    const total = (((h * 60 + m + minutes) % 1440) + 1440) % 1440
    return pad(Math.floor(total / 60)) + ":" + pad(total % 60)
}
