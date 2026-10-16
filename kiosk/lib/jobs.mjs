// The mono job signature shown on the confirm sheet, e.g. routine(name="briefing").
export function signature(name, args = {}) {
    const parts = Object.entries(args)
        .filter(([, value]) => value !== undefined && value !== null && value !== "")
        .map(([key, value]) => key + "=" + (typeof value === "string" ? '"' + value + '"' : String(value)))
    return name + "(" + parts.join(", ") + ")"
}
