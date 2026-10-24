import QtQuick

Worker {
    id: root
    objectName: "mediaService"
    backend: "backend.py"
    serviceName: "Media"
    property var responses: ({})
    property var reads: ({})
    property int cacheGeneration: 0
    readonly property var cacheable: ["details", "artwork", "collections", "watch", "spoilers", "person", "anime_entry", "anime_genres"]

    function cacheKey(op, args) {
        const identity = Object.assign({}, args);
        delete identity.refresh;
        if (identity.title) {
            const title = identity.title;
            identity.title = {id:title.tmdbId ? "tmdb:" + title.kind + ":" + title.tmdbId : title.imdbId || title.id,kind:title.kind};
        }
        if (identity.person) identity.person = {id:identity.person.id || identity.person.url || identity.person.name};
        return op + ":" + JSON.stringify(identity);
    }
    function hasCached(op, args) {
        const saved = responses[cacheKey(op, args)];
        return !!saved && Date.now() - saved.time < 15 * 60 * 1000;
    }
    function fetch(op, args, callback) {
        args = args || {};
        if (args.refresh) { cacheGeneration++; responses = ({}); }
        if (!cacheable.includes(op)) return request(op, args, callback);
        const key = cacheKey(op, args);
        const saved = responses[key];
        if (!args.refresh && saved && Date.now() - saved.time < 15 * 60 * 1000) {
            delete responses[key]; responses[key] = saved;
            Qt.callLater(() => { if (root) callback(JSON.parse(saved.json), ""); });
            return;
        }
        const generation = cacheGeneration;
        const pending = generation + ":" + key;
        if (reads[pending]) { reads[pending].push(callback); return; }
        reads[pending] = [callback];
        return request(op, args, (result, error) => {
            const callbacks = reads[pending] || [];
            delete reads[pending];
            if (!error && generation === cacheGeneration) {
                if (Object.keys(responses).length >= 80) delete responses[Object.keys(responses)[0]];
                responses[key] = {json:JSON.stringify(result),time:Date.now()};
            }
            for (const respond of callbacks) respond(result, error);
        });
    }
}
