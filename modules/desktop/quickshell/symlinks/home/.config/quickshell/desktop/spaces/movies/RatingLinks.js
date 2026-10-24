.pragma library

function source(r) {
    const name=String(r.source || "").toLowerCase();
    if (["imdb","internet movie database"].includes(name)) return "imdb";
    if (["rotten tomatoes","tomatoes","rt"].includes(name)) return "rt";
    if (["popcorn","tomatoesaudience","rt_audience"].includes(name)) return "rt_audience";
    return name;
}
function webUrl(value, base, prefix) {
    const url=String(value || "").trim();
    if (!url || /\s/.test(url)) return "";
    if (/^https?:\/\/[^/]+/i.test(url)) return url;
    if (url.startsWith("//")) return "https:" + url;
    if (/^[a-z][a-z0-9+.-]*:/i.test(url)) return "";
    const path=url.replace(/^\/+/, "");
    return path ? base + "/" + (prefix && !path.startsWith(prefix) ? prefix : "") + path : "";
}
function page(r, title) {
    const service=source(r), query=encodeURIComponent(title.title || "");
    if (service === "imdb") {
        const id=String(title.imdbId || title.id || "").match(/^tt\d+$/);
        if (id) return "https://www.imdb.com/title/" + id[0] + "/";
        const linkedId=String(r.url || "").match(/tt\d+/);
        return linkedId ? "https://www.imdb.com/title/" + linkedId[0] + "/" : "https://www.imdb.com/find/?q=" + query;
    }
    if (service === "tmdb") return title.tmdbId ? "https://www.themoviedb.org/" + (title.kind === "tv" ? "tv/" : "movie/") + title.tmdbId : "https://www.themoviedb.org/search?query=" + query;
    if (service === "myanimelist") return webUrl(r.url || title.malUrl,"https://myanimelist.net", "") || (title.malId ? "https://myanimelist.net/anime/" + title.malId : "https://myanimelist.net/anime.php?q=" + query);
    if (service === "rt" || service === "rt_audience") {
        const url=r.url || title.rottenTomatoesUrl;
        const path=String(url || "").replace(/^\/+/, "");
        return webUrl(url,"https://www.rottentomatoes.com", /^(m|tv)\//.test(path) ? "" : title.kind === "tv" ? "tv/" : "m/") || "https://www.rottentomatoes.com/search?search=" + query;
    }
    if (service === "metacritic") {
        const url=r.url || title.metacriticUrl;
        const path=String(url || "").replace(/^\/+/, "");
        return webUrl(url,"https://www.metacritic.com", /^(movie|tv)\//.test(path) ? "" : title.kind === "tv" ? "tv/" : "movie/") || "https://www.metacritic.com/search/" + query + "/";
    }
    return "";
}
function ordered(ratings) {
    const order={myanimelist:0, tmdb:0, imdb:1, rt:2, rt_audience:3, metacritic:4};
    return ratings.slice().sort((a,b) => (order[source(a)] ?? 9)-(order[source(b)] ?? 9));
}
