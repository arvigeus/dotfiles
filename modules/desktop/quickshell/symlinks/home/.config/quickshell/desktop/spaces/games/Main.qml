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
    property var titles: []
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
    property bool setupRequired: false
    property string error: ""
    property string detailError: ""
    property string notice: ""
    property var filters: ({
            genre: "",
            platform: "",
            sort: "-added",
            fromYear: "",
            toYear: ""
        })
    property var genreOptions: []
    property var platformOptions: []
    property var metadataQueue: []
    property bool metadataBusy: false
    property int browseGeneration: 0
    property int selectionGeneration: 0
    property int beatGeneration: 0
    property int nextOffset: 0
    property var pendingUninstall: ({})
    property string editingStore: ""
    readonly property bool busy: initializing || loading || detailLoading || service.pendingCount > 0 || (active && (backdrop.loading || logo.loading || (tab === "torrent" && (downloads.searching || downloads.connectionLoading || downloads.inspectLoading || downloads.reviewLoading))))
    readonly property string backgroundImage: artwork.hero || ((selected.artwork || [])[0] || (selected.screenshots || [])[0] || {}).url || ""
    readonly property string poster: artwork.cover || (selected.cover || {}).url || ""
    readonly property var images: (selected.artwork || []).concat(selected.screenshots || [])
    readonly property url protonDbArtwork: ["native", "platinum", "gold", "silver", "bronze", "borked"].includes(compatibility.tier) ? Qt.resolvedUrl("badges/protondb-" + compatibility.tier + ".svg") : ""
    readonly property string protonDbTooltip: ["ProtonDB · " + (compatibility.label || "Unknown"), compatibility.total ? compatibility.total + " reports" : "", compatibility.warning || ""].filter(Boolean).join("\n")
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
        onLibraryChanged: {
            if (root.mode === "local")
                root.browse(false);
            root.loadLocalFiles();
        }
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
            metadataDelay.stop();
            pagination.stop();
        } else {
            if (detailLoading)
                detailDelay.restart();
            metadataDelay.restart();
            pagination.restart();
            if (search.text)
                searchDelay.restart();
        }
    }
    function openUrl(url) {
        Browser.open(url, "games", "", host);
    }
    function updateCatalogue(items, append) {
        titles = Catalogue.update(catalogue, titles, items, append);
    }
    function patchGame(game) {
        const index = titles.findIndex(item => item.id === game.id);
        if (index < 0)
            return;
        const next = titles.slice();
        next[index] = Object.assign({}, next[index], game);
        titles = next;
        catalogue.setProperty(index, "payload", JSON.stringify(next[index]));
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
        const generation = ++browseGeneration;
        const offset = append ? nextOffset : 0;
        loading = true;
        error = "";
        notice = "";
        if (!append) {
            nextOffset = 0;
            metadataQueue = [];
        }
        if (mode === "local") {
            service.request("local_list", {}, (result, failure) => {
                if (generation !== browseGeneration)
                    return;
                loading = false;
                setupRequired = false;
                if (failure) {
                    error = failure;
                    return;
                }
                const query = search.text.trim().toLowerCase();
                updateCatalogue((result || []).filter(game => !query || game.title.toLowerCase().includes(query)), false);
                if (titles.length)
                    selectGame(titles.find(game => game.id === selected.id) || titles[0]);
                else
                    clearSelection();
            });
            return;
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
            notice = result.warning || "";
            updateCatalogue(result.items || [], append);
            nextOffset = Number(result.next || 0);
            if (!append) {
                rail.positionViewAtBeginning();
                grid.positionViewAtBeginning();
                const retained = titles.find(item => item.id === selected.id);
                if (retained)
                    selected = Object.assign({}, selected, retained);
                else if (titles.length)
                    selectGame(titles[0]);
                else
                    clearSelection();
            }
            if (mode === "library") {
                metadataQueue = metadataQueue.concat((result.items || []).filter(game => game.metadataPending).map(game => game.id));
                metadataDelay.restart();
            }
            pagination.restart();
        });
    }
    function clearSelection() {
        closeStoreMenus();
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
    function hydrateSelection(refresh) {
        if (!active || !selected.id)
            return;
        loadLocalFiles();
        if (mode === "local" && selected.local) {
            detailLoading = false;
            return;
        }
        const generation = selectionGeneration;
        const args = {
            gameId: selected.id,
            refresh: !!refresh
        };
        service.request("details", args, (result, failure) => {
            if (generation !== selectionGeneration)
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
                if (generation !== selectionGeneration)
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
    function hydrateLibrary() {
        if (!active || metadataBusy || mode !== "library" || loading)
            return;
        const queue = metadataQueue.filter(gameId => gameId !== selected.id);
        const gameId = queue.shift();
        metadataQueue = queue;
        if (!gameId)
            return;
        const generation = browseGeneration;
        metadataBusy = true;
        service.request("library_metadata", {
            gameId: gameId
        }, (result, failure) => {
            metadataBusy = false;
            if (generation === browseGeneration && !failure && result?.game)
                patchGame(result.game);
            metadataDelay.restart();
        });
    }
    function maybeLoadMore() {
        if (!active || loading || !nextOffset)
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
            if (mode !== "local")
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
        service.request("action", {
            gameId: gameId,
            actionId: action.id
        }, (result, failure) => {
            actionBusy = false;
            if (failure) {
                detailError = failure;
                return;
            }
            notice = result.message || "";
            if (action.type === "play" || result.handoff)
                host?.hide();
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
            else
                hydrateSelection(true);
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
        gridMode = preferences.value("catalogue/grid", false);
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
        id: metadataDelay
        interval: 160
        onTriggered: root.hydrateLibrary()
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
            objectName: "libraryTab"
            text: "My library"
            iconName: "gamepad-2"
            highlighted: root.mode === "library"
            onClicked: root.showMode("library")
        }
        MovieTab {
            objectName: "discoverTab"
            text: "Browse"
            iconName: "globe"
            highlighted: root.mode === "discover"
            onClicked: root.showMode("discover")
        }
        MovieTab {
            objectName: "favoritesTab"
            text: "Favorites"
            iconName: "star"
            highlighted: root.mode === "favorites"
            onClicked: root.showMode("favorites")
        }
        MovieTab {
            text: "Local"
            iconName: "folder-open"
            highlighted: root.mode === "local"
            onClicked: root.showMode("local")
        }
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
        Item {
            Layout.fillWidth: true
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
            jobs: downloads.jobs
            tasks: [task(root.initializing, "init", "Opening Games…"), task(root.loading, "browse", "Loading games…"), task(root.detailLoading, "details", "Loading game details…"), task(root.metadataBusy, "metadata", "Updating game metadata…"), task(root.actionBusy, "action", "Updating game library…"), task(service.pendingCount > 0 && !root.initializing && !root.loading && !root.detailLoading && !root.actionBusy && !root.metadataBusy, "information", "Loading game information…"), task(backdrop.loading || logo.loading, "artwork", "Loading artwork…"), task(root.tab === "torrent" && (downloads.searching || downloads.connectionLoading || downloads.inspectLoading || downloads.reviewLoading), "find", "Loading downloads…")]
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
            iconName: "sliders-horizontal"
            text: "Filters"
            enabled: root.mode === "discover" && root.catalogState.configured
            highlighted: root.filtersOpen
            onClicked: {
                root.filtersOpen = !root.filtersOpen;
                if (root.filtersOpen)
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
            iconName: "download"
            text: "Downloads"
            onClicked: downloads.showJobPanel()
        }
        MovieIconButton {
            objectName: "catalogueLayoutToggle"
            iconName: root.gridMode ? "list" : "layout-grid"
            text: root.gridMode ? "Poster rail" : "Poster grid"
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
        ScrollArea {
            visible: root.filtersOpen
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            contentHeight: height
            RowLayout {
                spacing: 8
                MovieChoice {
                    id: genre
                    objectName: "genrePicker"
                    Layout.preferredWidth: 180
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
                    Layout.preferredWidth: 180
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
                    model: ["Popular", "Highest rating", "Newest release", "Recently updated", "Title"]
                    Accessible.name: "Sort"
                }
                MovieInput {
                    id: fromYear
                    Layout.preferredWidth: 100
                    placeholderText: "From year"
                    Accessible.name: "From year"
                    validator: IntValidator {
                        bottom: 1970
                        top: 2200
                    }
                }
                MovieInput {
                    id: toYear
                    Layout.preferredWidth: 100
                    placeholderText: "To year"
                    Accessible.name: "To year"
                    validator: IntValidator {
                        bottom: 1970
                        top: 2200
                    }
                }
                MovieButton {
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
            }
        }
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
                        text: "ProtonDB · " + (root.compatibility.label || "Unknown")
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
                        visible: !root.selected.local
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
                    host: root.host
                    showLoading: false
                    title: Object.assign({}, root.selected, {
                        kind: "game",
                        year: (root.selected.releaseDate || "").slice(0, 4)
                    })
                    onImported: {
                        root.loadLocalFiles();
                        if (root.mode === "local")
                            root.browse(false);
                    }
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
                    text: root.setupRequired ? "Set up game discovery" : "No games found"
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
                    text: root.setupRequired ? "Add igdb_client_id and igdb_client_secret to " + (root.catalogState.configPath || "games.json") + ". My library works without catalogue credentials." : root.mode === "library" ? "Install a Steam game, sign in with legendary auth for Epic, or sign into GOG in Heroic, then refresh your libraries." : root.mode === "favorites" ? "Save games with the Favorite button." : root.mode === "local" ? "Find a local copy from a game in Browse. Imported files open in your file manager." : "Try another search or change the filters."
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
