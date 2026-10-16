.pragma library

function scales(row) {
    const parts = /^(\d+)x(\d+)/.exec(row.mode);
    const values = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 3, 4, row.scale];
    return [...new Set(values)].filter(value => parts && [Number(parts[1]), Number(parts[2])].every(size => Math.abs(size / value - Math.round(size / value)) < 0.01)).sort((a,b) => a-b);
}
