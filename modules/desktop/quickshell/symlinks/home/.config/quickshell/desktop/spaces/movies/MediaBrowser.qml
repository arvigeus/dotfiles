import QtQuick
import "../../ui"
import QtQuick.Controls
import QtQuick.Layouts
import QtCore
import Quickshell
import "Countries.js" as Countries
import "Catalogue.js" as Catalogue

FocusScope {
    id: root
    function fontSize(value) { return Math.round(value * MovieStyle.fontSize / 14); }
    property bool active: false
    property var initialFocus: searchOpen ? search : gridMode ? grid : rail
    property var host
    property string kind: "movie"
    readonly property string spaceId: kind === "tv" ? "series" : "movies"
    property url backgroundImage: ""
    property Item backdropTarget: null
    property Item toolbarTarget: null
    readonly property int toolbarHeight: 46
    property var titles: []
    property bool updatingCatalogue: false
    ListModel { id: catalogue }
    ListModel { id: episodeCatalogue }
    // Keep delegates and loaded textures alive: mutate rows instead of resetting a JS-array model.
    function updateCatalogue(items, append) {
        updatingCatalogue = true;
        titles = Catalogue.update(catalogue, titles, items, append);
        updatingCatalogue = false;
    }

    property var selected: ({})
    property var personal: ({favorite:false, note:"", url:""})
    property var providers: []
    property var episodeProviders: []
    property var standardProviders: []
    property var standardEpisodeProviders: []
    property var animeProviders: []
    property var tmdbGenres: []
    property var animeGenres: []
    property bool animeGenresLoading: false
    property var filters: ({})
    readonly property bool animeMode: filters.genre === "Anime" && !localMode
    readonly property bool editingAnime: genre.currentText === "Anime"
    onEditingAnimeChanged: if (editingAnime) requestAnimeGenres()
    property var seasons: []
    property var episodes: []
    property string episodeNext: ""
    property string nextPage: ""
    property string error: ""
    property string detailError: ""
    property bool loading: true
    property bool detailLoading: false
    property bool artworkLoading: false
    property bool seasonsLoading: false
    property bool personalLoading: false
    property bool filesLoading: false
    readonly property bool titleLoading: detailLoading || artworkLoading || seasonsLoading || relatedLoading || personalLoading || filesLoading || logo.loading || backdrop.loading
    property bool episodeLoading: false
    property bool playLoading: false
    property bool favorites: false
    property bool localMode: false
    property bool scanOpen: false
    property int watchIndex: 0
    property var localFiles: []
    property var torrentEpisode: ({})
    property string subtitlePath: ""
    property bool searchOpen: false
    property bool filtersOpen: false
    property int browseGeneration: 0
    property int selectionGeneration: 0
    property int episodeGeneration: 0
    property int relatedGeneration: 0
    property bool relatedLoading: false
    property int collectionsGeneration: 0
    property var collectionSections: []
    property bool collectionsLoading: false
    property bool collectionsLoaded: false
    property string collectionsError: ""
    property string linkedTitleId: ""
    property string tab: "overview"
    property var links: []
    property string spoiler: ""
    property var personDetails: ({})
    property string personRole: "All"
    property int personGeneration: 0
    readonly property var personCredits: (personDetails.credits || []).filter(t => t.kind === kind)
    readonly property var personRoles: ["All"].concat(Array.from(new Set(personCredits.reduce((roles,t) => roles.concat(t.roles || []),[]))).sort())
    property bool extraLoading: false
    property int extraGeneration: 0
    readonly property bool tabLoading: {
        switch (tab) {
        case "overview": case "cast": return detailLoading || artworkLoading;
        case "collections": return collectionsLoading;
        case "watch": case "spoilers": case "person": return extraLoading;
        case "episodes": return episodeLoading;
        case "torrent": return torrentPanel.connectionLoading || torrentPanel.searching || torrentPanel.extraSearching || torrentPanel.reviewLoading || torrentPanel.inspectLoading || torrentPanel.moreLoading || torrentPanel.startLoading || torrentPanel.launchPending || torrentPanel.tracksLoading;
        case "subtitles": return subtitlePanel.loading || subtitlePanel.searching || subtitlePanel.moreLoading || subtitlePanel.changing;
        default: return false;
        }
    }
    readonly property bool busy: loading || titleLoading || tabLoading || playLoading || animeGenresLoading || localService.pendingDownloads > 0 || localService.pendingChanges > 0 || (scanOpen && (scanPanel.scanning || scanPanel.matching))
    readonly property string loadingHint: {
        if (loading) return "Loading catalogue…";
        if (titleLoading) return kind === "tv" ? "Loading series…" : "Loading movie…";
        if (playLoading) return "Opening player…";
        if (scanOpen) return "Loading local library…";
        return ({overview:kind === "tv" ? "Loading series details…" : "Loading movie details…",cast:"Loading cast…",collections:"Loading collections…",watch:"Loading viewing options…",spoilers:"Loading spoilers…",person:"Loading filmography…",episodes:"Loading episodes…",torrent:"Loading downloads…",subtitles:"Loading subtitles…"})[tab] || "Loading…";
    }
    property bool gridMode: false
    property int providerIndex: 0
    property int trailerIndex: 0
    property bool artworkReady: false
    readonly property var trailers: selected.trailers || []
    readonly property var cast: selected.cast || []
    readonly property var directors: uniquePeople(cast.filter(p => ["director","co-director","creator","series director"].includes((p.job || p.role || "").toLowerCase())))
    readonly property var writers: uniquePeople(cast.filter(p => ["writer","screenplay","story","teleplay","novel","characters","original story","comic book"].includes((p.job || p.role || "").toLowerCase())))
    readonly property var stars: cast.filter(p => p.department === "Acting" || (!p.department && !/director|writer|screenplay|creator/i.test(p.role || ""))).slice(0,6)
    Settings {
        id: preferences
        location: "file://" + (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/spaces/" + root.spaceId + "/media-ui.ini"
    }
    MediaService { id: service; spaceId: root.spaceId; onFailed: message => root.error = message }
    TorrentService {
        id: localService
        spaceId: root.spaceId
        objectName: "torrentService"
        monitorJobs: true
        foreground: root.active
        monitorKind: root.kind
        onFailed: message => root.detailError = message
        onLibraryChanged: root.refreshLocalLibrary()
    }


    function refreshLocalLibrary() {
        if (selected.id) {
            const selection = selectionGeneration;
            service.fetch("local_files", {title:selected}, (result, failure) => {
                if (selection !== selectionGeneration || failure) return;
                localFiles = result;
                if (kind === "tv" && tab === "episodes" && localMode) showLocalEpisodes();
            });
        }
        if (localMode) browse(false);
    }
    MovieBackdrop {
        id: backdrop
        ownerKey: root.selected.id || ""
        poster: root.selected.poster || ""
        objectName: "movieBackdrop"
        gridMode: root.gridMode
        readingEdge: Math.min(0.75, (16 + Math.min(root.width * 0.7, 1000)) / Math.max(1, root.width))
        parent: root.backdropTarget || root
        anchors.fill: parent
        z: root.backdropTarget ? 0 : -1
        visible: root.active
        source: root.active ? root.backgroundImage : ""
    }

    ImageGallery { id: gallery; parent: root }

    function sameTitle(a, b) {
        return !!(a.id && b.id && (a.id === b.id ||
            (a.imdbId && a.imdbId === b.imdbId) ||
            (a.tmdbId && a.kind === b.kind && a.tmdbId === b.tmdbId)));
    }
    function dismissTransient() {
        if (gallery.visible) { gallery.close(); return true; }
        function closePopup(item) {
            if (item.popup && item.popup.visible) { item.popup.close(); return true; }
            if (item !== root && item.dismissTransient && item.dismissTransient()) return true;
            for (const child of item.children || []) if (closePopup(child)) return true;
            return false;
        }
        if (closePopup(toolbar) || closePopup(root)) return true;
        if (searchOpen) { searchOpen = false; search.text = ""; return true; }
        if (filtersOpen) { filtersOpen = false; return true; }
        return false;
    }
    onActiveChanged: if (!active) {
        gallery.close();
        selectionDelay.stop();
        pagination.stop();
        searchDelay.stop();
    } else {
        if (detailLoading) selectionDelay.restart();
        if (search.text) searchDelay.restart();
        pagination.restart();
    }
    function openUrl(url) { Browser.open(url, kind === "tv" ? "series" : "movies", "", host); }
    function localSeasons(files) { return Array.from(new Set(files.map(file => file.season))).sort((a,b) => a-b); }
    function clearSelection() {
        ++selectionGeneration; selectionDelay.stop();
        selected = ({}); localFiles = []; backgroundImage = "";
        detailLoading = false; artworkLoading = false; seasonsLoading = false; personalLoading = false; filesLoading = false;
        ++episodeGeneration; seasons = []; episodes = []; episodeCatalogue.clear(); episodeNext = ""; episodeLoading = false;
    }
    function uniquePeople(people) {
        const seen = new Set();
        return people.filter(person => { const key = person.id || person.name; if (seen.has(key)) return false; seen.add(key); return true; });
    }
    function genreChoices(names) {
        const choices = ["All genres"].concat(names);
        const animation = choices.indexOf("Animation");
        choices.splice(animation < 0 ? 1 : animation + 1, 0, "Anime");
        return choices;
    }
    function requestAnimeGenres() {
        if (animeGenres.length || animeGenresLoading) return;
        animeGenresLoading = true;
        service.fetch("anime_genres", {}, (result, failure) => {
            animeGenresLoading = false;
            if (!failure && result) animeGenres = result;
        });
    }
    onAnimeModeChanged: {
        ++browseGeneration; ++selectionGeneration; ++episodeGeneration; ++relatedGeneration; ++collectionsGeneration;
        selectionDelay.stop();
        updateCatalogue([], false);
        selected = ({}); backgroundImage = ""; seasons = []; episodes = []; episodeCatalogue.clear(); nextPage = "";
        detailLoading = false; artworkLoading = false; seasonsLoading = false; personalLoading = false; filesLoading = false; episodeLoading = false; playLoading = false; relatedLoading = false; linkedTitleId = "";
        collectionSections = []; collectionsLoading = false; collectionsLoaded = false; collectionsError = "";
        providers = animeMode ? animeProviders : standardProviders;
        episodeProviders = animeMode ? animeProviders.map(() => true) : standardEpisodeProviders;
        watchIndex = 0; providerIndex = 0;
        if (animeMode) requestAnimeGenres();
    }
    function activate() { (gridMode ? grid : rail).forceActiveFocus(); }
    onGridModeChanged: { activate(); pagination.restart(); }
    function maybeLoadMore() {
        if (!active) return;
        if (loading || error || !nextPage || favorites) return;
        const nearEnd = gridMode ? grid.contentY + grid.height >= grid.contentHeight - grid.cellHeight * 2
                                 : (rail.contentX > rail.originX || rail.currentIndex >= titles.length - 5) && rail.contentX + rail.width >= rail.contentWidth - rail.width * 0.5;
        if ((gridMode && titles.length < 60) || nearEnd) browse(true);
    }
    function keepLinkedSelection() { return !!linkedTitleId && selected.id === linkedTitleId; }
    function releaseLinkedSelection(event) {
        if ([Qt.Key_Up,Qt.Key_Down,Qt.Key_Left,Qt.Key_Right,Qt.Key_Home,Qt.Key_End,
             Qt.Key_PageUp,Qt.Key_PageDown].includes(event.key)) linkedTitleId = "";
        event.accepted = false;
    }
    function browse(append, keepSelection) {
        if (!append && !keepSelection) linkedTitleId = "";
        if (localMode) {
            const generation = ++browseGeneration;
            loading = true; error = ""; nextPage = "";
            service.fetch("local_titles", {kind:kind}, (result, failure) => {
                if (generation !== browseGeneration) return;
                loading = false;
                if (failure) { error = failure; return; }
                const query = search.text.trim().toLowerCase();
                updateCatalogue(result.items.filter(t => !query || t.title.toLowerCase().includes(query)), false);
                if (titles.some(t => !t.poster)) service.fetch("local_posters", {kind:kind}, (posters, posterError) => {
                    if (generation !== browseGeneration || !localMode || posterError || !posters) return;
                    const byId = {};
                    for (const item of posters) byId[item.id] = item.poster;
                    updateCatalogue(titles.map(item => byId[item.id]
                        ? Object.assign({}, item, {poster:byId[item.id]}) : item), false);
                });
                if (titles.length) { if (!keepLinkedSelection() && !titles.some(t => sameTitle(t, selected))) selectTitle(titles[0]); }
                else if (!keepLinkedSelection()) clearSelection();
            });
            return;
        }
        if (append && (loading || !nextPage)) return;
        const requestedPage = append ? nextPage : "";
        const generation = ++browseGeneration;
        loading = true; error = "";
        if (!append) service.fetch("snapshot", {kind:kind,query:search.text,filters:filters,favorites:favorites}, (result, failure) => {
            if (generation !== browseGeneration || !loading || failure || !result) return;
            updateCatalogue(result.items, false);
            nextPage = result.next || "";
            if (titles.length && !keepLinkedSelection() && !titles.some(t => sameTitle(t, selected))) selectTitle(titles[0]);
        });
        service.fetch("browse", {kind:kind,query:search.text,filters:filters,favorites:favorites,page:append ? nextPage : ""}, (result, failure) => {
            if (generation !== browseGeneration) return;
            loading = false;
            if (failure) { error = failure; return; }
            updateCatalogue(result.items, append);
            nextPage = result.next && result.next !== requestedPage ? result.next : "";
            pagination.restart();
            if (result.warning) error = result.warning;
            if (!append) {
                if (titles.length) { if (!keepLinkedSelection() && !titles.some(t => sameTitle(t, selected))) selectTitle(titles[0]); }
                else if (!keepLinkedSelection()) clearSelection();
            }
        });
    }
    function selectTitle(title) {
        if (sameTitle(selected, title)) return;
        linkedTitleId = ""; ++relatedGeneration; relatedLoading = false;
        ++collectionsGeneration; collectionSections = []; collectionsLoading = false; collectionsLoaded = false; collectionsError = "";
        const generation = ++selectionGeneration;
        ++episodeGeneration;
        personalLoading = true; filesLoading = !animeMode;
        selected = title; backgroundImage = title.backdrop || ""; artworkReady = false; trailerIndex = 0; detailLoading = true; artworkLoading = !animeMode; seasonsLoading = kind === "tv"; detailError = "";
        localFiles = []; torrentEpisode = ({}); subtitlePath = ""; watchIndex = 0;
        personal = ({favorite:false,note:"",url:""}); seasons = []; episodes = []; episodeCatalogue.clear(); episodeNext = "";
        episodeLoading = false; playLoading = false; tab = "overview"; links = []; spoiler = ""; extraLoading = false;
        if (active && (service.hasCached("details", {title:title}) || service.hasCached("artwork", {title:title}))) {
            selectionDelay.stop();
            hydrateSelection();
        } else selectionDelay.restart();
    }
    function openTitle(title) {
        if (!title || !title.id || title.kind !== kind) return;
        const needsBrowse = localMode || favorites || !animeMode || !!search.text ||
            !!filters.animeGenre || !!filters.sort || !!filters.country ||
            !!filters.minYear || !!filters.maxYear || !!filters.rating || !!filters.votes;
        localMode = false; favorites = false; scanOpen = false;
        filters = ({genre:"Anime"});
        search.text = ""; searchDelay.stop();
        selectTitle(title);
        linkedTitleId = title.id;
        if (needsBrowse) browse(false, true);
    }
    function handleOpen(payload) {
        if (payload && payload.title) openTitle(payload.title);
    }
    function openRelated(row) {
        if (!row || !row.malId) return;
        const request = ++relatedGeneration;
        const selection = selectionGeneration;
        relatedLoading = true; detailError = "";
        service.fetch("anime_entry", {malId:row.malId}, (title, failure) => {
            if (request !== relatedGeneration || selection !== selectionGeneration) return;
            relatedLoading = false;
            if (failure) { detailError = failure; return; }
            if (title.kind === kind) openTitle(title);
            else if (!host || !["movie", "tv"].includes(title.kind) ||
                     !host.openModule(title.kind === "movie" ? "movies" : "series", {title: title}))
                detailError = "The matching media module is unavailable.";
        });
    }
    function openCollections(refresh) {
        tab = "collections";
        if (!selected.id || collectionsLoading || (collectionsLoaded && !refresh)) return;
        const generation = ++collectionsGeneration;
        const selection = selectionGeneration;
        collectionsLoading = true; collectionsError = "";
        service.fetch("collections", {title:selected,refresh:!!refresh}, (result, failure) => {
            if (generation !== collectionsGeneration || selection !== selectionGeneration) return;
            collectionsLoading = false;
            if (failure) { collectionsError = failure; return; }
            collectionSections = result.sections || [];
            collectionsLoaded = true;
        });
    }
    Timer { id: selectionDelay; interval: 90; onTriggered: root.hydrateSelection() }
    function refreshTitle() {
        ++selectionGeneration;
        ++collectionsGeneration; collectionsLoading = false; collectionsLoaded = false; collectionsError = "";
        selectionDelay.stop();
        detailLoading=true; artworkLoading=!animeMode; seasonsLoading=kind === "tv";
        detailError=""; artworkReady=false;
        hydrateSelection(true);
        if (tab === "collections") openCollections(true);
    }
    function hydrateSelection(refresh) {
        if (!selected.id) return;
        const title = selected;
        const generation = selectionGeneration;
        personalLoading = true; filesLoading = !animeMode;
        service.fetch("personal", {title:title}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            personalLoading = false;
            if (!failure) personal = result;
        });
        if (!animeMode) service.fetch("local_files", {title:title}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            filesLoading = false;
            if (!failure) {
                localFiles = result;
                if (kind === "tv" && result.length && (localMode || !seasons.length))
                    seasons = localSeasons(result);
                if (kind === "tv" && result.length && tab === "episodes" && !episodes.length && !episodeLoading)
                    loadEpisodes(false);
            }
        });
        service.fetch("details", {title:title,refresh:!!refresh}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            detailLoading = false;
            if (failure) detailError = failure;
            else applyDetails(result);
        });
        if (!animeMode) service.fetch("artwork", {title:title,refresh:!!refresh}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            artworkLoading = false;
            if (failure) detailError = failure;
            if (!failure) {
                applyDetails(result.title); artworkReady = true;
                if (result.warnings.length) detailError = "Some extra artwork or ratings could not load. " + result.warnings.join(" ");
            }
        });
        if (kind === "tv") service.fetch("episodes", {title:title}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            seasonsLoading = false;
            if (!failure) { seasons = localMode && localFiles.length ? localSeasons(localFiles) : result.seasons; if (tab === "episodes") loadEpisodes(false); }
            else if (!localFiles.length) detailError = failure;
        });
    }
    function applyDetails(result) {
        const patch = Object.assign({}, result);
        if (!backgroundImage.toString() && patch.backdrop) backgroundImage = patch.backdrop;
        else if (backgroundImage.toString()) patch.backdrop = backgroundImage.toString();
        // Artwork responses own enriched fields; a slower details response must not revert them.
        if (artworkReady) ["backdrop","logo","ratings","cast","trailers","screenshots"].forEach(key => delete patch[key]);
        selected = Object.assign({}, selected, patch);
        if (localMode && selected.id && selected.poster)
            updateCatalogue(titles.map(item => sameTitle(item, selected)
                ? Object.assign({}, item, {poster:selected.poster, backdrop:selected.backdrop || item.backdrop}) : item), false);
    }
    function save(values) {
        const generation = selectionGeneration;
        service.fetch("save", {title:selected,values:values}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            if (failure) detailError = failure; else personal = result;
        });
    }
    function play(episode, online) {
        if (!episode && kind === "tv" && !animeMode && (localFiles.length || episodeProviders[providerIndex])) {
            tab = "episodes";
            if (!episodes.length && !episodeLoading) loadEpisodes(false);
            return;
        }
        const generation = selectionGeneration;
        playLoading = true;
        detailError = "";
        service.fetch("play", {title:selected,online:!!online,provider:providerIndex,season:episode ? episode.season : null,episode:episode ? episode.number : null}, (result, failure) => {
            if (generation !== selectionGeneration) return;
            playLoading = false;
            if (failure) detailError = failure;
            else if (result.type === "direct") External.launch(result.command, root.host);
            else openUrl(result.url);
        });
    }
    function loadEpisodes(append) {
        if (!selected.id || !seasons.length) return;
        const generation = ++episodeGeneration;
        const selection = selectionGeneration;
        episodeLoading = true;
        if (!append) { episodes = []; episodeCatalogue.clear(); }
        if (localMode && localFiles.length) {
            showLocalEpisodes();
            return;
        }
        service.fetch("episodes", {title:selected,season:seasons[Math.max(0,seasonPicker.currentIndex)],page:append ? episodeNext : ""}, (result, failure) => {
            if (selection !== selectionGeneration || generation !== episodeGeneration) return;
            episodeLoading = false;
            if (failure) {
                if (localFiles.length) showLocalEpisodes();
                else detailError = failure;
            } else {
                episodes = (append ? episodes : []).concat(result.items);
                for (const episode of result.items) episodeCatalogue.append({payload:JSON.stringify(episode)});
                episodeNext = result.next;
            }
        });
    }
    function showLocalEpisodes() {
        if (!localFiles.length) return;
        const chosen = Number(seasons[Math.max(0,seasonPicker.currentIndex)]);
        const rows = localFiles.filter(file => Number(file.season) === chosen).map(file => ({season:file.season,number:file.episode,title:file.episodeTitle || "Episode " + file.episode}));
        episodeCatalogue.clear();
        episodes = rows;
        for (const episode of rows) episodeCatalogue.append({payload:JSON.stringify(episode)});
        episodeNext = ""; episodeLoading = false;
    }
    function deleteLocal(path) {
        if (!path) return;
        localService.change("delete_local", {path:path}, (result, failure) => {
            if (failure) { detailError = failure; return; }
            service.fetch("local_files", {title:selected}, (files, error) => {
                if (!error) { localFiles = files; if (!files.length) { watchIndex = 0; if (tab === "subtitles") tab = "overview"; } }
                if (localMode) browse(false);
                if (kind === "tv") loadEpisodes(false);
            });
        });
    }
    function showPerson(person) {
        tab = "person"; detailError = ""; personRole = "All"; const personRequest = ++personGeneration; const request = ++extraGeneration; extraLoading = true; personDetails = ({name:person.name});
        const generation = selectionGeneration;
        service.fetch("person", {person:person}, (result, failure) => {
            if (generation !== selectionGeneration || personRequest !== personGeneration || request !== extraGeneration) return;
            extraLoading = false;
            if (failure) detailError = failure; else personDetails = result;
        });
    }
    function extra(op) {
        tab = op; extraLoading = true; detailError = "";
        const generation = selectionGeneration;
        const request = ++extraGeneration;
        if (op === "watch") links = []; else spoiler = "";
        service.fetch(op, {title:selected}, (result, failure) => {
            if (generation !== selectionGeneration || request !== extraGeneration) return;
            extraLoading = false;
            if (failure) detailError = failure;
            else if (op === "watch") links = result;
            else spoiler = result.text;
        });
    }
    Component.onCompleted: {
        service.fetch("init", {kind:kind}, (result, failure) => { if (failure) error = failure; else { standardProviders = result.providers; standardEpisodeProviders = result.episodeProviders || []; animeProviders = result.animeProviders || []; tmdbGenres = result.genres || []; providers = animeMode ? animeProviders : standardProviders; episodeProviders = animeMode ? animeProviders.map(() => true) : standardEpisodeProviders; gridMode = preferences.value("catalogue/grid", kind === "movie" ? preferences.value("movie/grid", false) : false); } });
        service.fetch("local_titles", {kind:kind}, (result, failure) => {
            if (linkedTitleId) return;
            localMode = !failure && !!result && result.items.length > 0;
            browse(false);
        });
    }
    Timer { id: pagination; interval: 100; onTriggered: root.maybeLoadMore() }
    Timer { id: searchDelay; interval: 350; onTriggered: root.browse(false) }
    RowLayout {
        id: toolbar
        objectName: "movieToolbar"
        parent: root.toolbarTarget || root
        width: parent.width
        height: root.toolbarHeight
        visible: root.active
        spacing: 8
        MovieButton { iconName: "folder-open"; text: "Local"; highlighted: root.localMode; onClicked: { root.localMode = true; root.favorites = false; root.scanOpen = false; root.browse(false); } }
        MovieButton { iconName: "globe"; text: "Browse"; highlighted: !root.localMode && !root.favorites; onClicked: { root.localMode = false; root.favorites = false; root.scanOpen = false; root.browse(false); } }
        MovieButton { iconName: "star"; text: "Favorites"; highlighted: !root.localMode && root.favorites; onClicked: { root.localMode = false; root.favorites = true; root.scanOpen = false; root.browse(false); } }
        MovieButton { visible: root.localMode; iconName: "file-search-corner"; text: "Scan"; highlighted: root.scanOpen; onClicked: root.scanOpen = !root.scanOpen }
        Item { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0 }
        Flickable {
            id: inlineFilters; objectName: "inlineFilters"
            visible: root.filtersOpen && !root.favorites && !root.localMode
            Layout.fillWidth: true; Layout.preferredWidth: filterFields.implicitWidth
            Layout.minimumWidth: 120; Layout.maximumWidth: filterFields.implicitWidth
            Layout.preferredHeight: 46
            clip: true; contentWidth: filterFields.implicitWidth; contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            WheelScroll { view: inlineFilters; orientation: Qt.Horizontal; verticalToHorizontal: true }
            ScrollBar.horizontal: MovieScrollBar {}
            Row {
                id: filterFields; spacing: 8
                MovieChoice { id: genre; objectName: "genrePicker"; width: root.kind === "tv" ? 200 : 165; model: root.genreChoices(root.tmdbGenres); Accessible.name: "Genre" }
                MovieChoice { id: animeGenre; visible: root.editingAnime; width: 160; model: [{id:"",name:"All anime genres"}].concat(root.animeGenres); textRole: "name"; Accessible.name: "Anime genre" }
                MovieChoice { id: sort; width: 150; model: root.editingAnime ? ["Default order","Popularity","Highest score","Most listed","Newest release","Oldest release"] : ["Default order","Popularity","Highest rating","Most votes","Newest release","Oldest release"]; Accessible.name: "Sort" }
                MovieChoice { id: country; objectName: "countryPicker"; visible: !root.editingAnime; width: 160; model: Countries.options; textRole: "name"; Accessible.name: "Country" }
                MovieInput { id: minYear; width: 90; placeholderText: "From year"; validator: IntValidator { bottom: 1870; top: 2200 } }
                MovieInput { id: maxYear; width: 90; placeholderText: "To year"; validator: IntValidator { bottom: 1870; top: 2200 } }
                MovieInput { id: rating; width: root.editingAnime ? 125 : 95; placeholderText: root.editingAnime ? "Min AniList score" : "Min rating"; validator: DoubleValidator { bottom: 0; top: 10 } }
                MovieInput { id: votes; visible: !root.editingAnime; width: 95; placeholderText: "Min votes"; validator: IntValidator { bottom: 0 } }
                MovieButton { objectName: "applyFilters"; text: "Apply"; onClicked: { root.filters = {genre:genre.currentIndex ? genre.currentText : "",animeGenre:root.editingAnime && animeGenre.currentIndex ? root.animeGenres[animeGenre.currentIndex-1].id : "",sort:["","popular","rating","votes","newest","oldest"][sort.currentIndex],country:root.editingAnime ? "" : Countries.options[country.currentIndex].code,minYear:minYear.text,maxYear:maxYear.text,rating:rating.text,votes:root.editingAnime ? "" : votes.text}; root.browse(false); } }
                MovieButton { objectName: "resetFilters"; text: "Reset"; onClicked: { genre.currentIndex=0; animeGenre.currentIndex=0; sort.currentIndex=0; country.currentIndex=0; minYear.clear(); maxYear.clear(); rating.clear(); votes.clear(); root.filters=({}); root.browse(false); } }
            }
        }
        MovieInput {
            id: search; rightPadding: 42; visible: root.searchOpen; Layout.preferredWidth: Math.min(320, root.width * 0.30)
            objectName: "mediaSearch"
            placeholderText: root.animeMode ? "Search anime…" : root.kind === "tv" ? "Search TV series…" : "Search movies…"
            onTextChanged: searchDelay.restart()
            MovieIconButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 36; height: 36; visible: search.text.length > 0; iconName: "x"; text: "Clear search"; onClicked: { search.clear(); search.forceActiveFocus(); } }
            onAccepted: { searchDelay.stop(); root.browse(false); }
        }
        Item {
            Layout.minimumWidth: 28; Layout.maximumWidth: 28; Layout.preferredHeight: 28
            MovieSpinner {
                id: loadingIndicator
                objectName: "movieLoadingIndicator"
                anchors.fill: parent
                visible: running
                running: root.active && root.busy && !gallery.visible
                Accessible.name: root.loadingHint
                PassiveToolTip { target: loadingIndicator; text: root.loadingHint }
            }
        }
        MovieIconButton { objectName: "searchButton"; Layout.minimumWidth: 42; Layout.maximumWidth: 42; highlighted: root.searchOpen; iconName: "search"; text: "Search " + (root.kind === "tv" ? "TV series" : "movies"); onClicked: { root.searchOpen = !root.searchOpen; if (root.searchOpen) search.forceActiveFocus(); else search.text = ""; } }
        MovieIconButton { objectName: "filtersButton"; Layout.minimumWidth: 42; Layout.maximumWidth: 42; iconName: "sliders-horizontal"; text: "Filters"; enabled: !root.favorites && !root.localMode; highlighted: root.filtersOpen; onClicked: root.filtersOpen = !root.filtersOpen }
        MovieIconButton { objectName: "catalogueLayoutToggle"; Layout.minimumWidth: 42; Layout.maximumWidth: 42; iconName: root.gridMode ? "panels-top-left" : "layout-grid"; text: root.gridMode ? "Show poster rail" : "Show grid"; onClicked: { root.gridMode = !root.gridMode; preferences.setValue("catalogue/grid",root.gridMode); } }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: root.toolbarTarget ? 0 : root.toolbarHeight + 12
        spacing: 12
        RowLayout {
            visible: !!root.error; Layout.fillWidth: true
            MovieText { text: root.error; color: MovieStyle.danger; Layout.fillWidth: true; wrapMode: Text.Wrap }
            MovieButton { text: "Retry"; onClicked: root.browse(false) }
        }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            LocalScan {
                id: scanPanel
                showLoading: false
                service: localService
                anchors.fill: parent; visible: root.localMode && root.scanOpen
                kind: root.kind
                onImported: root.browse(false)
            }
            GridView {
                id: grid; cacheBuffer: height * 1.5; objectName: "catalogueGrid"; visible: root.gridMode && !root.scanOpen
                width: parent.width * 0.51; height: parent.height
                clip: true; model: catalogue
                cellWidth: width / Math.max(2,Math.floor(width/155)); cellHeight: cellWidth*1.5+48
                keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: Poster {
                    required property string payload
                    readonly property var modelData: JSON.parse(payload)
                    required property int index
                    width: grid.cellWidth-8; height: grid.cellHeight-8; title: modelData
                    highlighted: root.sameTitle(root.selected, modelData)
                    onClicked: { grid.forceActiveFocus(); grid.currentIndex=index; root.selectTitle(modelData); }
                }
                onCurrentItemChanged: if (!root.updatingCatalogue && !root.keepLinkedSelection() && activeFocus && currentItem && !root.sameTitle(currentItem.title, root.selected)) root.selectTitle(currentItem.title)
                Keys.onPressed: event => root.releaseLinkedSelection(event)
                Keys.onReturnPressed: if (currentItem) root.selectTitle(currentItem.title)
                Keys.onEnterPressed: if (currentItem) root.selectTitle(currentItem.title)
                WheelScroll { objectName: "gridWheel"; view: grid; wheelStep: Math.max(360, grid.cellHeight * 1.25) }
                onContentYChanged: pagination.restart()
                ScrollBar.vertical: MovieScrollBar {}
            }
            ColumnLayout {
                id: detail; x: root.gridMode ? parent.width*0.55 : 16
                width: root.gridMode ? parent.width*0.45 : Math.min(parent.width*0.7,1000)
                height: root.gridMode ? parent.height : parent.height - Math.min(270,parent.height*0.38)
                visible: !!root.selected.id && !root.scanOpen; spacing: 8
                Item {
                    Layout.fillWidth: true; Layout.preferredHeight: Math.max(72,Math.min(145,root.height*0.17))
                    CrossfadeImage { id: logo; resetOnSourceChange: true; anchors.fill: parent; source: root.selected.logo || ""; fillMode: Image.PreserveAspectFit; horizontalAlignment: Image.AlignLeft; imageWidth: 900 }
                    MovieText { anchors.fill: parent; opacity: 1 - logo.imageOpacity; visible: opacity > 0; text: root.selected.title || ""; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(Math.min(48,root.width/25)); font.bold: true; wrapMode: Text.Wrap; maximumLineCount: 2; verticalAlignment: Text.AlignVCenter }
                }
                MovieText { Layout.fillWidth: true; text: [root.selected.year,root.animeMode ? root.selected.format : (root.selected.runtime ? root.selected.runtime + " min" : ""),root.animeMode && root.kind === "tv" && root.selected.episodesCount ? root.selected.episodesCount + (root.selected.episodesCount === 1 ? " episode" : " episodes") : "",(root.selected.genres || []).join(" / ")].filter(Boolean).join("   ·   "); color: MovieStyle.muted }
                MovieText { visible: root.animeMode && !!(root.selected.premiere || root.selected.sourceMaterial || root.selected.ageRating); Layout.fillWidth: true; text: [root.selected.premiere,root.selected.sourceMaterial ? "Source: " + root.selected.sourceMaterial : "",root.selected.ageRating ? "Rated " + root.selected.ageRating : ""].filter(Boolean).join("   ·   "); color: MovieStyle.muted; wrapMode: Text.Wrap }
                Ratings { host: root.host; Layout.fillWidth: true; Layout.minimumHeight: 28; ratings: root.selected.ratings || []; title: root.selected }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    SplitButton {
                        objectName: "onlineButton"
                        showLoading: false
                        busy: root.playLoading
                        enabled: !root.playLoading && (root.localFiles.length > 0 || root.providers.length > 0)
                        text: root.localFiles.length && root.watchIndex === 0 ? "Watch locally" : "Watch online"
                        options: (root.localFiles.length ? ["Local"] : []).concat(root.providers)
                        currentIndex: root.watchIndex
                        onTriggered: index => {
                            root.watchIndex = index;
                            if (root.localFiles.length && index === 0) root.play(null, false);
                            else { root.providerIndex = index - (root.localFiles.length ? 1 : 0); root.play(null, true); }
                        }
                    }
                    SplitButton { visible: root.trailers.length > 0; text: root.trailers.length === 1 ? "Trailer" : "Trailers"; options: root.trailers.map(t => t.title); currentIndex: root.trailerIndex; onTriggered: index => { root.trailerIndex=index; if (root.trailers[index]) root.openUrl(root.trailers[index].url); } }
                    MovieIconButton { iconName: root.personal.favorite ? "star-filled" : "star"; text: root.personal.favorite ? "Remove favorite" : "Add favorite"; onClicked: root.save({favorite:!root.personal.favorite}) }
                    MovieIconButton { iconName: "refresh-cw"; text: "Refresh title"; onClicked: root.refreshTitle() }
                    HoldDelete { localHint: "Delete local movie folder"; visible: root.kind === "movie" && root.localFiles.length > 0; torrent: root.localFiles.length > 0 && root.localFiles[0].torrent; onActivated: root.deleteLocal(root.localFiles[0].path) }
                }
                Flow {
                    Layout.fillWidth: true; spacing: 4
                    MovieTab { text: "Overview"; highlighted: root.tab === "overview"; onClicked: root.tab="overview" }
                    MovieTab { objectName: "collectionsTab"; text: "Collections"; highlighted: root.tab === "collections"; onClicked: root.openCollections(false) }
                    MovieTab { text: "Cast"; visible: !root.animeMode || root.cast.length > 0; highlighted: root.tab === "cast"; onClicked: root.tab="cast" }
                    MovieTab { objectName: "episodesTab"; text: "Episodes"; visible: root.kind === "tv"; highlighted: root.tab === "episodes"; onClicked: { root.tab="episodes"; if (!root.episodes.length) root.loadEpisodes(false); } }
                    MovieTab { text: "Services"; visible: !root.animeMode; highlighted: root.tab === "watch"; onClicked: root.extra("watch") }
                    MovieTab { objectName: "spoilersTab"; text: "Spoilers"; visible: root.kind === "movie" || root.animeMode; highlighted: root.tab === "spoilers"; onClicked: root.extra("spoilers") }
                    MovieTab { text: "Subtitles"; visible: root.localFiles.length > 0; highlighted: root.tab === "subtitles"; onClicked: { root.subtitlePath = root.kind === "movie" ? root.localFiles[0].path : root.subtitlePath; root.tab = "subtitles"; } }
                    MovieTab { objectName: "findTab"; text: "Find"; visible: root.localFiles.length === 0; highlighted: root.tab === "torrent"; onClicked: { root.torrentEpisode = ({}); root.tab = "torrent"; } }
                }
                MovieText { visible: !!root.detailError; Layout.fillWidth: true; text: root.detailError; color: MovieStyle.danger; wrapMode: Text.Wrap; maximumLineCount: 2 }
                ScrollArea {
                    visible: !["collections","cast","person","episodes","torrent","subtitles"].includes(root.tab)
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width; spacing: 12
                        MovieText { visible: root.tab === "overview"; Layout.fillWidth: true; text: root.selected.plot || (root.titleLoading ? "" : "No synopsis available."); wrapMode: Text.Wrap; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(16) }
                        MovieText { visible: root.tab === "overview"; Layout.fillWidth: true; text: root.animeMode ? (root.selected.studios || []).join(" / ") : (root.selected.countries || []).map(Countries.label).join(" / "); color: MovieStyle.muted; wrapMode: Text.Wrap }
                        MovieText { visible: root.tab === "overview" && root.animeMode && !!root.selected.background; Layout.fillWidth: true; text: root.selected.background || ""; wrapMode: Text.Wrap; color: MovieStyle.muted }
                        Repeater {
                            model: root.tab === "overview" ? [{label:"Directed by",people:root.directors},{label:"Written by",people:root.writers},{label:root.animeMode ? "Voices" : "Starring",people:root.stars}] : []
                            ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true; visible: modelData.people.length > 0; spacing: 3
                                MovieText { text: modelData.label; color: MovieStyle.muted }
                                Flow {
                                    Layout.fillWidth: true; spacing: 4
                                    Repeater { model: modelData.people; RowLayout {
                                        required property var modelData
                                        spacing: 0
                                        CrossfadeImage { source: modelData.image || ""; imageWidth: 84; Layout.preferredWidth: 36; Layout.preferredHeight: 48 }
                                        MovieButton { text: modelData.name; enabled: !!modelData.id || !!modelData.url; onClicked: modelData.url ? root.openUrl(modelData.url) : root.showPerson(modelData) }
                                    } }
                                }
                            }
                        }
                        ImageStrip {
                            visible: root.tab === "overview" && images.length > 0
                            Layout.fillWidth: true
                            Layout.preferredHeight: visible ? 116 : 0
                            images: root.selected.screenshots || []
                            onActivated: index => gallery.show(images, index, root.selected.title)
                        }
                        Repeater { model: root.tab === "watch" ? root.links : []; MovieButton { required property var modelData; text: modelData.name; onClicked: root.openUrl(modelData.url) } }
                        MovieText { visible: root.tab === "watch" && !root.extraLoading && !root.links.length; text: "No viewing options found."; color: MovieStyle.muted }
                        MovieText { visible: root.tab === "spoilers"; Layout.fillWidth: true; text: root.spoiler; wrapMode: Text.Wrap }
                    }
                }
                Collections {
                    objectName: "collectionsView"
                    visible: root.tab === "collections"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    sections: root.collectionSections
                    loading: root.collectionsLoading
                    loaded: root.collectionsLoaded
                    error: root.collectionsError
                    onActivated: title => root.animeMode ? root.openRelated(title) : root.selectTitle(title)
                }
                TorrentSearch {
                    id: torrentPanel
                    showLoading: false
                    service: localService
                    host: root.host
                    objectName: "torrentSearch"
                    visible: root.tab === "torrent"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    title: Object.assign({}, root.selected, root.torrentEpisode)
                    onImported: root.refreshLocalLibrary()
                }
                Subtitles {
                    id: subtitlePanel
                    spaceId: root.spaceId
                    showLoading: false
                    host: root.host
                    objectName: "subtitleBrowser"
                    visible: root.tab === "subtitles" && root.localFiles.length > 0
                    Layout.fillWidth: true; Layout.fillHeight: true
                    files: root.localFiles
                    requestedPath: root.subtitlePath
                }
                ListView {
                    id: castView
                    visible: root.tab === "cast"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    model: visible ? root.cast : []
                    spacing: 8
                    WheelScroll { view: castView }
                    ScrollBar.vertical: MovieScrollBar {}
                    delegate: MovieButton {
                        id: castRow
                        required property var modelData
                        width: castView.width; implicitHeight: Math.max(68,castText.implicitHeight+16)
                        text: modelData.name; enabled: !!modelData.id || !!modelData.url
                        onClicked: modelData.url ? root.openUrl(modelData.url) : root.showPerson(modelData)
                        contentItem: RowLayout {
                            spacing: 12
                            CrossfadeImage { source: castRow.modelData.image || ""; imageWidth: 84; Layout.preferredWidth: 42; Layout.preferredHeight: 60 }
                            ColumnLayout {
                                id: castText; Layout.fillWidth: true
                                MovieText { text: castRow.modelData.name; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                MovieText { text: castRow.modelData.role || ""; color: MovieStyle.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            }
                        }
                    }
                }
                GridView {
                    id: filmography; cacheBuffer: height; objectName: "filmography"
                    activeFocusOnTab: true
                    keyNavigationEnabled: true
                    Keys.onReturnPressed: if (currentItem) root.selectTitle(currentItem.title)
                    Keys.onEnterPressed: if (currentItem) root.selectTitle(currentItem.title)
                    visible: root.tab === "person"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    cellWidth: width / Math.max(1,Math.floor(width/140)); cellHeight: cellWidth*1.5+48
                    model: visible ? root.personCredits.filter(t => root.personRole === "All" || (t.roles || []).includes(root.personRole)).sort((a,b) => Number(b.year || 0)-Number(a.year || 0)) : []
                    WheelScroll { view: filmography; wheelStep: Math.max(360, filmography.cellHeight*1.25) }
                    ScrollBar.vertical: MovieScrollBar {}
                    header: Column {
                        width: filmography.width; spacing: 12; bottomPadding: 16
                        MovieText { width: parent.width; text: root.personDetails.name || ""; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(22); font.bold: true; wrapMode: Text.Wrap }
                        MovieText { width: parent.width; text: root.personDetails.biography || ""; wrapMode: Text.Wrap }
                        Flow {
                            width: parent.width; spacing: 4
                            Repeater { model: root.personRoles; MovieButton { required property string modelData; text: modelData; highlighted: root.personRole === modelData; onClicked: { root.personRole=modelData; filmography.positionViewAtBeginning(); } } }
                        }
                    }
                    delegate: Poster {
                        required property var modelData
                        width: filmography.cellWidth-8; height: filmography.cellHeight-8
                        title: modelData; onClicked: root.selectTitle(modelData)
                    }
                }
                ColumnLayout {
                    visible: root.tab === "episodes"
                    Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                    RowLayout {
                        visible: !root.animeMode
                        Layout.fillWidth: true
                        Layout.fillHeight: false
                        Layout.preferredHeight: visible ? 42 : 0
                        MovieChoice { id: seasonPicker; objectName: "seasonPicker"; enabled: root.seasons.length > 0; Layout.preferredWidth: 160; model: root.seasons.map(s => "Season " + s); onActivated: root.loadEpisodes(false); Accessible.name: "Season" }
                        MovieIconButton { iconName: "file-search-corner"; text: "Find selected season"; enabled: root.seasons.length > 0; onClicked: { root.torrentEpisode = ({season:root.seasons[Math.max(0,seasonPicker.currentIndex)]}); root.tab = "torrent"; } }
                    }
                    ListView {
                        id: episodeView; objectName: "episodeList"
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                        model: root.tab === "episodes" ? episodeCatalogue : null
                        spacing: 8
                        WheelScroll { view: episodeView }
                        ScrollBar.vertical: MovieScrollBar {}
                        delegate: EpisodeRow {
                            required property string payload
                            width: episodeView.width; episode: JSON.parse(payload)
                            findAvailable: true
                            localFile: root.localFiles.find(file => Number(file.season) === Number(episode.season) && Number(file.episode) === Number(episode.number)) || ({})
                            onClicked: root.play(episode, false)
                            onFindRequested: { root.torrentEpisode = ({season:episode.season,episode:episode.number,episodeTitle:episode.title}); root.tab = "torrent"; }
                            onSubtitlesRequested: { root.subtitlePath = localFile.path; root.tab = "subtitles"; }
                            onDeleteRequested: path => root.deleteLocal(path)
                        }
                        footer: Column {
                            width: episodeView.width
                            MovieText { visible: !root.episodeLoading && !root.episodes.length; text: "No episodes available yet."; color: MovieStyle.muted }
                            MovieButton { visible: !!root.episodeNext; text: "More episodes"; enabled: !root.episodeLoading; onClicked: root.loadEpisodes(true) }
                        }
                    }
                }
            }
            ListView {
                id: rail; cacheBuffer: width * 2; objectName: "catalogueRail"; visible: !root.gridMode && !root.scanOpen
                anchors.bottom: parent.bottom; width: parent.width; height: Math.min(250,parent.height*0.36)
                orientation: ListView.Horizontal; spacing: 12; clip: true; model: catalogue
                keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: Poster {
                    required property string payload
                    readonly property var modelData: JSON.parse(payload)
                    required property int index
                    width: (rail.height-42)/1.5; height: rail.height; title: modelData
                    highlighted: root.sameTitle(root.selected, modelData)
                    onClicked: { rail.forceActiveFocus(); rail.currentIndex=index; root.selectTitle(modelData); }
                }
                onCurrentItemChanged: if (!root.updatingCatalogue && !root.keepLinkedSelection() && activeFocus && currentItem && !root.sameTitle(currentItem.title, root.selected)) root.selectTitle(currentItem.title)
                Keys.onPressed: event => root.releaseLinkedSelection(event)
                Keys.onReturnPressed: if (currentItem) root.selectTitle(currentItem.title)
                Keys.onEnterPressed: if (currentItem) root.selectTitle(currentItem.title)
                onContentXChanged: pagination.restart()
                WheelScroll { view: rail; orientation: Qt.Horizontal; verticalToHorizontal: true; wheelStep: 360 }
                ScrollBar.horizontal: MovieScrollBar {}
            }
            MovieText { anchors.centerIn: parent; visible: !root.loading && !root.titles.length && !root.scanOpen; text: root.error ? "" : root.localMode ? "No local titles yet." : root.favorites ? "No saved favorites yet." : "No matching titles."; color: MovieStyle.muted }
        }
        Item { Layout.fillWidth: true; Layout.preferredHeight: 42 }
    }
}
