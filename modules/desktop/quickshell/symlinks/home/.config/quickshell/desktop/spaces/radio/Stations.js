function genreKey(value) {
    const key = String(value || "").toLowerCase().replace(/&/g, " and ").replace(/['’‘`\"]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
    const aliases = {rocknroll:"rock and roll", "rock n roll":"rock and roll", hiphop:"hip hop", "r and b":"r&b", "r n b":"r&b", rnb:"r&b", "rhythm and blues":"r&b", dnb:"drum and bass", "drum n bass":"drum and bass", lofi:"lo fi", kpop:"k pop", jpop:"j pop", edm:"electronic dance music"};
    return aliases[key] || key;
}

function siteKey(url) {
    return String(url || "").trim().toLowerCase().replace(/^https?:\/\//, "").split(/[/?#]/)[0].replace(/^www\./, "");
}

function streamUrls(station) {
    return [station, ...(station.variants || [])].reduce((all, item) => all.concat([item.url, item.url_resolved]), [])
        .filter(Boolean).map(value => String(value).trim().replace(/#.*$/, ""));
}

function sameFavorite(a, b) {
    if (a.groupKey && a.groupKey === b.groupKey) return true;
    const ids = new Set([a, ...(a.variants || [])].map(item => item.stationuuid));
    if ([b, ...(b.variants || [])].some(item => ids.has(item.stationuuid))) return true;
    const urls = new Set(streamUrls(a));
    return streamUrls(b).some(url => urls.has(url));
}

function stationGroupKey(station) {
    const name = String(station.name || "").toLowerCase().replace(/[’‘]/g, "'").replace(/['`\"]/g, "").replace(/&/g, " and ").replace(/[.,;:!?(){}\[\]\/\\_-]+/g, " ").replace(/\s+/g, " ").trim();
    const country = String(station.countrycode || station.country || "").toLowerCase();
    const source = siteKey(station.homepage) || siteKey(station.favicon) || siteKey(station.url_resolved) || siteKey(station.url);
    return country + "|" + name + "|" + source;
}

function buildQualityOptions(variants) {
    const choices = [];
    const seen = new Set();
    for (const variant of variants) {
        const codec = String(variant.codec || "").trim().toUpperCase();
        const bitrate = Number(variant.bitrate) || 0;
        const key = codec + "|" + bitrate;
        if (bitrate || codec) {
            if (seen.has(key)) continue;
            seen.add(key);
        }
        const fallbackLabel = "Stream " + (choices.length + 1);
        choices.push({
            stationuuid: variant.stationuuid,
            codec: codec,
            bitrate: bitrate,
            label: [codec, bitrate ? bitrate + " kbps" : ""].filter(Boolean).join(" · ") || fallbackLabel
        });
    }
    return choices;
}

function groupStations(items) {
    const grouped = new Map();
    for (const station of items || []) {
        if (!station || !station.stationuuid || !station.name) continue;
        const key = stationGroupKey(station);
        if (!grouped.has(key)) grouped.set(key, {variants: [], seen: new Set()});
        const group = grouped.get(key);
        if (group.seen.has(station.stationuuid)) continue;
        group.seen.add(station.stationuuid);
        group.variants.push(station);
    }
    return Array.from(grouped, ([groupKey, group]) => {
        const variants = group.variants.slice().sort((a, b) => (Number(b.bitrate) || 0) - (Number(a.bitrate) || 0) || (Number(b.clickcount) || 0) - (Number(a.clickcount) || 0));
        const best = variants[0];
        const tags = Array.from(new Set(variants.reduce((all, variant) => all.concat(String(variant.tags || "").split(",").map(tag => tag.trim()).filter(Boolean)), [])));
        const logoVariant = variants.find(variant => /^https?:\/\//i.test(variant.favicon || ""));
        const qualityOptions = buildQualityOptions(variants);
        return Object.assign({}, best, {
            groupKey: groupKey,
            variants: variants,
            favicon: logoVariant ? logoVariant.favicon : "",
            tags: tags.join(", "),
            qualityOptions: qualityOptions,
            qualityLabel: qualityOptions.length ? qualityOptions[0].label : ""
        });
    });
}

