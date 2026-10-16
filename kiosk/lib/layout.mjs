// Height of one row in a grid whose rows share the available height equally
// but never shrink below `min`; past that the grid scrolls.
export function rowHeight(count, columns, available, gap, min) {
    const rows = Math.max(1, Math.ceil(count / columns))
    return Math.max(min, (available - (rows - 1) * gap) / rows)
}

// Total height of `count` cells laid out `columns` wide.
export function gridHeight(count, columns, cell, gap) {
    const rows = Math.ceil(count / columns)
    return rows > 0 ? rows * cell + (rows - 1) * gap : 0
}
