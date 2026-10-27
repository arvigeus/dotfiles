import QtQuick
import Quickshell
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../movies"
import "../radio" as RadioUi
import "../movies/Catalogue.js" as Models

Item {
    id: root
    objectName: "musicBrowser"
    property var host
    property bool active: false
    property var toolbarTarget: null
    property var backdropTarget: null
    property real toolbarHeight: 46
    property var initialFocus: searchOpen ? search : list
    property bool initialized: false
    property string section: "library"
    property var viewStates: ({})
    property var savedViews: ({})
    property string notice: ""
    property bool restoringView: false
    property string category: "songs"
    property string genreId: ""
    property string genreName: ""
    property bool searchOpen: false
    property bool filtersOpen: false
    property bool loading: false
    property bool appending: false
    property bool needsBrowse: false
    property bool genresLoading: false
    property bool hasMore: false
    property int total: 0
    property bool libraryIndexed: false
    property bool libraryIndexing: false
    property string libraryVersion: ""
    property string libraryIndexMessage: ""
    property bool checkingIndex: false
    property int offset: 0
    property string cursor: ""
    property int generation: 0
    property var rows: []
    property var genres: []
    property var entity: null
    property bool entityReady: true
    property var entityRows: ({songs:[],artists:[],albums:[]})
    property var entityPaging: ({})
    property var history: []
    property string panel: ""
    property string error: ""
    property string saveError: ""
    property bool pendingOnly: false
    property bool refreshingFiles: false
    property string localVersion: ""
    property var artistDetails: ({})
    property int artistGeneration: 0
    property bool checkingLocal: false
    property var capabilities: ({track:false,album:false})
    readonly property bool busy: (section === "library" && libraryIndexing) || cacheService.activeJobCount > 0 || loading || genresLoading || service.activeJobCount > 0

    ListModel { id: catalogue }
    Rectangle { objectName: "musicBackground"; parent: root.backdropTarget || root; anchors.fill: parent; z: root.backdropTarget ? 0 : -1; color: "#000000"; visible: root.active }
    MusicService {
        id: service; active: root.active; observeBackgroundJobs: true
        onFailed: message => root.error = message
        onJobStartFailed: message => root.error = message
        onJobFinished: job => { root.notifyJob(job,service); if (job.error) root.error = job.error; else root.observeFiles(); }
    }
    Worker {
        id: cloudService; objectName: "musicCloudService"; backendDirectory: "spaces/music"; backend: "cloud.py"; startOnDemand: true; spaceId: "music"; serviceName: "My Library"
        onFailed: message => root.error = message
    }
    MusicService {
        id: cacheService; objectName: "musicFileService"; backend: "local_files.py"; serviceName: "Music files"; startOnDemand: true; active: root.active; observeBackgroundJobs: true
        onJobStartFailed: message => root.error = message
        onJobFinished: job => {
            root.notifyJob(job,cacheService);
            if (info.busy && String(job.job_id) === info.jobId) info.complete(job.result || {},job.error || (job.state === "cancelled" ? "Operation cancelled." : ""));
            else if (job.error) root.error = job.error;
            else root.notice = "Song cached in Music.";
            root.observeFiles(true);
        }
    }
    MusicPlayback {
        id: playback; service: service; controller: root; active: root.active
    }
    Worker { id: covers; backendDirectory: "spaces/music"; backend: "artwork.py"; spaceId: "music"; serviceName: "Music artwork"; startOnDemand: true }
    property var deliverNotification: (title,body) => Quickshell.execDetached(["notify-send","--app-name=Music","--icon=audio-x-generic","--",title,String(body).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")])
    function visibleJob(job,owner) { return (owner.jobRequests[job.job_id]?.args.action || job.result?.action) !== "info"; }
    function notifyJob(job,owner) {
        if (!visibleJob(job,owner) || job.state === "cancelled") return;
        const action = owner.jobRequests[job.job_id]?.args.action || job.result?.action;
        const failure = job.error || job.result?.error;
        if (failure) deliverNotification(job.title || "Music",failure);
        else if (action !== "save" && action !== "lyrics") deliverNotification(job.title || "Music",job.result?.message || "Completed.");
    }
    OperationCenter { id: activity; objectName: "musicNotifications"; parent: root; heading: "Notifications"; iconName: "bell"; notificationTitle: "Music"; jobs: service.jobs.filter(job => root.visibleJob(job,service)).concat(cacheService.jobs.filter(job => root.visibleJob(job,cacheService))); onCancelRequested: id => { if (cacheService.jobs.some(job => job.job_id === id)) cacheService.cancelJob(id); else service.cancelJob(id); }; onActionRequested: job => { if (cacheService.jobs.some(item => item.job_id === job.job_id)) cacheService.retryJob(job.job_id); else service.retryJob(job.job_id); } }

    function recordKey(item) { return String(item?.source || "") + "|" + String(item?.kind || "") + "|" + String(item?.id || ""); }
    function songScopeKey() { return section + ":" + (entity?.id || "") + ":" + search.text; }
    function fileAction(action,song) { cacheService.startJob("file-job",{action:action,song:song || {},title:"Cache song"}); }
    function observeFiles(force) {
        if (!active || section !== "library" || refreshingFiles) return;
        refreshingFiles = true;
        cloudService.request("local-refresh",{refresh:!!force},(result,failure) => {
            refreshingFiles = false;
            if (failure) { notice = failure; return; }
            if (result.warning) notice = result.warning;
            if (result.version && result.version !== localVersion) {
                localVersion = result.version;
                applyIndex(result.index,false);
                if (section === "library") { if (loading) needsBrowse = true; else browse(false,false,true); }
            }
        });
    }
    function applyIndex(info,requery) {
        if (!info) return;
        const changed = info.ready && (!libraryIndexed || String(info.version) !== libraryVersion);
        libraryIndexed = !!info.ready; libraryIndexing = !!info.indexing;
        if (info.version) libraryVersion = String(info.version);
        libraryIndexMessage = libraryIndexing ? "Caching library metadata · " + (info.loaded || 0).toLocaleString() + " songs" : info.indexError || "";
        if (requery && changed && section === "library") browse(false,false,true);
    }
    function indexStatus() {
        if (!active || section !== "library" || checkingIndex) return;
        checkingIndex = true;
        cloudService.request("index-status",{},(result,failure) => { checkingIndex = false; if (!failure) applyIndex(result,true); });
    }
    function refreshLocal() {
        if (!active || checkingLocal) return;
        const targets = [], positions = ({});
        for (const child of list.contentItem.children) if (child.record && child.y + child.height >= list.contentY && child.y <= list.contentY + list.height && ["nextcloud","music-local"].includes(child.record.source)) { targets.push(child.record); positions[recordKey(child.record)] = child.index; }
        if (!targets.length) return;
        const token = generation; checkingLocal = true;
        cacheService.request("states",{items:targets},(result,failure) => {
            checkingLocal = false; if (failure || token !== generation) return;
            let next = null;
            for (const state of result) {
                const key = recordKey(state), index = positions[key];
                if (index === undefined || !rows[index] || recordKey(rows[index]) !== key) continue;
                const old = rows[index];
                if (old.local === state.local && old.localPath === state.localPath && old.pendingUpload === state.pendingUpload) continue;
                if (!next) next = rows.slice();
                next[index] = Object.assign({},old,state);
                catalogue.setProperty(index,"payload",JSON.stringify(next[index]));
            }
            if (next) rows = next;
        });
    }
    function activate() { if (active) initialFocus.forceActiveFocus(); }
    function currentService(item) { return (item ? ["nextcloud","music-local"].includes(item.source) : section === "library") ? cloudService : service; }
    function initialize() {
        loading = true; error = "";
        service.request("init", {}, (result, failure) => {
            loading = false;
            if (failure) { error = failure; return; }
            const settings = result.settings || {};
            section = "library"; savedViews = settings.views || ({});
            const view = savedViews[section] || {};
            category = "songs"; pendingOnly = false;
            genreId = ""; genreName = "";
            initialized = true; browse(false); observeFiles();
            service.request("download-capabilities", {}, (value, failure) => { if (!failure) capabilities = value; });
        });
    }
    function persist() {
        if (!initialized) return;
        savedViews = Object.assign({}, savedViews, {[section]:{category:entity ? (history[0]?.category || "songs") : category,genreId:genreId,genreName:genreName,pending:pendingOnly}});
        service.request("settings-save", {settings:{section:section,views:savedViews}}, (result, failure) => saveError = failure || "");
    }
    function loadGenres() {
        if (genres.length || genresLoading) return;
        const owner = section; genresLoading = true;
        currentService().request("genres", {}, (result, failure) => {
            if (owner !== section) return;
            genresLoading = false; if (failure) error = failure; else genres = result;
        });
    }
    function updateRows(items, append) {
        rows = Models.update(catalogue, rows, items || [], append, recordKey);
        if (!append) { list.currentIndex = rows.length ? 0 : -1; list.positionViewAtBeginning(); }
        pagination.restart();
    }
    function browse(append, refresh, preserveScroll) {
        if (!initialized) return;
        if (!active) { needsBrowse = true; return; }
        if (append && (loading || !hasMore)) return;
        needsBrowse = false; searchDelay.stop(); error = ""; notice = "";
        const token = ++generation; appending = !!append;
        const previousScroll = preserveScroll ? list.contentY : 0;
        if (!append) loading = false;
        if (!append) { offset = 0; cursor = ""; hasMore = false; }
        if (entity) {
            if (["nextcloud","music-local"].includes(entity.source) && entity.kind !== "playlist" && libraryIndexed && entityReady && !refresh) {
                loading = true;
                cloudService.request("entity-browse",{entity:entity,category:category,query:search.text.trim(),offset:offset,pageSize:preserveScroll ? rows.length : 200},(result,failure) => {
                    if (token !== generation) return;
                    loading = false;
                    if (failure) { error = failure; return; }
                    updateRows(result.items,append); if (preserveScroll) list.contentY = previousScroll; total = result.total || 0; offset = result.limit || 0; hasMore = !!result.hasMore; applyIndex(result.index,false); pagination.restart();
                });
                return;
            }
            if (!entityReady || refresh) { entityReady = false; loadEntity(entity,refresh); return; }
            if (append && entity.kind === "artist" && ["songs","albums"].includes(category)) {
                const state = entityPaging[category] || {};
                loading = true;
                currentService(entity).request(category === "songs" ? "artist-songs-page" : "artist-albums-page", state, (result, failure) => {
                    if (token !== generation) return;
                    loading = false;
                    if (failure) { error = failure; return; }
                    notice = result.warning || "";
                    entityPaging = Object.assign({}, entityPaging, {[category]:Object.assign({}, state, result)});
                    const combined = (entityRows[category] || []).slice(), seen = new Set(combined.map(recordKey));
                    for (const item of result.items || []) if (!seen.has(recordKey(item))) { combined.push(item); seen.add(recordKey(item)); }
                    entityRows = Object.assign({}, entityRows, {[category]:combined});
                    renderEntity(true);
                });
                return;
            }
            renderEntity(false);
            return;
        }
        loading = true;
        currentService().request(section === "library" ? "browse" : "search-page", {query:search.text.trim(),category:section === "discover" && !search.text.trim() ? "songs" : category,genreId:category === "artists" ? "" : genreId,genreName:category === "artists" ? "" : genreName,pending:pendingOnly,offset:offset,pageSize:preserveScroll ? rows.length : 200,cursor:cursor,refresh:!!refresh}, (result, failure) => {
            if (token !== generation) return;
            loading = false;
            if (failure) { error = failure; if (section === "library") { indexStatus(); observeFiles(); } return; }
            applyIndex(result.index,false);
            updateRows(result.items, append); if (preserveScroll) list.contentY = previousScroll; total = result.total === undefined ? rows.length : result.total;
            offset = result.limit || 0; cursor = result.cursor || ""; hasMore = !!result.hasMore; notice = result.warning || "";
            pagination.restart();
            if (needsBrowse) Qt.callLater(() => browse(false,false,true));
        });
    }
    function maybeLoadMore() {
        if (active && !panel && !loading && hasMore && !error && list.contentY + list.height >= list.contentHeight - 280) browse(true);
    }
    function snapshot() { return {category:category,genreId:genreId,genreName:genreName,pending:pendingOnly,query:search.text,searchOpen:searchOpen,filtersOpen:filtersOpen,entity:entity,entityRows:entityRows,entityPaging:entityPaging,history:history,entityReady:entityReady,notice:notice,rows:rows.slice(),offset:offset,cursor:cursor,hasMore:hasMore,scroll:list.contentY,total:total,genres:genres,needsBrowse:(loading && !appending) || needsBrowse}; }
    function changeSection(value) {
        if (value === section) return;
        viewStates = Object.assign({}, viewStates, {[section]:snapshot()});
        ++generation; loading = false; genresLoading = false; genres = []; panel = ""; closeMenus();
        section = value; restoringView = true;
        const view = viewStates[value] || savedViews[value] || {};
        category = view.category || "songs"; genreId = view.genreId || ""; genreName = view.genreName || ""; pendingOnly = !!view.pending;
        search.text = view.query || ""; searchOpen = !!view.searchOpen; filtersOpen = !!view.filtersOpen;
        entity = view.entity || null; entityReady = view.entityReady !== false; entityRows = view.entityRows || ({songs:[],artists:[],albums:[]}); entityPaging = view.entityPaging || ({}); history = view.history || []; total = view.total || 0;
        genres = view.genres || []; offset = view.offset || 0; cursor = view.cursor || ""; hasMore = !!view.hasMore;
        updateRows(view.rows || [], false); restoringView = false; error = ""; notice = view.notice || ""; persist();
        if (!view.rows || view.needsBrowse) browse(false);
        else Qt.callLater(() => { list.contentY = view.scroll || 0; pagination.restart(); });
        if (entity?.kind === "artist") loadArtistInfo(entity); else { ++artistGeneration; artistDetails = ({}); }
        if (section === "library") { indexStatus(); observeFiles(); }
    }
    function changeCategory(value) { category = value; persist(); browse(false); }
    function openArtist(song) {
        select({id:(song.artistIds || [])[0] || "name:" + song.artist,source:song.source,account:song.account,kind:"artist",name:song.artist});
    }
    function openAlbum(song) {
        select({id:song.albumId || "name:" + song.album,source:song.source,account:song.account,kind:"album",title:song.album,artist:song.artist});
    }
    function renderEntity(append) {
        const query = search.text.trim().toLocaleLowerCase();
        const scroll = list.contentY;
        updateRows((entityRows[category] || []).filter(item => !query || [item.title,item.name,item.artist,item.album].filter(Boolean).join(" ").toLocaleLowerCase().includes(query)),false);
        if (append) list.contentY = scroll;
        total = rows.length; hasMore = !!entityPaging[category]?.hasMore;
        pagination.restart();
    }
    function select(item) {
        if (item.kind === "song") { if (playback.currentTrackKey === recordKey(item) && playback.playerProcess) playback.togglePause(); else playCollection(item); return; }
        history = history.concat([{entity:entity,entityRows:entityRows,entityPaging:entityPaging,category:category,entityReady:entityReady,query:search.text,rows:rows.slice(),offset:offset,cursor:cursor,hasMore:hasMore,scroll:list.contentY,total:total}]);
        entity = item; entityRows = ({songs:[],artists:[],albums:[]}); entityPaging = ({}); search.clear(); category = "songs";
        searchDelay.stop(); entityReady = false; loadEntity(item); if (item.kind === "artist") loadArtistInfo(item); else { ++artistGeneration; artistDetails = ({}); }
    }
    function loadEntity(item, refresh) {
        const token = ++generation; loading = true; error = ""; updateRows([],false);
        currentService(item).request(item.kind, {[item.kind]:item,refresh:!!refresh}, (result, failure) => {
            if (token !== generation) return;
            loading = false;
            if (failure) { error = failure; return; }
            applyIndex(result.index,false); notice = result.warning || ""; entityReady = true; entity = result[item.kind] || item;
            entityRows = ({songs:result.songs || [],artists:result.artists || [],albums:result.albums || []});
            entityPaging = ({songs:result.songPaging || {},albums:result.albumPaging || {}});
            browse(false);
        });
    }
    function back() {
        ++generation; loading = false; panel = "";
        if (!history.length) { entity = null; browse(false); return; }
        const previous = history[history.length - 1]; history = history.slice(0,-1);
        entity = previous.entity; if (entity?.kind === "artist") loadArtistInfo(entity); else { ++artistGeneration; artistDetails = ({}); } entityReady = previous.entityReady !== false; entityRows = previous.entityRows; entityPaging = previous.entityPaging; category = previous.category;
        restoringView = true; search.text = previous.query; restoringView = false; searchDelay.stop();
        total = previous.total || 0; offset = previous.offset; cursor = previous.cursor; hasMore = previous.hasMore; updateRows(previous.rows,false);
        Qt.callLater(() => { list.contentY = previous.scroll || 0; pagination.restart(); });
    }
    function playCollection(item) {
        if (section !== "library" || !libraryIndexed) {
            const songs = rows.filter(row => row.kind === "song");
            playback.playSongs(songs,Math.max(0,songs.findIndex(row => recordKey(row) === recordKey(item))));
            return;
        }
        const token = ++playback.playGeneration;
        cloudService.request("queue",{entity:entity,query:search.text.trim(),genreName:genreName,pending:pendingOnly},(result,failure) => {
            if (token !== playback.playGeneration) return;
            if (failure) { error = failure; return; }
            const songs = result.items || [];
            playback.playSongs(songs,Math.max(0,songs.findIndex(row => recordKey(row) === recordKey(item))));
        });
    }
    function loadArtistInfo(item) {
        const token = ++artistGeneration; artistDetails = ({});
        const provider = currentService(item);
        provider.request("artist-info",{artist:item},(result,failure) => {
            if (token !== artistGeneration || !entity || recordKey(entity) !== recordKey(item)) return;
            if (!failure) artistDetails = result.artist || ({});
            // Metadata enrichment never changes the library's artist identity or songs.
            if (failure || (!artistDetails.cover && !artistDetails.biography)) service.request("artist-info",{artist:{kind:"artist",name:item.name}},(extra,error) => {
                if (token === artistGeneration && !error) artistDetails = extra.artist || ({});
            });
        });
    }
    function download(item) {
        if (["nextcloud","music-local"].includes(item.source)) {
            cloudService.request("queue",{entity:item},(result,failure) => {
                if (failure) { error = failure; return; }
                cacheService.startJob("file-job",{action:"cache-collection",songs:result.items || [],title:"Cache album"});
            });
            return;
        }
        service.startJob("download_start", {kind:item.kind === "album" ? "album" : "track",item:item,title:"Save " + item.title}); activity.showActivity(); }
    function closeMenus() { genreMenu.close(); categoryChoice.popup.close(); picker.close(); }
    function dismissTransient() {
        if (info.visible) { info.dismissTransient(); return true; }
        if (activity.visible) { activity.close(); return true; }
        if (genreMenu.visible || categoryChoice.popup.visible || picker.visible) { closeMenus(); return true; }
        if (panel) { panel = ""; return true; }
        if (filtersOpen) { filtersOpen = false; return true; }
        if (search.text) { search.clear(); return true; }
        if (searchOpen) { searchOpen = false; return true; }
        if (entity) { back(); return true; }
        return false;
    }
    onActiveChanged: {
        if (!active) { if (searchDelay.running) needsBrowse = true; searchDelay.stop(); pagination.stop(); closeMenus(); info.close(); activity.close(); }
        else if (initialized) { if (needsBrowse) browse(false); pagination.restart(); refreshLocal(); observeFiles(); if (section === "library") indexStatus(); Qt.callLater(activate); }
    }
    Component.onCompleted: initialize()
    Timer { id: searchDelay; interval: 300; onTriggered: root.browse(false) }

    Timer { objectName: "musicFolderTimer"; interval: 5000; repeat: true; running: root.active && root.section === "library"; onTriggered: root.observeFiles() }
    Timer { id: pagination; interval: 120; onTriggered: { root.maybeLoadMore(); root.refreshLocal(); } }
    Timer { objectName: "musicIndexTimer"; interval: 800; repeat: true; running: root.active && root.section === "library" && root.libraryIndexing; onTriggered: root.indexStatus() }

    RowLayout {
        objectName: "musicToolbar"; parent: root.toolbarTarget || root; width: parent.width; height: root.toolbarHeight; visible: root.active; spacing: 8
        MovieIconButton { visible: !!root.entity || !!root.panel; iconName: "arrow-left"; text: "Back to music"; onClicked: root.panel ? root.panel = "" : root.back() }
        MovieTab { objectName: "musicLibraryTab"; text: "My Library"; iconName: "music"; highlighted: root.section === "library"; onClicked: root.changeSection("library") }
        MovieTab { objectName: "musicDiscoverTab"; text: "Discover"; iconName: "globe"; highlighted: root.section === "discover"; onClicked: root.changeSection("discover") }

        MovieText { text: (root.total || root.rows.length).toLocaleString(); color: MovieStyle.muted; visible: !root.panel }
        Item { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0 }
        MovieButton {
            id: genreButton; visible: root.filtersOpen && root.category !== "artists" && !root.entity; text: root.genreName || "All genres"; iconName: "music"; Layout.maximumWidth: 180
            onClicked: { root.loadGenres(); genreMenu.visible ? genreMenu.close() : genreMenu.open(); }
            RadioUi.FilterMenu {
                id: genreMenu; y: genreButton.height + 4; width: Math.min(320, root.width); height: Math.min(420, root.height)
                x: Math.min(0,(root.toolbarTarget || root).width - genreButton.mapToItem(root.toolbarTarget || root,0,0).x - width)
                options: [{id:"",name:"All genres"}].concat(root.genres); selectedNames: [genreButton.text]; placeholder: "Search genres…"
                onChosen: name => { const item = options.find(value => value.name === name); root.genreId = item?.id || ""; root.genreName = root.genreId ? name : ""; close(); root.persist(); root.browse(false); }
            }
        }
        MovieButton { id: artistPicker; objectName: "musicArtists"; visible: !root.entity && (root.section !== "library" || root.filtersOpen); text: "Artists"; onClicked: { picker.parent = artistPicker; picker.show("artists"); } }
        MovieButton { id: albumPicker; objectName: "musicAlbums"; visible: !root.entity && (root.section !== "library" || root.filtersOpen); text: "Albums"; onClicked: { picker.parent = albumPicker; picker.show("albums"); } }
        MovieButton { id: playlistPicker; objectName: "musicPlaylists"; visible: !root.entity && root.section === "library" && root.filtersOpen; text: "Playlists"; onClicked: { picker.parent = playlistPicker; picker.show("playlists"); } }
        MovieChoice { id: categoryChoice; objectName: "musicCategory"; enabled: root.entityReady; visible: root.entity?.kind === "artist"; Layout.preferredWidth: 120; model: ["Songs","Albums"]; currentIndex: root.category === "albums" ? 1 : 0; onActivated: index => root.changeCategory(index ? "albums" : "songs") }
        MovieInput { id: search; objectName: "musicSearch"; visible: root.searchOpen; Layout.preferredWidth: Math.min(280,root.width * 0.23); Layout.minimumWidth: 90; placeholderText: root.entity ? "Search this " + root.entity.kind + "…" : root.section === "library" ? "Search My Library…" : "Search Discover…"; Accessible.name: "Search music"; onTextChanged: if (root.initialized && !root.restoringView) { if (root.active) searchDelay.restart(); else root.needsBrowse = true; } onAccepted: root.browse(false) }
        Item { Layout.preferredWidth: 28; Layout.preferredHeight: 28
            ActivityIndicator {
                anchors.fill: parent; active: root.active; spinnerName: "musicLoadingIndicator"
                jobs: service.jobs.concat(cacheService.jobs)
                tasks: [
                    task(root.loading, "browse", "Loading music…"),
                    task(root.section === "library" && root.libraryIndexing, "index", root.libraryIndexMessage || "Indexing music…"),
                    task(root.genresLoading, "genres", "Loading genres…"),
                    task(service.startingJobs + cacheService.startingJobs > 0, "queue", "Queuing operation…"),
                    task(info.lookingUp, "lyrics", "Finding lyrics…"),
                    task(info.reading, "song", "Loading song details…"),
                    task(playback.preparing, "player", playback.playMessage || "Opening player…")
                ]
            }
        }
        MovieIconButton { objectName: "musicSearchButton"; iconName: "search"; text: "Search music"; highlighted: root.searchOpen; onClicked: { root.searchOpen = !root.searchOpen; if (root.searchOpen) search.forceActiveFocus(); else search.clear(); } }
        MovieIconButton { objectName: "musicFilters"; visible: !root.entity && root.category !== "artists"; iconName: "sliders-horizontal"; text: "Music filters"; highlighted: root.filtersOpen || !!root.genreId; onClicked: { root.filtersOpen = !root.filtersOpen; if (root.filtersOpen) root.loadGenres(); } }
        MovieIconButton { objectName: "musicPendingFilter"; visible: root.section === "library" && !root.entity; iconName: "upload"; text: "Not uploaded"; highlighted: root.pendingOnly; onClicked: { root.pendingOnly = !root.pendingOnly; root.browse(false); } }
        MovieIconButton { objectName: "musicNotificationsButton"; iconName: "bell"; text: "Notifications"; highlighted: activity.activeCount > 0; onClicked: activity.visible ? activity.close() : activity.showActivity() }
        MovieIconButton { objectName: "musicRefresh"; iconName: "refresh-cw"; text: "Refresh music"; enabled: !root.loading; onClicked: root.initialized ? root.browse(false,true) : root.initialize() }
    }

    ColumnLayout {
        anchors.fill: parent; spacing: 12
        RowLayout {
            visible: !!root.error || !!root.saveError; Layout.fillWidth: true
            MovieText { Layout.fillWidth: true; wrapMode: Text.Wrap; color: MovieStyle.danger; text: [root.error,root.saveError].filter(Boolean).join("\n") }
            MovieButton { text: "Retry"; visible: !!root.error; enabled: !root.loading; onClicked: root.initialized ? root.browse(false,true) : root.initialize() }
        }
        RowLayout {
            visible: !!root.entity && !root.panel; Layout.fillWidth: true
            MovieText { Layout.fillWidth: true; text: root.entity?.title || root.entity?.name || ""; font.bold: true; font.pixelSize: MovieStyle.fontSize * 1.4; elide: Text.ElideRight }
            MovieButton { text: "Play all"; iconName: "play"; enabled: root.entityReady; onClicked: { if (root.category !== "songs") root.changeCategory("songs"); root.playCollection(null); } }
            MovieIconButton { visible: root.entity?.kind === "album" && (root.entity?.source === "nextcloud" || root.capabilities.album); iconName: "download"; text: "Download album locally"; onClicked: root.download(root.entity) }

        }
        RowLayout {
            visible: root.entity?.kind === "artist" && !root.panel; Layout.fillWidth: true; spacing: 20
            Image { Layout.preferredWidth: 144; Layout.preferredHeight: 144; visible: !!root.artistDetails.cover; source: root.artistDetails.cover || ""; asynchronous: true; fillMode: Image.PreserveAspectCrop; sourceSize.width: 288; sourceSize.height: 288 }
            ScrollArea { clip: true; Layout.fillWidth: true; Layout.preferredHeight: 144; contentWidth: availableWidth
                MovieText { width: parent.width; text: root.artistDetails.biography || root.artistDetails.editorialNotes?.standard || ""; textFormat: Text.StyledText; wrapMode: Text.Wrap; color: MovieStyle.muted }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: MovieStyle.border }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            ListView {
                id: list; objectName: "musicList"; anchors.fill: parent; visible: !root.panel
                clip: true; spacing: 2; model: catalogue; activeFocusOnTab: true; keyNavigationEnabled: true; keyNavigationWraps: false
                onContentYChanged: if (root.active) pagination.restart()
                onHeightChanged: if (root.active) pagination.restart()
                Keys.onReturnPressed: if (currentItem) root.select(currentItem.record)
                Keys.onEnterPressed: if (currentItem) root.select(currentItem.record)
                Keys.onSpacePressed: playback.togglePause()
                delegate: Rectangle {
                    id: row
                    required property string payload
                    required property int index
                    readonly property var record: JSON.parse(payload)
                    readonly property bool playing: playback.currentTrackKey === root.recordKey(record)
                    width: list.width; height: Math.max(80,details.implicitHeight + 24); radius: 6
                    color: playing ? MovieStyle.accentSurface : hover.containsMouse ? "#18ffffff" : "transparent"
                    border.width: list.activeFocus && list.currentIndex === index ? 1 : 0; border.color: MovieStyle.accent
                    MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; onClicked: { list.currentIndex = row.index; list.forceActiveFocus(); } onDoubleClicked: root.select(row.record) }
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 12; spacing: 12
                        MovieIconButton { objectName: "musicPlay:" + row.index; iconName: row.record.kind !== "song" ? "chevron-right" : row.playing && !playback.playerPaused ? "pause" : "play"; text: (row.record.kind === "song" ? "Play " : "Browse ") + (row.record.title || row.record.name); onClicked: root.select(row.record) }
                        MusicCover { objectName: "musicCover:" + row.index; Layout.preferredWidth: 56; Layout.preferredHeight: 56; record: row.record; service: covers; fetchEnabled: root.active && row.y + row.height >= list.contentY && row.y <= list.contentY + list.height }
                        ColumnLayout {
                            id: details; Layout.fillWidth: true; spacing: 5
                            MovieText { Layout.fillWidth: true; text: row.record.title || row.record.name || ""; font.bold: true; font.pixelSize: MovieStyle.fontSize * 1.2; elide: Text.ElideRight }
                            RowLayout {
                                Layout.fillWidth: true; spacing: 10
                                MusicLink { objectName: "musicArtist:" + row.index; visible: !!row.record.artist; Layout.maximumWidth: Math.min(300,root.width * .25); text: row.record.artist || ""; Accessible.name: "Browse artist " + text; onClicked: root.openArtist(row.record) }
                                MovieText { visible: !!row.record.album; text: "/"; color: MovieStyle.muted }
                                MusicLink { objectName: "musicAlbum:" + row.index; visible: !!row.record.album; Layout.fillWidth: true; text: row.record.album || ""; Accessible.name: "Browse album " + text; onClicked: root.openAlbum(row.record) }
                                MovieText { visible: !row.record.album; Layout.fillWidth: true; text: row.record.releaseDate || (row.record.genres || []).join(" · "); color: MovieStyle.muted; elide: Text.ElideRight }
                            }
                        }
                        MovieText { objectName: "musicDuration:" + row.index; visible: row.record.kind === "song"; text: root.timeLabel(row.record.duration || 0); color: MovieStyle.muted; Layout.preferredWidth: 50 }
                        MovieIconButton { objectName: "musicInfo:" + row.index; visible: row.record.kind === "song"; iconName: "info"; text: "Song information"; onClicked: info.showSong(row.record) }
                        Item {
                            objectName: "musicUploadSlot:" + row.index; Layout.preferredWidth: 16; Layout.preferredHeight: 16
                            MovieIcon { anchors.fill: parent; visible: !!row.record.notUploaded || !!row.record.pendingUpload; name: "upload"; opacity: .55; Accessible.name: row.record.notUploaded ? "Not uploaded" : "Local edits" }
                        }
                        Item {
                            objectName: "musicDownloadSlot:" + row.index; Layout.preferredWidth: MovieStyle.controlHeight; Layout.preferredHeight: MovieStyle.controlHeight
                            MovieIconButton { objectName: "musicDownload:" + row.index; anchors.fill: parent; visible: row.record.source === "nextcloud" ? !row.record.local : row.record.source === "apple" && (row.record.kind === "song" ? !!root.capabilities.track : row.record.kind === "album" && !!root.capabilities.album); iconName: "download"; text: row.record.source === "nextcloud" ? "Cache song in Music" : "Download locally: " + row.record.title; onClicked: row.record.source === "nextcloud" ? root.fileAction("download",row.record) : root.download(row.record) }
                        }
                    }
                }
                WheelScroll { view: list; wheelStep: 330 }
                ScrollBar.vertical: MovieScrollBar {}
                footer: Item { width: list.width; height: root.hasMore ? 24 : 0 }
            }
            MovieText { anchors.centerIn: parent; width: Math.min(500,parent.width - 40); visible: !root.panel && !root.rows.length && !root.loading && !root.error; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: MovieStyle.muted; text: root.pendingOnly ? "No unuploaded songs match this view." : root.section === "library" ? "No music matches this library view." : "No music matches this view." }

        }
        Rectangle { Layout.fillWidth: true; height: 1; color: MovieStyle.border }
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            MovieIconButton { iconName: "skip-back"; text: "Previous song"; enabled: playback.queueSongs.length > 0; onClicked: playback.playPrevious() }
            MovieIconButton { objectName: "musicPause"; iconName: playback.playerProcess && !playback.playerPaused ? "pause" : "play"; text: "Play or pause music"; enabled: !!playback.currentTrack; onClicked: playback.togglePause() }
            MovieIconButton { iconName: "skip-forward"; text: "Next song"; enabled: playback.queueSongs.length > 0; onClicked: playback.playNext(false) }
            MovieIconButton { objectName: "musicStop"; iconName: "square"; text: "Stop Music"; enabled: !!playback.currentTrack; onClicked: playback.stopPlayback() }
            ColumnLayout {
                Layout.fillWidth: true; Layout.minimumWidth: 80; spacing: 4
                MovieText { Layout.fillWidth: true; text: playback.currentTrack ? [playback.currentTrack.title,playback.currentTrack.artist].filter(Boolean).join(" · ") : "Choose a song to start listening."; elide: Text.ElideRight; font.bold: true }
                MovieText { Layout.fillWidth: true; visible: playback.playFailed; text: playback.playMessage; elide: Text.ElideRight; color: MovieStyle.danger }
            }
            MovieText { text: root.timeLabel(playback.position) + " / " + root.timeLabel(playback.duration); color: MovieStyle.muted }
            MusicSlider { objectName: "musicSeek"; Layout.preferredWidth: Math.min(220,root.width * 0.17); from: 0; to: Math.max(1,playback.duration); value: playback.position; enabled: !!playback.playerProcess; onMoved: playback.seekTo(value); Accessible.name: "Playback position" }
            MovieIconButton { iconName: "shuffle"; text: "Shuffle"; highlighted: playback.shuffleEnabled; onClicked: playback.shuffleEnabled = !playback.shuffleEnabled }
            MovieIconButton { iconName: "repeat"; text: "Repeat queue"; highlighted: playback.repeatAllEnabled; onClicked: playback.repeatAllEnabled = !playback.repeatAllEnabled }
            MusicSlider { Layout.preferredWidth: 100; from: 0; to: 100; value: playback.volume; onMoved: playback.changeVolume(value); Accessible.name: "Music volume" }
        }
    }
    function timeLabel(seconds) { const value = Math.max(0,Math.floor(seconds)); return Math.floor(value / 60) + ":" + String(value % 60).padStart(2,"0"); }
    MusicPicker { id: picker; maximumWidth: root.width; y: parent.height + 4; x: Math.min(0,(root.toolbarTarget || root).width - parent.mapToItem(root.toolbarTarget || root,0,0).x - width); discover: root.section === "discover"; service: root.currentService(); onChosen: item => root.select(item) }
    MusicInfo {
        id: info; parent: root; files: cacheService; catalogue: service; coverService: covers
        onSaved: (song,result) => {
            root.observeFiles(true);
            if (result.synced) cloudService.request("refresh-item",{item:song,action:result.action},() => root.observeFiles());
        }
    }
}
