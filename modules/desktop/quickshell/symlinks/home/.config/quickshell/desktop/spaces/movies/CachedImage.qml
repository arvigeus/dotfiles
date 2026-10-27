import QtQuick

Image {
    id: root

    property var cacheService: ImageCache
    property url remoteSource: ""
    property bool fetching: false
    property bool failed: false
    property bool initialized: false
    property bool retried: false
    property int generation: 0
    property var ticket: null
    readonly property int loadStatus: fetching ? Image.Loading : failed ? Image.Error : status

    function resolve(refresh) {
        if (ticket)
            ticket.callback = null;

        ticket = null;
        const url = String(remoteSource);
        const request = ++generation;
        failed = false;
        if (!/^https?:\/\//i.test(url)) {
            fetching = false;
            source = remoteSource;
            return;
        }
        fetching = true;
        source = "";
        ticket = cacheService.fetch(url, (file, error) => {
            if (request !== generation)
                return;

            if (error) {
                failed = true;
                fetching = false;
                return;
            }
            source = file;
            fetching = false;
        }, refresh);
    }

    source: ""
    asynchronous: true
    cache: true
    onRemoteSourceChanged: {
        if (initialized) {
            retried = false;
            resolve(false);
        }
    }
    onStatusChanged: {
        if (initialized && !fetching && status === Image.Error && /^https?:\/\//i.test(String(remoteSource)) && !retried) {
            retried = true;
            resolve(true);
        }
    }
    Component.onCompleted: {
        cacheService.acquire();
        initialized = true;
        resolve(false);
    }
    Component.onDestruction: {
        generation++;
        if (ticket)
            ticket.callback = null;

        cacheService.release();
    }
}
