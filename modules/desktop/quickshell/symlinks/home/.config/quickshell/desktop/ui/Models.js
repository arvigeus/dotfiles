// Apply keyed snapshots to a ListModel without recreating delegates (keeping
// form state and focus). Used instead of ScriptModel { objectProp } for lists
// whose rows can reorder: Quickshell 0.3.2 moves such rows but leaves their
// delegates' modelData at the pre-move record.
// The model needs dynamicRoles: it then ignores a record equal to the stored
// one, including nested lists and a different key order.
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
            model.setProperty(index, role, entry);
        }
    });
    // Rows left over from duplicate keys.
    if (model.count > values.length) model.remove(values.length, model.count - values.length);
}
