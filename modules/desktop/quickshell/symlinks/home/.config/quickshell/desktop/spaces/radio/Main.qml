import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../movies"
import "Stations.js" as Stations

Item {
    id: root
    objectName: "radioBrowser"
    property var host
    property bool active: false
    property var toolbarTarget: null
    property var backdropTarget: null
    property real toolbarHeight: 46
    property var initialFocus: searchOpen ? search : stationList
    property bool initialized: false
    property bool needsBrowse: false
    property bool loading: false
    property bool resolving: false
    property bool commandPending: false
    property bool statusPending: false
    property bool favoriteSaving: false
    property bool syncing: false
    property bool syncEnabled: false
    property string syncError: ""
    property bool searchOpen: false
    property bool filtersOpen: false
    property string country: ""
    property var genres: []
    property var qualities: ({})
    property var favorites: []
    property var results: []
    property var rows: []
    property var rowsByKey: ({})
    property var countries: []
    property var genreOptions: []
    property bool countriesLoaded: false
    property bool genresLoaded: false
    property bool countriesLoading: false
    property bool genresLoading: false
    property string countryError: ""
    property string genreError: ""
    property string error: ""
    property string saveError: ""
    property string playbackError: ""
    property string notice: ""
    property int nextOffset: -1
    property int browseGeneration: 0
    property int playGeneration: 0
    property var playback: ({
            playing: false,
            station: {},
            title: "",
            paused: false
        })
    readonly property bool busy: loading || resolving || commandPending || favoriteSaving || syncing || countriesLoading || genresLoading

    RadioService {
        id: service
        onFailed: message => root.error = message
    }
    Worker {
        id: favoritesService
        objectName: "radioFavoritesService"
        backendDirectory: "spaces/radio"
        backend: "favorites.py"
        spaceId: "radio"
        serviceName: "Radio favorites"
        startOnDemand: true
    }
    ListModel {
        id: stationModel
    }
    Rectangle {
        objectName: "radioBackground"
        parent: root.backdropTarget || root
        anchors.fill: parent
        z: root.backdropTarget ? 0 : -1
        visible: root.active
        color: "#000000"
    }

    function activate() {
        if (active)
            initialFocus.forceActiveFocus();
    }
    function menuOffset(button, menuWidth) {
        const target = toolbarTarget || root;
        const x = button.mapToItem(target, 0, 0).x;
        return Math.max(-x, Math.min(0, target.width - x - menuWidth));
    }
    function favorite(key) {
        const station = rowsByKey[key];
        return favorites.some(item => item.groupKey === key || (station && Stations.sameFavorite(item, station)));
    }
    function acceptFavorites(items) {
        const records = [];
        for (const item of items)
            records.push(...(item.variants?.length ? item.variants : [item]));
        favorites = Stations.groupStations(records);
    }
    function syncFavorites() {
        if (!initialized || !syncEnabled || syncing || favoriteSaving)
            return;
        syncing = true;
        favoritesService.request("sync", {}, (result, failure) => {
            syncing = false;
            syncError = failure || result?.warning || "";
            if (!failure && result) {
                acceptFavorites(result.favorites || []);
                displayRows(true);
            }
        }, 0);
    }
    function persist() {
        if (!initialized)
            return;
        service.request("settings-save", {
            settings: {
                country: country,
                genres: genres,
                qualities: qualities
            }
        }, (result, failure) => {
            saveError = failure || "";
        });
    }
    function displayRows(preserve) {
        const selected = stationList.currentIndex >= 0 ? stationModel.get(stationList.currentIndex)?.key : "";
        const scroll = stationList.contentY;
        const query = search.text.trim().toLowerCase();
        const pinned = favorites.filter(item => (!query || [item.name, item.country, item.tags, item.language].join(" ").toLowerCase().includes(query)) && (!country || item.country === country) && genres.every(tag => item.tags.split(",").some(value => Stations.genreKey(value) === Stations.genreKey(tag))));
        const next = pinned.concat(Stations.groupStations(results).filter(item => !pinned.some(saved => Stations.sameFavorite(saved, item))));
        rows = next;
        const indexed = {};
        for (const item of next)
            indexed[item.groupKey] = item;
        rowsByKey = indexed;
        // Keep delegates and scroll position stable as additional stream variants arrive.
        for (let i = 0; i < next.length; ++i) {
            if (i < stationModel.count && stationModel.get(i).key === next[i].groupKey)
                continue;
            let found = -1;
            for (let j = i + 1; j < stationModel.count; ++j)
                if (stationModel.get(j).key === next[i].groupKey) {
                    found = j;
                    break;
                }
            if (found >= 0)
                stationModel.move(found, i, 1);
            else
                stationModel.insert(i, {
                    key: next[i].groupKey
                });
        }
        if (stationModel.count > next.length)
            stationModel.remove(next.length, stationModel.count - next.length);
        const index = preserve ? next.findIndex(item => item.groupKey === selected) : -1;
        stationList.currentIndex = index >= 0 ? index : next.length ? 0 : -1;
        if (preserve)
            stationList.contentY = scroll;
        else
            stationList.positionViewAtBeginning();
    }
    function browse(append) {
        if (!initialized)
            return;
        if (!active) {
            needsBrowse = true;
            return;
        }
        needsBrowse = false;
        if (append && (loading || nextOffset < 0))
            return;
        const generation = ++browseGeneration;
        searchDelay.stop();
        error = "";
        notice = "";
        const offset = append ? nextOffset : 0;
        loading = true;
        if (!append) {
            nextOffset = -1;
            results = [];
            displayRows(false);
        }
        service.request("browse", {
            query: search.text.trim(),
            country: country,
            tags: genres,
            offset: offset
        }, (result, failure) => {
            if (generation !== browseGeneration)
                return;
            loading = false;
            if (failure) {
                error = failure;
                return;
            }
            const incoming = result.items || [];
            const seen = new Set((append ? results : []).map(item => item.stationuuid));
            results = (append ? results : []).concat(incoming.filter(item => !seen.has(item.stationuuid)));
            nextOffset = result.nextOffset >= 0 && result.nextOffset !== offset ? result.nextOffset : -1;
            notice = result.warning || "";
            displayRows(append);
        });
    }
    function scheduleBrowse() {
        if (initialized) {
            if (active)
                searchDelay.restart();
            else
                needsBrowse = true;
        }
    }
    function maybeLoadMore() {
        if (active && !loading && !error && nextOffset >= 0 && stationList.contentY + stationList.height >= stationList.contentHeight - 240)
            browse(true);
    }
    function loadOptions(kind) {
        const isCountry = kind === "countries";
        if (isCountry ? countriesLoading || countriesLoaded : genresLoading || genresLoaded)
            return;
        if (isCountry) {
            countriesLoading = true;
            countryError = "";
        } else {
            genresLoading = true;
            genreError = "";
        }
        service.request(kind, {}, (result, failure) => {
            if (isCountry) {
                countriesLoading = false;
                countryError = failure || result?.warning || "";
                if (!failure) {
                    countries = result.items || [];
                    countriesLoaded = !result.warning;
                }
            } else {
                genresLoading = false;
                genreError = failure || result?.warning || "";
                if (!failure) {
                    genreOptions = result.items || [];
                    genresLoaded = !result.warning;
                }
            }
        });
    }
    function toggleGenre(name) {
        if (!genres.includes(name) && genres.length >= 12) {
            saveError = "Choose up to 12 genres.";
            return;
        }
        genres = genres.includes(name) ? genres.filter(tag => tag !== name) : genres.concat([name]);
        persist();
        scheduleBrowse();
    }
    function toggleFavorite(station) {
        if (!station || favoriteSaving || syncing)
            return;
        const next = favorite(station.groupKey) ? favorites.filter(item => !Stations.sameFavorite(item, station)) : [station].concat(favorites);
        favoriteSaving = true;
        favoritesService.request("favorites-save", {
            favorites: next
        }, (result, failure) => {
            favoriteSaving = false;
            saveError = failure || "";
            if (!failure) {
                acceptFavorites(result);
                displayRows(true);
                syncFavorites();
            }
        });
    }
    function qualityIndex(station) {
        const index = (station.qualityOptions || []).findIndex(item => item.stationuuid === qualities[station.groupKey]);
        return Math.max(0, index);
    }
    function chooseQuality(station, index) {
        const option = station.qualityOptions[index];
        if (!option)
            return;
        qualities = Object.assign({}, qualities, {
            [station.groupKey]: option.stationuuid
        });
        persist();
        if (playback.playing && Stations.stationGroupKey(playback.station) === station.groupKey)
            play(station);
    }
    function applyPlayback(result, failure) {
        if (failure) {
            playbackError = failure;
            return;
        }
        playback = result;
        playbackError = result.error || "";
    }
    function play(station) {
        if (!station)
            return;
        const variant = (station.variants || []).find(item => item.stationuuid === station.qualityOptions[qualityIndex(station)]?.stationuuid) || station;
        const generation = ++playGeneration;
        resolving = true;
        commandPending = false;
        playbackError = "";
        service.request("resolve", {
            station: variant
        }, (result, failure) => {
            if (generation !== playGeneration)
                return;
            resolving = false;
            if (failure) {
                playbackError = failure;
                return;
            }
            commandPending = true;
            service.request("start", result, (state, startFailure) => {
                if (generation !== playGeneration)
                    return;
                commandPending = false;
                applyPlayback(state, startFailure);
                if (!startFailure && result.warning)
                    playbackError = result.warning;
            });
        });
    }
    function playerCommand(op) {
        const generation = ++playGeneration;
        resolving = false;
        commandPending = true;
        service.request(op, {}, (result, failure) => {
            if (generation !== playGeneration)
                return;
            commandPending = false;
            applyPlayback(result, failure);
        });
    }
    function refreshStatus() {
        if (!active || statusPending || resolving || commandPending)
            return;
        const generation = playGeneration;
        statusPending = true;
        service.request("status", {}, (result, failure) => {
            statusPending = false;
            if (generation === playGeneration) {
                if (failure)
                    playbackError = failure;
                else {
                    playback = result;
                    if (result.error)
                        playbackError = result.error;
                }
            }
        });
    }
    function dismissTransient() {
        if (countryMenu.visible) {
            countryMenu.close();
            return true;
        }
        if (genreMenu.visible) {
            genreMenu.close();
            return true;
        }
        for (const child of stationList.contentItem.children) {
            if (child.closeMenu && child.closeMenu())
                return true;
        }
        if (filtersOpen) {
            filtersOpen = false;
            return true;
        }
        if (search.text.length) {
            search.clear();
            return true;
        }
        if (searchOpen) {
            searchOpen = false;
            return true;
        }
        return false;
    }
    onActiveChanged: {
        if (!active) {
            if (searchDelay.running)
                needsBrowse = true;
            searchDelay.stop();
            pagination.stop();
            countryMenu.close();
            genreMenu.close();
            for (const child of stationList.contentItem.children)
                if (child.closeMenu)
                    child.closeMenu();
        } else if (initialized) {
            if (needsBrowse)
                browse(false);
            syncFavorites();
            refreshStatus();
            Qt.callLater(activate);
        }
    }
    Component.onCompleted: service.request("init", {}, (result, failure) => {
        if (failure) {
            error = failure;
            return;
        }
        country = result.settings.country || "";
        genres = result.settings.genres || [];
        qualities = result.settings.qualities || ({});
        acceptFavorites(result.favorites);
        syncEnabled = !!result.syncConfigured;
        initialized = true;
        browse(false);
        syncFavorites();
    })
    Timer {
        id: searchDelay
        interval: 350
        onTriggered: root.browse(false)
    }
    Timer {
        id: pagination
        interval: 120
        onTriggered: root.maybeLoadMore()
    }
    Timer {
        objectName: "radioMetadataTimer"
        interval: 2500
        repeat: true
        running: root.active && root.playback.playing
        onTriggered: root.refreshStatus()
    }
    Timer {
        objectName: "radioSyncTimer"
        interval: 60000
        repeat: true
        running: root.active && root.syncEnabled && root.initialized
        onTriggered: root.syncFavorites()
    }

    RowLayout {
        objectName: "radioToolbar"
        parent: root.toolbarTarget || root
        width: parent.width
        height: root.toolbarHeight
        visible: root.active
        spacing: 8
        MovieText {
            objectName: "radioStationHeading"
            text: "Stations"
            font.bold: true
        }
        MovieText {
            objectName: "radioStationCount"
            text: root.rows.length.toLocaleString()
            color: MovieStyle.muted
        }
        Item {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.preferredWidth: 0
        }
        Flickable {
            id: inlineFilters
            objectName: "radioFilters"
            visible: root.filtersOpen
            Layout.fillWidth: true
            Layout.preferredWidth: filterFields.implicitWidth
            Layout.minimumWidth: 110
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
                MovieButton {
                    id: countryButton
                    objectName: "radioCountry"
                    text: root.country || "All countries"
                    iconName: "map-pin"
                    width: 190
                    onClicked: {
                        root.loadOptions("countries");
                        countryMenu.visible ? countryMenu.close() : countryMenu.open();
                    }
                    FilterMenu {
                        id: countryMenu
                        objectName: "radioCountryMenu"
                        y: countryButton.height + 4
                        width: Math.min(320, root.width)
                        height: Math.min(420, root.height)
                        x: root.menuOffset(countryButton, width)
                        options: [
                            {
                                name: ""
                            }
                        ].concat(root.countries)
                        selectedNames: [root.country]
                        loading: root.countriesLoading
                        error: root.countryError
                        placeholder: "Search countries…"
                        onRetry: root.loadOptions("countries")
                        onChosen: name => {
                            root.country = name;
                            close();
                            root.persist();
                            root.scheduleBrowse();
                            countryButton.forceActiveFocus();
                        }
                    }
                }
                MovieButton {
                    id: genreButton
                    objectName: "radioGenres"
                    text: root.genres.length ? "Genres (" + root.genres.length + ")" : "Genres"
                    iconName: "music"
                    width: 135
                    onClicked: {
                        root.loadOptions("genres");
                        genreMenu.visible ? genreMenu.close() : genreMenu.open();
                    }
                    FilterMenu {
                        id: genreMenu
                        objectName: "radioGenreMenu"
                        y: genreButton.height + 4
                        width: Math.min(320, root.width)
                        height: Math.min(420, root.height)
                        x: root.menuOffset(genreButton, width)
                        options: root.genreOptions
                        selectedNames: root.genres
                        multiple: true
                        loading: root.genresLoading
                        error: root.genreError
                        placeholder: "Search genres…"
                        onRetry: root.loadOptions("genres")
                        onChosen: name => root.toggleGenre(name)
                    }
                }
                MovieButton {
                    text: "Reset"
                    onClicked: {
                        root.country = "";
                        root.genres = [];
                        root.persist();
                        root.browse(false);
                    }
                }
            }
        }
        MovieInput {
            id: search
            objectName: "radioSearch"
            visible: root.searchOpen
            rightPadding: 40
            Layout.preferredWidth: Math.min(300, root.width * 0.25)
            Layout.minimumWidth: 100
            placeholderText: "Search stations…"
            Accessible.name: "Search radio stations"
            onTextChanged: root.scheduleBrowse()
            onAccepted: root.browse(false)
            MovieIconButton {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 36
                height: 36
                visible: !!search.text
                iconName: "x"
                text: "Clear station search"
                onClicked: {
                    search.clear();
                    search.forceActiveFocus();
                }
            }
        }
        Item {
            Layout.minimumWidth: 28
            Layout.maximumWidth: 28
            Layout.preferredHeight: 28
            ActivityIndicator {
                anchors.fill: parent
                active: root.active
                spinnerName: "radioLoadingIndicator"
                tasks: [task(root.loading, "browse", "Loading stations…"), task(root.resolving, "resolve", "Connecting to station…"), task(root.commandPending, "player", "Updating playback…"), task(root.favoriteSaving, "favorites", "Saving favorites…"), task(root.syncing, "sync", "Syncing favorites…"), task(root.countriesLoading, "countries", "Loading countries…"), task(root.genresLoading, "genres", "Loading genres…")]
            }
        }
        MovieIconButton {
            objectName: "radioSearchButton"
            iconName: "search"
            text: "Search stations"
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
            objectName: "radioFiltersButton"
            iconName: "sliders-horizontal"
            text: "Station filters"
            highlighted: root.filtersOpen || !!root.country || root.genres.length > 0
            onClicked: root.filtersOpen = !root.filtersOpen
        }
        MovieIconButton {
            objectName: "radioRefresh"
            iconName: "refresh-cw"
            text: "Refresh stations and sync favorites"
            onClicked: {
                if (root.initialized) {
                    root.browse(false);
                    root.syncFavorites();
                } else
                    root.error = "Close Radio in Spaces and reopen it to retry loading saved records.";
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 74
            spacing: 14
            MovieIcon {
                name: "boom-box"
                width: 32
                height: 32
                color: root.playback.playing ? MovieStyle.accent : MovieStyle.muted
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                MovieText {
                    objectName: "radioNowPlaying"
                    Layout.fillWidth: true
                    text: root.playback.station.name || "Radio"
                    font.pixelSize: MovieStyle.fontSize * 1.7
                    font.bold: true
                    elide: Text.ElideRight
                }
                MovieText {
                    objectName: "radioSong"
                    Layout.fillWidth: true
                    text: root.playback.title || (root.resolving ? "Resolving station…" : root.playback.paused ? "Paused" : root.playback.connecting ? "Connecting…" : root.playback.playing ? "Live radio" : "Choose a station to start listening.")
                    color: MovieStyle.muted
                    elide: Text.ElideRight
                }
            }
            MovieIconButton {
                objectName: "radioPause"
                visible: root.playback.playing
                enabled: !root.commandPending && !root.resolving
                iconName: root.playback.paused ? "play" : "pause"
                text: root.playback.paused ? "Resume playback" : "Pause playback"
                onClicked: root.playerCommand("pause")
            }
            MovieIconButton {
                objectName: "radioStop"
                visible: root.playback.playing || root.resolving || root.commandPending
                iconName: "square"
                text: "Stop Radio playback"
                onClicked: root.playerCommand("stop")
            }
        }
        RowLayout {
            Layout.fillWidth: true
            visible: !!root.error || !!root.saveError || !!root.syncError || !!root.playbackError
            MovieText {
                Layout.fillWidth: true
                text: [root.error, root.saveError, root.syncError, root.playbackError].filter(Boolean).join("\n")
                color: MovieStyle.danger
                wrapMode: Text.Wrap
            }
            MovieButton {
                visible: !!root.error
                text: "Retry"
                onClicked: root.browse(false)
            }
            MovieButton {
                visible: !!root.syncError
                text: "Retry sync"
                enabled: !root.syncing
                onClicked: root.syncFavorites()
            }
        }
        Flow {
            Layout.fillWidth: true
            visible: !!root.country || root.genres.length > 0
            spacing: 5
            MovieButton {
                visible: !!root.country
                text: root.country + "  ×"
                Accessible.name: "Clear country filter"
                onClicked: {
                    root.country = "";
                    root.persist();
                    root.browse(false);
                }
            }
            Repeater {
                model: root.genres
                MovieButton {
                    required property string modelData
                    text: modelData + "  ×"
                    Accessible.name: "Remove genre " + modelData
                    onClicked: root.toggleGenre(modelData)
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: MovieStyle.border
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ListView {
                id: stationList
                objectName: "radioStationList"
                anchors.fill: parent
                clip: true
                model: stationModel
                spacing: 2
                activeFocusOnTab: true
                keyNavigationEnabled: true
                keyNavigationWraps: false
                onContentYChanged: if (root.active)
                    pagination.restart()
                Keys.onReturnPressed: if (currentItem)
                    root.play(currentItem.station)
                Keys.onEnterPressed: if (currentItem)
                    root.play(currentItem.station)
                Keys.onSpacePressed: if (root.playback.playing)
                    root.playerCommand("pause")
                else if (currentItem)
                    root.play(currentItem.station)
                delegate: Rectangle {
                    id: row
                    required property string key
                    required property int index
                    readonly property var station: root.rowsByKey[key] || ({})
                    readonly property bool playing: root.playback.playing && Stations.stationGroupKey(root.playback.station) === key
                    width: stationList.width
                    height: Math.max(78, stationInfo.implicitHeight + 24)
                    radius: 6
                    color: playing ? MovieStyle.accentSurface : rowMouse.containsMouse ? "#18ffffff" : "transparent"
                    border.width: stationList.activeFocus && stationList.currentIndex === index ? 1 : 0
                    border.color: MovieStyle.accent
                    function closeMenu() {
                        if (quality.popup.visible) {
                            quality.popup.close();
                            return true;
                        }
                        return false;
                    }
                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            stationList.currentIndex = row.index;
                            stationList.forceActiveFocus();
                        }
                        onDoubleClicked: root.play(row.station)
                    }
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 12
                        MovieIconButton {
                            objectName: "radioPlay:" + row.index
                            iconName: row.playing && !root.playback.paused ? "pause" : "play"
                            text: row.playing ? root.playback.paused ? "Resume " + row.station.name : "Pause " + row.station.name : "Play " + row.station.name
                            onClicked: {
                                stationList.currentIndex = row.index;
                                if (row.playing)
                                    root.playerCommand("pause");
                                else
                                    root.play(row.station);
                            }
                        }
                        ColumnLayout {
                            id: stationInfo
                            Layout.fillWidth: true
                            spacing: 5
                            MovieText {
                                Layout.fillWidth: true
                                text: row.station.name || ""
                                font.bold: true
                                font.pixelSize: MovieStyle.fontSize * 1.2
                                elide: Text.ElideRight
                            }
                            MovieText {
                                Layout.fillWidth: true
                                text: [row.station.country, row.station.language, (row.station.tags || "").split(",").slice(0, 5).join(" · ")].filter(Boolean).join("   /   ")
                                color: MovieStyle.muted
                                elide: Text.ElideRight
                            }
                        }
                        MovieChoice {
                            id: quality
                            objectName: "radioQuality:" + row.index
                            Layout.preferredWidth: Math.min(180, root.width * 0.20)
                            model: (row.station.qualityOptions || []).map(item => item.label)
                            currentIndex: root.qualityIndex(row.station)
                            Accessible.name: "Stream quality for " + row.station.name
                            onActivated: index => root.chooseQuality(row.station, index)
                        }
                        Item {
                            visible: root.width > 700
                            implicitWidth: MovieStyle.controlHeight
                            implicitHeight: MovieStyle.controlHeight
                            MovieIconButton {
                                anchors.fill: parent
                                visible: /^https?:\/\//i.test(row.station.homepage || "")
                                iconName: "globe"
                                text: "Station website"
                                onClicked: Browser.open(row.station.homepage, "radio", "", root.host)
                            }
                        }
                        MovieIconButton {
                            objectName: "radioFavorite:" + row.index
                            enabled: !root.favoriteSaving && !root.syncing
                            highlighted: root.favorite(row.key)
                            iconName: highlighted ? "star-filled" : "star"
                            text: highlighted ? "Remove favorite " + row.station.name : "Favorite " + row.station.name
                            onClicked: root.toggleFavorite(row.station)
                        }
                    }
                }
                WheelScroll {
                    view: stationList
                    wheelStep: 330
                }
                ScrollBar.vertical: MovieScrollBar {}
                footer: MovieButton {
                    visible: root.nextOffset >= 0
                    enabled: !root.loading
                    text: root.loading ? "Loading stations…" : "Load more stations"
                    onClicked: root.browse(true)
                }
            }
            MovieText {
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 480)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                visible: !root.rows.length
                color: MovieStyle.muted
                text: root.loading ? "Finding stations…" : root.error ? "" : "No stations match these filters."
            }
        }
    }
}
