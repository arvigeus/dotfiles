// Apply keyed snapshots to a ListModel without recreating delegates (keeping
// form state and focus). Used instead of ScriptModel { objectProp } for lists
// whose rows can reorder: Quickshell 0.3.2 moves such rows but leaves their
// delegates' modelData at the pre-move record.
function sync(model, values, identity, role = "record") {
    const wanted = new Set(values.map(entry => entry[identity]));
    for (let i = model.count - 1; i >= 0; i--)
        if (!wanted.has(model.get(i).identity)) model.remove(i);
    values.forEach((entry, index) => {
        const key = entry[identity];
        let existing = -1;
        for (let i = index; i < model.count; i++)
            if (model.get(i).identity === key) { existing = i; break; }
        if (existing === -1) model.insert(index, {identity: key, [role]: entry});
        else {
            if (existing !== index) model.move(existing, index, 1);
            const current = model.get(index)[role];
            // Snapshot records have scalar fields. Compare by key because Qt
            // maps need not enumerate properties in Python's insertion order.
            if (Object.keys(current).length !== Object.keys(entry).length
                || Object.keys(entry).some(key => current[key] !== entry[key]))
                model.setProperty(index, role, entry);
        }
    });
}
