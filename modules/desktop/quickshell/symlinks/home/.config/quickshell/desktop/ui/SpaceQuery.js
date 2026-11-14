.pragma library

var commands = [
    {name: "movie", label: "Movies", icon: "film"},
    {name: "series", label: "TV series", icon: "tv"},
    {name: "episode", label: "Episodes · show S01E02", icon: "tv"},
    {name: "music", label: "Songs, albums and artists", icon: "music"},
    {name: "song", label: "Songs", icon: "music"},
    {name: "album", label: "Albums", icon: "music"},
    {name: "artist", label: "Artists", icon: "user-round"},
    {name: "radio", label: "Radio stations", icon: "boom-box"},
    {name: "tv", label: "Television channels", icon: "antenna"},
    {name: "game", label: "Games", icon: "gamepad-2"},
    {name: "youtube", label: "YouTube videos", icon: "video"}
];
var aliases = {movies: "movie", show: "series", shows: "series", episodes: "episode",
    songs: "song", albums: "album", artists: "artist", radios: "radio",
    television: "tv", games: "game", yt: "youtube", video: "youtube"};
var examples = {
    movie: '/movie genre:sci-fi year:2000..2025 rating:7 sort:rating',
    series: '/series genre:comedy rating:7 library:true',
    episode: '/episode severance S01E02 local:true',
    music: '/music genre:jazz',
    song: '/song artist:"Daft Punk" duration:..5m',
    album: '/album genre:jazz year:2020..',
    artist: '/artist genre:rock',
    radio: '/radio genre:jazz country:Vietnam bitrate:128',
    tv: '/tv category:news language:English',
    game: '/game genre:rpg platform:pc installed:true',
    youtube: '/youtube astronomy duration:..20m channel:NASA'
};
var fieldNames = ["genre", "min_year", "max_year", "min_rating", "min_votes", "country", "language", "category", "artist", "album", "channel", "platform", "min_duration", "max_duration", "min_bitrate", "codec", "favorites", "owned", "installed", "live", "availability", "sort"];

function tokens(text) {
    let words = [], word = "", quote = "", escaped = false;
    for (const c of text) {
        if (escaped) { word += c; escaped = false; }
        else if (c === "\\" && quote) escaped = true;
        else if (quote) { if (c === quote) quote = ""; else word += c; }
        else if ((c === '"' || c === "'") && (!word || word.endsWith(":"))) quote = c;
        else if (/\s/.test(c)) { if (word) words.push(word); word = ""; }
        else word += c;
    }
    if (quote || escaped) throw new Error("Finish the quoted filter value.");
    if (word) words.push(word);
    return words;
}

function range(value, duration) {
    const parse = part => {
        if (!part) return null;
        const match = /^(\d+)(s|m|h)?$/.exec(part);
        if (!match || (!duration && match[2])) throw new Error("Use a number or range, such as year:2000..2025 or duration:..10m.");
        return Number(match[1]) * (match[2] === "h" ? 3600 : match[2] === "m" ? 60 : 1);
    };
    const parts = value.split("..");
    if (parts.length > 2) throw new Error("Use one range, such as year:2000..2025.");
    const low = parse(parts[0]);
    if (parts.length === 1) return duration ? [null, low] : [low, low];
    const high = parse(parts[1]);
    if (low === null && high === null) throw new Error("The range needs at least one value.");
    return [low, high];
}

function criteria(text) {
    let query = [], filters = {}, online = true;
    for (const word of tokens(text)) {
        const match = /^([a-z][a-z_]*):(.*)$/.exec(word);
        if (!match || ["https", "http", "file"].includes(match[1])) { query.push(word); continue; }
        let name = match[1], value = match[2];
        if (!value) throw new Error("Add a value after " + name + ":");
        if (name === "year" || name === "duration") {
            const bounds = range(value, name === "duration");
            if (bounds[0] !== null) filters[name === "year" ? "min_year" : "min_duration"] = bounds[0];
            if (bounds[1] !== null) filters[name === "year" ? "max_year" : "max_duration"] = bounds[1];
            continue;
        }
        if (["online", "local", "library"].includes(name)) {
            if (!["true", "false"].includes(value)) throw new Error(name + " must be true or false.");
            if (name === "online") online = value === "true";
            else if (value === "true") filters.availability = name;
            continue;
        }
        name = ({rating:"min_rating", votes:"min_votes", bitrate:"min_bitrate", favorite:"favorites"})[name] || name;
        if (!fieldNames.includes(name)) throw new Error("Unknown filter: " + name);
        if (["favorites", "owned", "installed", "live"].includes(name)) {
            if (!["true", "false"].includes(value)) throw new Error(name + " must be true or false.");
            value = value === "true";
        } else if (/^(min_|max_)/.test(name)) {
            if (!/^\d+(\.\d+)?$/.test(value)) throw new Error(name + " must be a number.");
            value = Number(value);
        }
        filters[name] = value;
    }
    return {query:query.join(" "), filters:filters, online:online};
}

function parse(text) {
    const value = text.replace(/^\s+/, "");
    if (!value.startsWith("/")) return null;
    const match = /^\/(\S*)\s*([\s\S]*)$/.exec(value);
    const name = (match?.[1] || "").toLowerCase();
    const kind = aliases[name] || name;
    const command = commands.find(item => item.name === kind);
    let parsed = {query:"", filters:{}, online:true}, error = "";
    try { parsed = criteria((match?.[2] || "").trim()); }
    catch (failure) { error = failure.message; }
    return {kind: command ? kind : "", query: parsed.query, filters:parsed.filters,
        online:parsed.online, error:error,
        hasCriteria: !!parsed.query || Object.keys(parsed.filters).length > 0 || !parsed.online,
        example: examples[kind] || "",
        suggestions: command ? [command] : commands.filter(item => item.name.startsWith(name))};
}
