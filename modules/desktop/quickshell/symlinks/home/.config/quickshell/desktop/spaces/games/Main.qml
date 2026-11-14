pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCore
import Quickshell
import "../../ui"
import "../movies"
import "../movies/Catalogue.js" as Catalogue

Item {
    id: root
    objectName: "gamesBrowser"
    property var host: null
    property bool active: false
    property Item backdropTarget: null
    property Item toolbarTarget: null
    readonly property int toolbarHeight: 46
    readonly property var initialFocus: searchOpen ? search : gridMode ? grid : rail
    readonly property Item catalogueFocus: gridMode ? grid : rail
    readonly property list<Item> navigationTabs: [libraryTab, browseTab, favoritesTab]
    property var titles: []
    property var allTitles: []
    property bool hideNsfw: true
    property var contentQueue: []
    property int contentBusy: 0
    // Known NSFW labels hide a game; so does a label still awaiting its first
    // classification attempt. Unavailable labels stay visible.
    readonly property int contentHidden: hideNsfw ? allTitles.filter(game => game.content?.nsfw === true).length : 0
    readonly property int contentAwaiting: hideNsfw ? allTitles.filter(game => game.content?.awaiting && game.content.nsfw !== true).length : 0
    readonly property int contentUnlabelled: hideNsfw ? allTitles.filter(game => game.content?.supported && game.content.nsfw === null && !game.content.awaiting).length : 0
    readonly property string contentStatus: ["Show games that GOG tags NSFW or Steam rates for adult sexual content.", contentHidden ? contentHidden + " hidden by store labels" : "", contentAwaiting ? contentAwaiting + " hidden until classified" : "", contentUnlabelled ? contentUnlabelled + " without store labels, shown" : ""].filter(Boolean).join("\n")
    property var selected: ({})
    property var availability: ({
            stores: []
        })
    property var compatibility: ({})
    property var artwork: ({})
    property var beatTimes: ({})
    property var catalogState: ({
            configured: false
        })
    property string mode: "library"
    property string libraryFilter: "all"
    property bool gridMode: false
    property bool searchOpen: false
    property bool filtersOpen: false
    property string tab: "overview"
    property var localFiles: []
    property bool loading: false
    property bool initializing: true
    property bool detailLoading: false
    property bool actionBusy: false
    property var installJobs: []
    property bool installsLoading: false
    property string installsError: ""
    property bool installsChanged: false
    property int installGeneration: 0
    readonly property bool installing: installJobs.some(job => job.state === "running")
    property bool setupRequired: false
    property string error: ""
    property string detailError: ""
    property var filters: ({
            genre: "",
            platform: "",
            sort: "-added",
            fromYear: "",
            toYear: ""
        })
    property var genreOptions: []
    property var platformOptions: []
    property int browseGeneration: 0
    property int selectionGeneration: 0
    property int hydrationGeneration: 0
    property int beatGeneration: 0
    property int nextOffset: 0
    property var pendingUninstall: ({})
    property string editingStore: ""
    readonly property bool busy: initializing || loading || detailLoading || service.pendingCount > 0 || (active && (backdrop.loading || logo.loading || (tab === "torrent" && (downloads.searching || downloads.connectionLoading || downloads.reviewLoading))))
    readonly property string backgroundImage: artwork.hero || ((selected.artwork || [])[0] || (selected.screenshots || [])[0] || {}).url || ""
    readonly property string poster: artwork.cover || (selected.cover || {}).url || ""
    readonly property var images: (selected.artwork || []).concat(selected.screenshots || [])
    // A native Linux build takes the badge; the ProtonDB tier stays in the tooltip.
    readonly property string protonDbBadge: compatibility.native ? "native" : compatibility.tier || ""
    readonly property url protonDbArtwork: ["native", "platinum", "gold", "silver", "bronze", "borked"].includes(protonDbBadge) ? Qt.resolvedUrl("badges/protondb-" + protonDbBadge + ".svg") : ""
    readonly property string protonDbTooltip: [compatibility.native ? "Native Linux version on Steam" : "", "ProtonDB · " + (compatibility.label || "Unknown"), compatibility.total ? compatibility.total + " reports" : "", compatibility.warning || ""].filter(Boolean).join("\n")
    // Launchers finish uninstalling after the handoff; recheck a few times.
    property var availabilityRecheckDelays: [3000, 10000, 30000]
    property var availabilityChecks: []
    readonly property string hltbTooltip: ["HowLongToBeat", "Main story: " + durationLabel(beatTimes.main), "Main + extras: " + durationLabel(beatTimes.extras), "Completionist: " + durationLabel(beatTimes.complete), beatTimes.stale ? "Saved times" : "", beatTimes.warning || "", !beatTimes.url ? "Click to enter a HowLongToBeat game link." : ""].filter(Boolean).join("\n")

    function durationLabel(value) {
        return Number(value) > 0 ? Number(value) + " h" : "Unavailable";
    }
    function closeStoreMenus() {
        let dismissed = false;
        for (let index = 0; index < storeButtons.count; ++index) {
            const button = storeButtons.itemAt(index);
            if (button?.popup.visible) {
                button.popup.close();
                dismissed = true;
            }
        }
        return dismissed;
    }

    ListModel {
        id: catalogue
    }
    GameService {
        id: service
        onFailed: message => root.error = message
    }
    TorrentService {
        id: torrents
        spaceId: "games"
        monitorKind: "game"
        monitorJobs: true
        foreground: root.active
        onLibraryChanged: root.loadLocalFiles()
    }
    ArtworkCache {
        id: artCache
        spaceId: "games"
    }
    Settings {
        id: preferences
        location: "file://" + (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/spaces/games/games-ui.ini"
    }
    MovieBackdrop {
        id: backdrop
        objectName: "gamesBackdrop"
        cacheService: artCache
        parent: root.backdropTarget || root
        anchors.fill: parent
        z: root.backdropTarget ? 0 : -1
        visible: root.active
        source: root.active ? root.backgroundImage : ""
        poster: root.poster
        ownerKey: root.selected.id || ""
        gridMode: root.gridMode
    }
    ImageGallery {
        id: gallery
        objectName: "gamesGallery"
        parent: root
        cacheService: artCache
    }

    function dismissTransient() {
        if (downloads.dismissTransient())
            return true;
        if (gallery.visible) {
            gallery.close();
            return true;
        }
        if (uninstall.visible) {
            uninstall.close();
            return true;
        }
        if (matching.visible) {
            matching.close();
            return true;
        }
        if (closeStoreMenus())
            return true;
        for (const picker of [libraryChoice, genre, platform, sort]) {
            if (picker.popup.visible) {
                picker.popup.close();
                return true;
            }
        }
        if (searchOpen) {
            searchOpen = false;
            search.clear();
            return true;
        }
        if (filtersOpen) {
            filtersOpen = false;
            return true;
        }
        return false;
    }
    onActiveChanged: {
        if (!active) {
            gallery.close();
            matching.close();
            uninstall.close();
            closeStoreMenus();
            for (const picker of [libraryChoice, genre, platform, sort])
                picker.popup.close();
            searchDelay.stop();
            detailDelay.stop();
            availabilityCheck.stop();
            availabilityChecks = [];
            contentDelay.stop();
            pagination.stop();
        } else {
            if (installsChanged) {
                installsChanged = false;
                browse(false);
                hydrateSelection(false);
            }
            if (detailLoading)
                detailDelay.restart();
            pollInstalls();
            contentDelay.restart();
            pagination.restart();
            if (search.text)
                searchDelay.restart();
        }
    }
    function openUrl(url) {
        Browser.open(url, "games", "", host);
    }
    function updateCatalogue(items, append) {
        const seen = new Set(append ? allTitles.map(game => game.id) : []);
        const additions = (items || []).filter(game => {
            if (!game.id || seen.has(game.id))
                return false;
            seen.add(game.id);
            return true;
        });
        allTitles = append ? allTitles.concat(additions) : additions;
        applyContentFilter();
    }
    function contentVisible(game) {
        if (!hideNsfw || game.content?.nsfw !== true && !game.content?.awaiting)
            return true;
        // A label still being classified never hides the game being viewed.
        return game.content?.nsfw !== true && game.id === selected.id;
    }
    function queueContent(items, refresh) {
        const queued = new Set(contentQueue.map(entry => entry.id));
        const additions = [];
        for (const game of items || []) {
            if (queued.has(game.id) || !(refresh ? game.content?.supported : game.content?.pending))
                continue;
            queued.add(game.id);
            additions.push({
                id: game.id,
                refresh: !!refresh
            });
        }
        contentQueue = contentQueue.concat(additions);
    }
    function applyContentFilter() {
        const visible = allTitles.filter(game => contentVisible(game));
        titles = Catalogue.update(catalogue, titles, visible, false);
        if (selected.id && !titles.some(game => game.id === selected.id)) {
            gallery.close();
            matching.close();
            uninstall.close();
            clearSelection();
        }
        if (!selected.id && titles.length)
            selectGame(titles[0]);
    }
    function setNsfwIncluded(included) {
        hideNsfw = !included;
        preferences.setValue("catalogue/hideNsfw", hideNsfw);
        // Hiding NSFW also removes a viewed game whose label is still unknown.
        if (hideNsfw && allTitles.find(game => game.id === selected.id)?.content?.awaiting) {
            gallery.close();
            matching.close();
            uninstall.close();
            clearSelection();
        }
        applyContentFilter();
        contentQueue = [];
        queueContent(allTitles, false);
        contentDelay.restart();
        pagination.restart();
    }
    function hydrateContent() {
        if (!active || !hideNsfw || loading)
            return;
        while (contentBusy < 2 && contentQueue.length) {
            // One request classifies a slice of the page; its Steam games share
            // one store read.
            const refresh = contentQueue[0].refresh;
            const batch = [];
            const rest = [];
            for (const entry of contentQueue)
                (entry.refresh === refresh && batch.length < 25 ? batch : rest).push(entry);
            contentQueue = rest;
            const gameIds = batch.map(entry => entry.id);
            const generation = browseGeneration;
            ++contentBusy;
            service.request("content_rating", {
                gameIds: gameIds,
                refresh: refresh
            }, (result, failure) => {
                --contentBusy;
                if (generation === browseGeneration)
                    patchGames(failure ? gameIds.map(gameId => ({
                                id: gameId,
                                content: Object.assign({}, allTitles.find(game => game.id === gameId)?.content, {
                                    pending: false,
                                    awaiting: false
                                })
                            })) : result.items || []);
                contentDelay.restart();
                pagination.restart();
            });
        }
    }
    function patchGame(game) {
        patchGames([game]);
    }
    function patchGames(games) {
        const next = allTitles.slice();
        const indexes = new Map(next.map((item, index) => [item.id, index]));
        const patched = new Map();
        for (const game of games) {
            const index = indexes.get(game?.id);
            if (index === undefined)
                continue;
            next[index] = Object.assign({}, next[index], game);
            patched.set(game.id, next[index]);
        }
        if (!patched.size)
            return;
        allTitles = next;
        // Hydration patches games in place; rebuild the visible catalogue only
        // when a patched game's visibility changes.
        const positions = new Map(titles.map((item, position) => [item.id, position]));
        const visible = titles.slice();
        for (const [id, game] of patched) {
            const position = positions.get(id);
            if ((position !== undefined) !== contentVisible(game)) {
                applyContentFilter();
                return;
            }
            if (position !== undefined)
                visible[position] = game;
        }
        titles = visible;
        for (const [id, game] of patched)
            if (positions.has(id))
                catalogue.setProperty(positions.get(id), "payload", JSON.stringify(game));
    }
    function showMode(value) {
        mode = value;
        filtersOpen = false;
        tab = "overview";
        browse(false);
    }
    function browse(append, refresh) {
        if (append && (loading || !nextOffset))
            return;
        const generation = append ? browseGeneration : ++browseGeneration;
        const offset = append ? nextOffset : 0;
        loading = true;
        error = "";
        if (!append) {
            nextOffset = 0;
            contentQueue = [];
        }
        service.request(mode === "library" ? "library_games" : "browse", {
            query: search.text,
            offset: offset,
            favorites: mode === "favorites",
            mode: libraryFilter,
            filters: filters,
            refresh: !!refresh
        }, (result, failure) => {
            if (generation !== browseGeneration)
                return;
            loading = false;
            if (failure) {
                error = failure;
                return;
            }
            setupRequired = !!result.setupRequired;
            if (result.catalog)
                catalogState = result.catalog;
            // Saved catalogue results shown offline or without credentials are
            // flagged inline, as in Movies and Books. Store problems already show
            // on each store's status and setup has its own empty state.
            if (mode !== "library" && !setupRequired && result.warning)
                error = result.warning;
            updateCatalogue(result.items || [], append);
            queueContent(result.items, refresh);
            contentDelay.restart();
            nextOffset = Number(result.next || 0);
            if (!append) {
                // A refreshed listing keeps the selected game in view.
                const position = titles.findIndex(item => item.id === selected.id);
                if (position >= 0) {
                    selected = Object.assign({}, selected, titles[position]);
                    rail.positionViewAtIndex(position, ListView.Contain);
                    grid.positionViewAtIndex(position, GridView.Contain);
                } else {
                    rail.positionViewAtBeginning();
                    grid.positionViewAtBeginning();
                    if (titles.length)
                        selectGame(titles[0]);
                    else
                        clearSelection();
                }
            }
            pagination.restart();
        });
    }
    function clearSelection() {
        closeStoreMenus();
        availabilityCheck.stop();
        availabilityChecks = [];
        ++selectionGeneration;
        ++beatGeneration;
        detailDelay.stop();
        selected = ({});
        artwork = ({});
        beatTimes = ({});
        availability = ({
                stores: []
            });
        compatibility = ({});
        localFiles = [];
        detailLoading = false;
        detailError = "";
    }
    function selectGame(game) {
        if (!game?.id || game.id === selected.id)
            return;
        clearSelection();
        selected = game;
        detailLoading = true;
        gallery.close();
        matching.close();
        uninstall.close();
        tab = "overview";
        detailDelay.restart();
    }
    function handleOpen(payload) {
        externalOpen.submit(payload);
    }
    SpaceOpenRequest {
        id: externalOpen
        active: root.active
        ready: !root.initializing && !root.actionBusy
        onDelivered: payload => {
            if (!payload?.item?.id)
                return;
            ++root.browseGeneration;
            root.loading = false;
            root.selectGame(payload.item);
            if (payload.play) {
                const id = payload.item.id;
                service.request("availability", {
                    gameId: id
                }, (result, failure) => {
                    if (!root.active || root.selected.id !== id)
                        return;
                    if (failure) {
                        root.detailError = failure;
                        return;
                    }
                    const action = (result.stores || []).reduce((actions, store) => actions.concat(store.actions || []), []).find(action => action.type === "play");
                    if (action)
                        root.execute(action);
                    else
                        root.detailError = "This game is no longer installed. Choose a store to continue.";
                });
            }
        }
    }
    function hydrateSelection(refresh) {
        if (!active || !selected.id)
            return;
        loadLocalFiles();
        // Refresh, install completion and match edits can re-hydrate the same
        // game; only the newest hydration may apply its responses.
        const selection = selectionGeneration;
        const hydration = ++hydrationGeneration;
        const current = () => selection === selectionGeneration && hydration === hydrationGeneration;
        const args = {
            gameId: selected.id,
            refresh: !!refresh
        };
        service.request("details", args, (result, failure) => {
            if (!current())
                return;
            detailLoading = false;
            if (failure) {
                detailError = failure;
                return;
            }
            selected = Object.assign({}, selected, result.game || {});
            patchGame(selected);
            detailError = result.warning || "";
        });
        for (const op of ["availability", "protondb", "presentation"]) {
            service.request(op, args, (result, failure) => {
                if (!current())
                    return;
                if (failure) {
                    detailError = failure;
                    return;
                }
                if (op === "availability")
                    availability = result;
                else if (op === "protondb")
                    compatibility = result;
                else
                    artwork = result;
            });
        }
        loadBeatTimes(refresh);
    }
    function loadLocalFiles() {
        if (!selected.id)
            return;
        const generation = selectionGeneration;
        service.request("local_files", {
            title: Object.assign({}, selected, {
                kind: "game"
            })
        }, (result, failure) => {
            if (generation === selectionGeneration && !failure)
                localFiles = result || [];
        });
    }
    function loadBeatTimes(refresh) {
        const generation = ++beatGeneration;
        const selectedGeneration = selectionGeneration;
        service.request("howlongtobeat", {
            gameId: selected.id,
            refresh: !!refresh
        }, (result, failure) => {
            if (generation !== beatGeneration || selectedGeneration !== selectionGeneration)
                return;
            beatTimes = failure ? {
                warning: failure
            } : result;
        });
    }
    function maybeLoadMore() {
        if (!active || loading || !nextOffset || (hideNsfw && (contentBusy || contentQueue.length)))
            return;
        const nearEnd = gridMode ? grid.contentY + grid.height >= grid.contentHeight - grid.cellHeight * 2 : rail.contentX + rail.width >= rail.contentWidth - rail.width / 2;
        if (nearEnd)
            browse(true);
    }
    function favorite() {
        const gameId = selected.id;
        service.request("set_favorite", {
            gameId: gameId,
            favorite: !selected.favorite
        }, (result, failure) => {
            if (failure) {
                detailError = failure;
                return;
            }
            patchGame({
                id: gameId,
                favorite: result.favorite
            });
            if (selected.id === gameId)
                selected = Object.assign({}, selected, {
                    favorite: result.favorite
                });
            if (mode === "favorites")
                browse(false);
        });
    }
    function refreshLibraries() {
        if (actionBusy)
            return;
        actionBusy = true;
        service.request("refresh_libraries", {}, (result, failure) => {
            actionBusy = false;
            if (failure) {
                error = failure;
                return;
            }
            catalogState = result.catalog;
            browse(false, true);
            hydrateSelection(true);
        });
    }
    function execute(action) {
        if (action.type === "buy") {
            openUrl(action.url);
            return;
        }
        if (actionBusy)
            return;
        const gameId = selected.id;
        actionBusy = true;
        detailError = "";
        service.request("action", {
            gameId: gameId,
            actionId: action.id
        }, (result, failure) => {
            actionBusy = false;
            if (failure) {
                detailError = failure;
                return;
            }
            if (result.job) {
                ++installGeneration;
                installJobs = [result.job].concat(installJobs.filter(job => job.id !== result.job.id));
                pollInstalls();
            }
            if (action.type === "play" || result.handoff)
                host?.hide();
            else if (action.type === "uninstall") {
                availabilityChecks = availabilityRecheckDelays.slice();
                nextAvailabilityCheck();
            }
        });
    }
    function nextAvailabilityCheck() {
        const delays = availabilityChecks.slice();
        const delay = delays.shift();
        availabilityChecks = delays;
        if (delay === undefined)
            return;
        availabilityCheck.interval = delay;
        availabilityCheck.restart();
    }
    function recheckAvailability() {
        if (!active || !selected.id) {
            availabilityChecks = [];
            return;
        }
        const selection = selectionGeneration;
        const hydration = hydrationGeneration;
        const installed = stores => JSON.stringify((stores || []).map(store => [store.store, !!store.installed]));
        const before = installed(availability.stores);
        service.request("availability", {
            gameId: selected.id,
            refresh: true
        }, (result, failure) => {
            if (selection !== selectionGeneration || hydration !== hydrationGeneration)
                return;
            if (failure) {
                nextAvailabilityCheck();
                return;
            }
            availability = result;
            if (installed(result.stores) === before) {
                nextAvailabilityCheck();
                return;
            }
            availabilityChecks = [];
            browse(false);
        });
    }
    function installLabel(job) {
        const percent = job.progress !== null && job.progress !== undefined ? " · " + Math.floor(job.progress * 100) + "%" : "";
        return (job.detail || "Installing") + percent + (job.speed !== undefined ? " · " + job.speed.toFixed(1) + " MiB/s" : "") + (job.eta ? " · ETA " + job.eta : "");
    }
    function pollInstalls() {
        if (installsLoading)
            return;
        const generation = installGeneration;
        installsLoading = true;
        service.request("install_jobs", {}, (result, failure) => {
            installsLoading = false;
            if (generation !== installGeneration) {
                pollInstalls();
                return;
            }
            installsError = failure || "";
            if (failure)
                return;
            const finished = (result || []).some(job => job.state !== "running" && installJobs.some(previous => previous.id === job.id && previous.state === "running"));
            installJobs = result || [];
            if (finished) {
                service.request("refresh_libraries", {}, (state, refreshFailure) => {
                    if (refreshFailure) {
                        installsError = refreshFailure;
                        return;
                    }
                    catalogState = state.catalog;
                    if (active) {
                        browse(false);
                        hydrateSelection(false);
                    } else
                        installsChanged = true;
                });
            }
        });
    }
    function editMatch(store, value) {
        editingStore = store;
        matchInput.text = value || "";
        matching.open();
    }
    function saveMatch() {
        const gameId = selected.id;
        const store = editingStore;
        matchFailure.text = "";
        matchSave.enabled = false;
        service.request(store === "hltb" ? "set_hltb_match" : "set_match", {
            gameId: gameId,
            store: store,
            externalId: matchInput.text.trim()
        }, (result, failure) => {
            matchSave.enabled = true;
            if (selected.id !== gameId || editingStore !== store)
                return;
            if (failure) {
                matchFailure.text = failure;
                return;
            }
            matching.close();
            if (store === "hltb")
                loadBeatTimes(true);
            else {
                // Keep the edited game selected; its identity survives a new match.
                browse(false);
                hydrateSelection(false);
            }
        });
    }
    function loadFilters() {
        if (genreOptions.length)
            return;
        service.request("catalog_filters", {}, (result, failure) => {
            if (failure) {
                error = failure;
                return;
            }
            genreOptions = result.genres || [];
            platformOptions = result.platforms || [];
        });
    }
    Component.onCompleted: {
        // INI storage returns "true"/"false" strings once read from disk.
        gridMode = String(preferences.value("catalogue/grid", false)) === "true";
        hideNsfw = String(preferences.value("catalogue/hideNsfw", true)) === "true";
        pollInstalls();
        service.request("init", {}, (result, failure) => {
            initializing = false;
            if (failure) {
                error = failure;
                return;
            }
            catalogState = result.catalog;
            browse(false);
        });
    }
    // Opening, showing and starting an install read snapshots once; only a
    // running install needs polling.
    Timer {
        interval: 1500
        repeat: true
        running: root.installing && !service.stopped
        onTriggered: root.pollInstalls()
    }
    Timer {
        id: availabilityCheck
        onTriggered: root.recheckAvailability()
    }
    Timer {
        id: detailDelay
        interval: 90
        onTriggered: root.hydrateSelection(false)
    }
    Timer {
        id: searchDelay
        interval: 350
        onTriggered: if (root.active)
            root.browse(false)
    }
    Timer {
        id: contentDelay
        interval: 20
        onTriggered: root.hydrateContent()
    }
    Timer {
        id: pagination
        interval: 110
        onTriggered: root.maybeLoadMore()
    }

    RowLayout {
        id: toolbar
        objectName: "gamesToolbar"
        parent: root.toolbarTarget || root
        width: parent.width
        height: root.toolbarHeight
        visible: root.active
        spacing: 8
        MovieTab {
            id: libraryTab
            objectName: "libraryTab"
            text: "My Library"
            iconName: "gamepad-2"
            highlighted: root.mode === "library"
            onClicked: root.showMode("library")
        }
        MovieTab {
            id: browseTab
            objectName: "discoverTab"
            text: "Browse"
            iconName: "globe"
            highlighted: root.mode === "discover"
            onClicked: root.showMode("discover")
        }
        MovieTab {
            id: favoritesTab
            objectName: "favoritesTab"
            text: "Favorites"
            iconName: "star"
            highlighted: root.mode === "favorites"
            onClicked: root.showMode("favorites")
        }
        Item {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 0
        }
        Flickable {
            id: inlineFilters
            objectName: "gameInlineFilters"
            visible: root.filtersOpen
            Layout.fillWidth: true
            Layout.preferredWidth: filterFields.implicitWidth
            Layout.minimumWidth: Math.min(120, filterFields.implicitWidth)
            Layout.maximumWidth: filterFields.implicitWidth
            Layout.preferredHeight: 46
            clip: true
            contentWidth: filterFields.implicitWidth
            contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            WheelScroll {
                view: inlineFilters
                orientation: Qt.Horizontal
                verticalToHorizontal: true
            }
            ScrollBar.horizontal: MovieScrollBar {}
            Row {
                id: filterFields
                spacing: 8
                MovieChoice {
                    id: libraryChoice
                    visible: root.mode === "library"
                    model: ["All games", "Installed", "Owned"]
                    Accessible.name: "Library filter"
                    onActivated: {
                        root.libraryFilter = ["all", "installed", "owned"][currentIndex];
                        root.browse(false);
                    }
                }
                MovieButton {
                    id: nsfwFilter
                    objectName: "gameContentFilter"
                    text: "NSFW"
                    iconName: root.hideNsfw ? "eye-off" : "eye"
                    highlighted: !root.hideNsfw
                    Accessible.name: "Include NSFW games"
                    Accessible.description: root.contentStatus
                    Accessible.checkable: true
                    Accessible.checked: !root.hideNsfw
                    onClicked: root.setNsfwIncluded(root.hideNsfw)
                    PassiveToolTip {
                        objectName: "gameContentStatus"
                        target: nsfwFilter
                        text: root.contentStatus
                        maximumLineCount: 6
                    }
                }
                Row {
                    visible: root.mode === "discover" && root.catalogState.configured
                    spacing: 8
                    MovieChoice {
                        id: genre
                        objectName: "genrePicker"
                        width: 180
                        model: [
                            {
                                id: "",
                                name: "All genres"
                            }
                        ].concat(root.genreOptions)
                        textRole: "name"
                        Accessible.name: "Genre"
                    }
                    MovieChoice {
                        id: platform
                        width: 180
                        model: [
                            {
                                id: "",
                                name: "All platforms"
                            }
                        ].concat(root.platformOptions)
                        textRole: "name"
                        Accessible.name: "Platform"
                    }
                    MovieChoice {
                        id: sort
                        width: 165
                        model: ["Popular", "Highest rating", "Newest release", "Recently updated", "Title"]
                        Accessible.name: "Sort"
                    }
                    MovieInput {
                        id: fromYear
                        width: 90
                        placeholderText: "From year"
                        Accessible.name: "From year"
                        validator: IntValidator {
                            bottom: 1970
                            top: 2200
                        }
                    }
                    MovieInput {
                        id: toYear
                        width: 90
                        placeholderText: "To year"
                        Accessible.name: "To year"
                        validator: IntValidator {
                            bottom: 1970
                            top: 2200
                        }
                    }
                    MovieButton {
                        objectName: "applyGameFilters"
                        text: "Apply"
                        onClicked: {
                            root.filters = {
                                genre: genre.model[genre.currentIndex].id,
                                platform: platform.model[platform.currentIndex].id,
                                sort: ["-added", "-rating", "-released", "-updated", "name"][sort.currentIndex],
                                fromYear: fromYear.text,
                                toYear: toYear.text
                            };
                            root.browse(false);
                        }
                    }
                    MovieButton {
                        objectName: "resetGameFilters"
                        text: "Reset"
                        onClicked: {
                            genre.currentIndex = 0;
                            platform.currentIndex = 0;
                            sort.currentIndex = 0;
                            fromYear.clear();
                            toYear.clear();
                            root.filters = {
                                genre: "",
                                platform: "",
                                sort: "-added",
                                fromYear: "",
                                toYear: ""
                            };
                            root.browse(false);
                        }
                    }
                }
            }
        }
        MovieInput {
            id: search
            objectName: "gamesSearch"
            visible: root.searchOpen
            Layout.preferredWidth: Math.max(120, Math.min(260, root.width / 5))
            placeholderText: "Search games"
            Accessible.name: "Search games"
            onTextChanged: searchDelay.restart()
        }
        ActivityIndicator {
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            active: root.active && !gallery.visible
            spinnerName: "gamesLoading"
            jobs: root.installJobs.concat(downloads.jobs)
            tasks: [task(root.initializing, "init", "Opening Games…"), task(root.loading, "browse", "Loading games…"), task(root.detailLoading, "details", "Loading game details…"), task(root.actionBusy, "action", "Updating game library…"), task(service.pendingCount > (root.installsLoading ? 1 : 0) && !root.initializing && !root.loading && !root.detailLoading && !root.actionBusy, "information", "Loading game information…"), task(backdrop.loading || logo.loading, "artwork", "Loading artwork…"), task(root.tab === "torrent" && (downloads.searching || downloads.connectionLoading || downloads.reviewLoading), "find", "Loading downloads…")]
        }
        MovieIconButton {
            iconName: "search"
            text: "Search games"
            highlighted: root.searchOpen
            onClicked: {
                root.searchOpen = !root.searchOpen;
                if (root.searchOpen)
                    search.forceActiveFocus();
                else
                    search.clear();
            }
        }
        MovieIconButton {
            objectName: "gameFiltersButton"
            iconName: "sliders-horizontal"
            text: "Filters"
            highlighted: root.filtersOpen
            onClicked: {
                root.filtersOpen = !root.filtersOpen;
                if (root.filtersOpen && root.mode === "discover" && root.catalogState.configured)
                    root.loadFilters();
            }
        }
        MovieIconButton {
            iconName: "refresh-cw"
            text: "Refresh libraries and game information"
            enabled: !root.actionBusy
            onClicked: root.refreshLibraries()
        }
        MovieIconButton {
            objectName: "gameDownloads"
            iconName: "download"
            text: "Downloads"
            onClicked: downloads.showJobPanel()
        }
        MovieIconButton {
            objectName: "catalogueLayoutToggle"
            iconName: root.gridMode ? "panels-top-left" : "layout-grid"
            text: root.gridMode ? "Show poster rail" : "Show grid"
            onClicked: {
                root.gridMode = !root.gridMode;
                preferences.setValue("catalogue/grid", root.gridMode);
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: root.toolbarTarget ? 0 : root.toolbarHeight + 12
        spacing: 14
        MovieText {
            Layout.fillWidth: true
            visible: !!root.error
            text: root.error
            color: MovieStyle.danger
            wrapMode: Text.Wrap
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 30
            GridView {
                id: grid
                objectName: "gamesGrid"
                visible: root.gridMode && root.titles.length > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: root.width * 0.48
                clip: true
                cellWidth: Math.max(140, width / Math.max(1, Math.floor(width / 180)))
                cellHeight: cellWidth * 1.65
                model: catalogue
                cacheBuffer: height
                currentIndex: root.titles.findIndex(game => game.id === root.selected.id)
                onCurrentIndexChanged: if (activeFocus && currentIndex >= 0)
                    root.selectGame(root.titles[currentIndex])
                onContentYChanged: pagination.restart()
                ScrollBar.vertical: MovieScrollBar {}
                WheelScroll {
                    view: grid
                }
                delegate: ArtworkCard {
                    required property string payload
                    readonly property var game: JSON.parse(payload)
                    width: grid.cellWidth - 8
                    height: grid.cellHeight - 10
                    text: game.title || ""
                    imageSource: (game.cover || {}).url || ""
                    cacheService: artCache
                    fallbackIcon: "gamepad-2"
                    favorite: !!game.favorite
                    badge: (game.installedBy || []).length ? "Installed" : ""
                    highlighted: game.id === root.selected.id
                    onClicked: root.selectGame(game)
                }
            }
            ColumnLayout {
                id: detailPane
                objectName: "gameDetailPane"
                visible: !!root.selected.id
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: root.gridMode ? root.width * 0.48 : root.width
                spacing: 8
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(72, Math.min(145, root.height * 0.17))
                    CrossfadeImage {
                        id: logo
                        objectName: "gameTitleArtwork"
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.min(parent.width, 500)
                        height: parent.height
                        source: root.active ? root.artwork.logo || "" : ""
                        cacheService: artCache
                        imageWidth: 1000
                        resetOnSourceChange: true
                        fillMode: Image.PreserveAspectFit
                        horizontalAlignment: Image.AlignLeft
                        Accessible.name: root.selected.title || ""
                    }
                    MovieText {
                        anchors.fill: parent
                        visible: !logo.hasImage
                        text: root.selected.title || ""
                        font.pixelSize: 40
                        font.bold: true
                        verticalAlignment: Text.AlignVCenter
                        wrapMode: Text.Wrap
                        maximumLineCount: 3
                    }
                }
                MovieText {
                    Layout.fillWidth: true
                    color: MovieStyle.muted
                    wrapMode: Text.Wrap
                    text: [root.selected.releaseDate || "", (root.selected.genres || []).join(" · ")].filter(Boolean).join("   ·   ")
                }
                Flow {
                    objectName: "gameFacts"
                    Layout.fillWidth: true
                    spacing: 12
                    Row {
                        id: igdbRating
                        objectName: "igdbRating"
                        visible: root.selected.rating !== undefined && root.selected.rating !== null
                        spacing: 6
                        height: 38
                        Accessible.role: Accessible.StaticText
                        Accessible.name: "IGDB · " + Number(root.selected.rating || 0).toFixed(1) + " / 5"
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 34
                            height: 34
                            radius: 6
                            color: "#9147ff"
                            Image {
                                objectName: "igdbArtwork"
                                anchors.fill: parent
                                anchors.margins: 3
                                source: Qt.resolvedUrl("badges/igdb.svg")
                                sourceSize.width: 68
                                fillMode: Image.PreserveAspectFit
                            }
                        }
                        MovieText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: Number(root.selected.rating || 0).toFixed(1)
                            font.bold: true
                            font.pixelSize: MovieStyle.fontSize + 2
                        }
                        PassiveToolTip {
                            target: igdbRating
                            text: igdbRating.Accessible.name + (root.selected.ratingCount ? "\n" + root.selected.ratingCount + " ratings" : "")
                        }
                    }
                    MovieButton {
                        id: protonBadge
                        objectName: "protonDbButton"
                        visible: !!root.compatibility.url
                        implicitWidth: root.protonDbArtwork.toString() ? 42 : 96
                        implicitHeight: 38
                        padding: 2
                        text: (root.compatibility.native ? "Native Linux · " : "") + "ProtonDB · " + (root.compatibility.label || "Unknown")
                        Accessible.name: text
                        Accessible.description: root.protonDbTooltip
                        contentItem: Item {
                            Image {
                                objectName: "protonDbArtwork"
                                anchors.centerIn: parent
                                width: 34
                                height: 34
                                source: root.protonDbArtwork
                                sourceSize.width: 68
                                fillMode: Image.PreserveAspectFit
                            }
                            MovieText {
                                anchors.centerIn: parent
                                visible: !root.protonDbArtwork.toString()
                                text: "ProtonDB"
                                font.pixelSize: 12
                            }
                        }
                        onClicked: root.openUrl(root.compatibility.url)
                        PassiveToolTip {
                            target: protonBadge
                            text: root.protonDbTooltip
                        }
                    }
                    MovieButton {
                        id: beatButton
                        objectName: "hltbButton"
                        text: Number(root.beatTimes.main) > 0 ? root.durationLabel(root.beatTimes.main) : "—"
                        iconName: "clock"
                        padding: 4
                        Accessible.name: "HowLongToBeat · Main story: " + root.durationLabel(root.beatTimes.main)
                        Accessible.description: root.hltbTooltip
                        onClicked: root.beatTimes.url ? root.openUrl(root.beatTimes.url) : root.editMatch("hltb", root.beatTimes.override || "")
                        PassiveToolTip {
                            objectName: "hltbTooltip"
                            target: beatButton
                            text: root.hltbTooltip
                            maximumLineCount: 12
                        }
                    }
                    MovieIconButton {
                        objectName: "gameWebsiteButton"
                        text: "Open official website"
                        iconName: "link"
                        visible: !!root.selected.officialWebsite
                        onClicked: root.openUrl(root.selected.officialWebsite)
                    }
                }
                Flow {
                    objectName: "gameStoreButtons"
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        id: storeButtons
                        model: root.availability.stores || []
                        GameStoreButton {
                            required property var modelData
                            width: Math.min(220, Math.max(140, (detailPane.width - 160) / Math.max(1, storeButtons.count)))
                            height: MovieStyle.controlHeight
                            store: modelData
                            busy: root.actionBusy
                            installJob: modelData.store === "epic" ? root.installJobs.find(job => job.externalId === modelData.externalId) || ({}) : ({})
                            onActionRequested: action => root.execute(action)
                            onMatchRequested: (store, externalId) => root.editMatch(store, externalId)
                            onUrlRequested: url => root.openUrl(url)
                            onUninstallRequested: action => {
                                root.pendingUninstall = action;
                                uninstall.open();
                            }
                        }
                    }
                    MovieIconButton {
                        objectName: "gameFavorite"
                        text: root.selected.favorite ? "Remove favorite" : "Add favorite"
                        iconName: root.selected.favorite ? "star-filled" : "star"
                        highlighted: !!root.selected.favorite
                        onClicked: root.favorite()
                    }
                    MovieIconButton {
                        objectName: "gameRefresh"
                        text: "Refresh game"
                        iconName: "refresh-cw"
                        enabled: !root.detailLoading
                        onClicked: root.hydrateSelection(true)
                    }
                    MovieIconButton {
                        text: "Open local game files"
                        iconName: "folder-open"
                        visible: root.localFiles.length > 0
                        onClicked: {
                            Apps.launch(["xdg-open", "file://" + encodeURI(String(root.localFiles[0].path).replace(/\/[^/]+$/, ""))]);
                            root.host?.hide();
                        }
                    }
                }
                MovieText {
                    objectName: "gameInstallStatus"
                    Layout.fillWidth: true
                    readonly property var job: root.installJobs.find(job => job.gameId === root.selected.id) || ({})
                    visible: !!job.id || !!root.installsError
                    text: root.installsError || (job.id ? "Epic · " + root.installLabel(job) : "")
                    color: root.installsError || job.state === "failed" ? MovieStyle.danger : MovieStyle.muted
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    MovieTab {
                        objectName: "gameOverviewTab"
                        text: "Overview"
                        highlighted: root.tab === "overview"
                        onClicked: root.tab = "overview"
                    }
                    MovieTab {
                        objectName: "gameFindTab"
                        text: "Find"
                        highlighted: root.tab === "torrent"
                        onClicked: root.tab = "torrent"
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                }
                MovieText {
                    Layout.fillWidth: true
                    visible: !!root.detailError
                    text: root.detailError
                    color: MovieStyle.danger
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                ScrollArea {
                    id: details
                    objectName: "gameOverview"
                    visible: root.tab === "overview"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: availableWidth
                    clip: true
                    ColumnLayout {
                        objectName: "gameOverviewContent"
                        width: details.availableWidth
                        spacing: 12
                        MovieText {
                            Layout.fillWidth: true
                            text: root.selected.summary || "No description is available for this game."
                            wrapMode: Text.Wrap
                            font.pixelSize: 17
                        }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 16
                            visible: root.artwork.playHours !== undefined || !!root.artwork.lastPlayed
                            MovieText {
                                visible: root.artwork.playHours !== undefined
                                text: (root.artwork.playHours || 0) + " h played"
                                color: MovieStyle.muted
                            }
                            MovieText {
                                visible: !!root.artwork.lastPlayed
                                text: "Last played " + (root.artwork.lastPlayed || "")
                                color: MovieStyle.muted
                            }
                        }
                        MovieText {
                            Layout.fillWidth: true
                            visible: (root.selected.developers || []).length > 0
                            text: "Developer  " + (root.selected.developers || []).join(", ")
                            color: MovieStyle.muted
                            wrapMode: Text.Wrap
                        }
                        MovieText {
                            Layout.fillWidth: true
                            visible: (root.selected.platforms || []).length > 0
                            text: (root.selected.platforms || []).join(" · ")
                            color: MovieStyle.muted
                            wrapMode: Text.Wrap
                        }
                        MovieText {
                            Layout.fillWidth: true
                            visible: (root.selected.relationships || []).length > 0
                            text: (root.selected.relationships || []).map(item => item.type + ": " + item.title).join(" · ")
                            color: MovieStyle.muted
                            wrapMode: Text.Wrap
                        }
                        ImageStrip {
                            objectName: "gameImageStrip"
                            Layout.fillWidth: true
                            Layout.preferredHeight: 116
                            visible: root.images.length > 0
                            images: root.images
                            cacheService: artCache
                            onActivated: index => gallery.show(images, index, root.selected.title)
                        }
                    }
                }
                TorrentSearch {
                    id: downloads
                    showStatus: false
                    objectName: "gameFindContent"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: root.active && root.tab === "torrent"
                    service: torrents
                    extraJobs: root.installJobs.map(job => Object.assign({}, job, {
                            detail: root.installLabel(job)
                        }))
                    host: root.host
                    showLoading: false
                    title: Object.assign({}, root.selected, {
                        kind: "game",
                        year: (root.selected.releaseDate || "").slice(0, 4)
                    })
                    onImported: root.loadLocalFiles()
                }
            }
            ColumnLayout {
                visible: !root.selected.id && !root.loading && !root.initializing
                Layout.fillWidth: true
                Layout.fillHeight: true
                Item {
                    Layout.fillHeight: true
                }
                MovieText {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: root.setupRequired ? "Set up game discovery" : root.hideNsfw && root.allTitles.length ? "No games visible" : "No games found"
                    font.pixelSize: 28
                    font.bold: true
                }
                MovieText {
                    Layout.fillWidth: true
                    Layout.maximumWidth: 750
                    Layout.alignment: Qt.AlignHCenter
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: MovieStyle.muted
                    text: root.setupRequired ? root.catalogState.configError ? root.catalogState.configError + " My library still works." : "Add igdb_client_id and igdb_client_secret to " + (root.catalogState.configPath || "games.json") + ". My library works without catalogue credentials." : root.hideNsfw && root.allTitles.length ? "Games labelled NSFW, or still being classified, are hidden. Enable NSFW in Filters to show them." : root.mode === "library" ? "Install a Steam game, sign in with legendary auth for Epic, or sign into GOG in Heroic, then refresh your libraries." : root.mode === "favorites" ? "Save games with the Favorite button." : "Try another search or change the filters."
                }
                MovieButton {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Refresh"
                    iconName: "refresh-cw"
                    onClicked: root.refreshLibraries()
                }
                Item {
                    Layout.fillHeight: true
                }
            }
        }
        ListView {
            id: rail
            objectName: "gamesRail"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(300, root.height * 0.34)
            visible: !root.gridMode && root.titles.length > 0
            orientation: ListView.Horizontal
            spacing: 12
            clip: true
            cacheBuffer: width
            model: catalogue
            currentIndex: root.titles.findIndex(game => game.id === root.selected.id)
            onCurrentIndexChanged: if (activeFocus && currentIndex >= 0)
                root.selectGame(root.titles[currentIndex])
            onContentXChanged: pagination.restart()
            ScrollBar.horizontal: MovieScrollBar {}
            WheelScroll {
                view: rail
                orientation: Qt.Horizontal
                verticalToHorizontal: true
            }
            delegate: ArtworkCard {
                required property string payload
                readonly property var game: JSON.parse(payload)
                width: (rail.height - 50) * 0.67
                height: rail.height - 10
                text: game.title || ""
                imageSource: (game.cover || {}).url || ""
                cacheService: artCache
                fallbackIcon: "gamepad-2"
                favorite: !!game.favorite
                badge: (game.installedBy || []).length ? "Installed" : ""
                highlighted: game.id === root.selected.id
                onClicked: root.selectGame(game)
            }
        }
    }
    Popup {
        id: matching
        objectName: "gameMatchDialog"
        parent: root
        x: Math.max(0, (root.width - width) / 2)
        y: Math.max(0, (root.height - height) / 2)
        width: Math.min(550, root.width - 24)
        padding: 20
        focus: true
        modal: false
        onOpened: {
            matchFailure.text = "";
            matchInput.forceActiveFocus();
        }
        background: Rectangle {
            color: MovieStyle.surface
            radius: MovieStyle.radius
            border.color: MovieStyle.border
        }
        contentItem: ColumnLayout {
            spacing: 15
            MovieText {
                text: root.editingStore === "hltb" ? "HowLongToBeat match" : root.editingStore === "steam" ? "Steam match" : root.editingStore === "gog" ? "GOG match" : "Epic match"
                font.bold: true
                font.pixelSize: 22
            }
            MovieText {
                Layout.fillWidth: true
                text: root.editingStore === "hltb" ? "Paste a game link or ID. Leave blank to use automatic matching." : root.editingStore === "gog" ? "Enter the numeric GOG product ID from Heroic. Leave blank to clear the match." : "Enter the Steam AppID or Legendary app name. Leave blank to clear the match."
                wrapMode: Text.Wrap
                color: MovieStyle.muted
            }
            MovieInput {
                id: matchInput
                objectName: "gameMatchInput"
                Layout.fillWidth: true
                Accessible.name: "Game link or ID"
                onAccepted: if (matchSave.enabled)
                    root.saveMatch()
            }
            MovieText {
                id: matchFailure
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: MovieStyle.danger
                visible: !!text
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                MovieButton {
                    text: "Cancel"
                    onClicked: matching.close()
                }
                MovieButton {
                    id: matchSave
                    objectName: "gameMatchSave"
                    text: "Save"
                    highlighted: true
                    onClicked: root.saveMatch()
                }
            }
        }
    }
    Popup {
        id: uninstall
        objectName: "gameUninstallConfirmation"
        parent: root
        x: Math.max(0, (root.width - width) / 2)
        y: Math.max(0, (root.height - height) / 2)
        width: Math.min(480, root.width - 24)
        padding: 20
        focus: true
        modal: false
        background: Rectangle {
            color: MovieStyle.surface
            radius: MovieStyle.radius
            border.color: MovieStyle.border
        }
        contentItem: ColumnLayout {
            spacing: 15
            MovieText {
                text: "Uninstall " + (root.selected.title || "game") + "?"
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                font.pixelSize: 22
                font.bold: true
            }
            MovieText {
                text: "The launcher will remove the installed game files."
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                color: MovieStyle.muted
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                MovieButton {
                    text: "Cancel"
                    onClicked: uninstall.close()
                }
                MovieButton {
                    text: "Uninstall"
                    highlighted: true
                    onClicked: {
                        uninstall.close();
                        root.execute(root.pendingUninstall);
                    }
                }
            }
        }
    }
}
