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

function matches(candidates, text, favoriteIds = []) {
    const query = text.trim().toLowerCase();
    const words = query ? query.split(/\s+/) : [];
    // Favorites organize browsing; typing retains the same name-based ranking.
    const favorites = new Set(query ? [] : favoriteIds);
    function rank(item) {
        return !query || item.name === query ? 0 : item.name.startsWith(query) ? 1
            : item.name.includes(query) ? 2 : 3;
    }
    return candidates.filter(item => words.every(word => item.terms.includes(word)))
        .sort((a, b) => rank(a) - rank(b)
            || Number(favorites.has(b.entry.id)) - Number(favorites.has(a.entry.id))
            || a.name.localeCompare(b.name)
            || a.entry.id.localeCompare(b.entry.id))
        .map(item => item.entry);
}
