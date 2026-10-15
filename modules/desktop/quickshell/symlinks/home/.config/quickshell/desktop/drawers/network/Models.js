// Apply snapshots without recreating delegates, losing form state or focus.
function sync(model, entries, identity, stableNetworkOrder) {
    const previous = new Map();
    for (let i = 0; i < model.count; i++) previous.set(model.get(i).identity, i);
    const values = entries.slice();
    if (stableNetworkOrder) values.sort((a, b) =>
        Number(b.connected) - Number(a.connected) || Number(!!b.uuid) - Number(!!a.uuid)
        || ((previous.get(a[identity]) ?? 100000) - (previous.get(b[identity]) ?? 100000))
        || b.strength - a.strength);
    const wanted = new Set(values.map(entry => entry[identity]));
    for (let i = model.count - 1; i >= 0; i--)
        if (!wanted.has(model.get(i).identity)) model.remove(i);
    values.forEach((entry, index) => {
        const key = entry[identity];
        let existing = -1;
        for (let i = index; i < model.count; i++)
            if (model.get(i).identity === key) { existing = i; break; }
        if (existing === -1) model.insert(index, {identity: key, record: entry});
        else {
            if (existing !== index) model.move(existing, index, 1);
            const current = model.get(index).record;
            // Snapshot records have scalar fields. Compare by key because Qt
            // maps need not enumerate properties in Python's insertion order.
            if (Object.keys(current).length !== Object.keys(entry).length
                || Object.keys(entry).some(key => current[key] !== entry[key]))
                model.setProperty(index, "record", entry);
        }
    });
}
