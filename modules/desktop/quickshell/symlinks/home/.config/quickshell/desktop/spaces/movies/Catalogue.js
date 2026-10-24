.pragma library

// Reconcile by identity, retaining delegates, decoded artwork and scroll position.
function update(model, current, items, append, identity) {
    const keyFor = identity || (item => item && item.id ? String(item.id) : "");
    const seen = new Set(append ? current.map(keyFor) : []);
    const additions = (items || []).filter(item => {
        const key = keyFor(item);
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
    });
    const next = append ? current.concat(additions) : additions;
    if (append) {
        for (const item of additions) model.append({key: keyFor(item), payload: JSON.stringify(item)});
        return next;
    }
    const wanted = new Set(next.map(keyFor));
    for (let i = model.count - 1; i >= 0; --i)
        if (!wanted.has(model.get(i).key)) model.remove(i);
    for (let i = 0; i < next.length; ++i) {
        const key = keyFor(next[i]), payload = JSON.stringify(next[i]);
        if (i >= model.count || model.get(i).key !== key) {
            let from = i + 1;
            while (from < model.count && model.get(from).key !== key) ++from;
            if (from < model.count) model.move(from, i, 1);
            else model.insert(i, {key: key, payload: payload});
        }
        if (model.get(i).payload !== payload) model.setProperty(i, "payload", payload);
    }
    return next;
}
