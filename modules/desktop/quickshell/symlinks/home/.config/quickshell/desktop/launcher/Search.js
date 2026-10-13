.pragma library

// Native entries stay authoritative. Cache text only, never command strings.
function catalogue(entries) {
    return entries.map(entry => ({
        entry: entry,
        name: entry.name.toLowerCase(),
        terms: [entry.name, entry.genericName || "", entry.comment || "",
            entry.id, (entry.keywords || []).join(" ")].join(" ").toLowerCase()
    }));
}

function matches(candidates, text) {
    const query = text.trim().toLowerCase();
    const words = query ? query.split(/\s+/) : [];
    function rank(item) {
        return !query || item.name === query ? 0 : item.name.startsWith(query) ? 1
            : item.name.includes(query) ? 2 : 3;
    }
    return candidates.filter(item => words.every(word => item.terms.includes(word)))
        .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)
            || a.entry.id.localeCompare(b.entry.id))
        .map(item => item.entry);
}
