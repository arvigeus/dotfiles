import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "../../ui"
import "../movies"
import "../movies/Catalogue.js" as Catalogue

Item {
    id: root
    property bool active: false
    property bool searchOpen: false
    function fontSize(value) { return Math.round(value * MovieStyle.fontSize / 14); }
    property var toolbarTarget: null
    property var backdropTarget: null
    property var initialFocus: searchOpen ? search : gridMode ? grid : rail
    property real toolbarHeight: 46
    property bool initialized: false
    property string savedProvider: ""
    property bool needsBrowse: false
    property bool preferencesReady: false
    property var host
    readonly property url selectedPreviewSource: selected.preview || selected.thumbLarge || selected.path || ""
    readonly property url selectedOriginalSource: selected.path || selectedPreviewSource
    property var wallpapers: []
    property var selected: ({})
    readonly property bool engineSelected: selected.provider === "wallpaper_engine"
    readonly property bool videoSelected: selected.kind === "video"
    property bool favoritesView: false
    property bool gridMode: false
    property bool filtersOpen: false
    property bool loading: true
    property bool randomLoading: false
    property bool settingWallpaper: false
    property bool openingWorkshop: false
    property string engineSetupMessage: ""
    property bool engineReady: false
    property int installationGeneration: 0
    property bool favoriteSaving: false
    property string providerId: "wallhaven"
    property bool providerCatalogReady: false
    property var providerOptions: [
        {id:"wallhaven",name:"Wallhaven",random:true,search:true},
        {id:"bing",name:"Bing Daily",random:true,search:true}
    ]
    property string error: ""
    property string actionMessage: ""
    property bool actionFailed: false
    property string query: ""
    property int browseGeneration: 0
    property int favoriteGeneration: 0
    property var page: 0
    property var filters: ({categories:"111",sorting:"hot",topRange:"1M",ratio:"",resolution:"",tagQuery:"",tagLabel:""})
    property var pendingFilters: ({categories:"111",sorting:"hot",topRange:"1M",ratio:"",resolution:"",tagQuery:"",tagLabel:""})
    property var providerFilters: ({
        wallhaven:{categories:"111",sorting:"hot",topRange:"1M",ratio:"",resolution:"",tagQuery:"",tagLabel:""},
        bing:{country:"US"}
    })
    property int tagSuggestionGeneration: 0
    property string tagSuggestionQuery: ""
    property var tagSuggestionResults: []
    property bool searchingTagSuggestions: false

    ListModel { id: catalogue }
    Worker { id: service; backend: "backend.py"; backendDirectory: "spaces/pictures"; spaceId: "pictures"; serviceName: "Pictures"; onFailed: message => root.error = message }
    ArtworkCache { id: picturesCache; spaceId: "pictures" }

    function isFavorite(value) {
        const key = typeof value === "string" ? value : wallpaperKey(value);
        return favoriteIds.has(key);
    }
    property var favoriteIds: new Set()

    function providerName(id) {
        const provider = providerOptions.find(value => value.id === id);
        return provider ? provider.name : id;
    }
    function providerDescriptor(id) { return providerOptions.find(value => value.id === id) || null; }
    function providerIndex(id) { return providerOptions.findIndex(value => value.id === id); }
    function providerSupports(id, capability) {
        const descriptor = providerDescriptor(id);
        return !!(descriptor && descriptor[capability]);
    }
    function syncFilterControls() {
        pendingFilters = Object.assign({}, filters);
    }
    function filterIndex(field) {
        const value = pendingFilters[field.key];
        const index = field.options.findIndex(option => option.value === value);
        return Math.max(0, index);
    }
    function filterVisible(field) {
        return !field.when || pendingFilters[field.when.key] === field.when.value;
    }
    function updatePendingFilter(key, value) {
        const next = Object.assign({}, pendingFilters);
        next[key] = value;
        pendingFilters = next;
    }
    function searchWallhavenTags(query) {
        const clean = String(query || "").trim().slice(0, 100);
        const generation = ++tagSuggestionGeneration;
        if (!clean) {
            tagSuggestionQuery = "";
            tagSuggestionResults = [];
            searchingTagSuggestions = false;
            return;
        }
        tagSuggestionQuery = clean.toLowerCase();
        tagSuggestionResults = [];
        searchingTagSuggestions = true;
        service.request("tagSearch", {query:clean}, (result, failure) => {
            if (generation !== tagSuggestionGeneration) return;
            searchingTagSuggestions = false;
            tagSuggestionResults = failure || !result ? [] : (result.tags || []);
        });
    }
    function selectProvider(id) {
        if (id === providerId || !providerDescriptor(id)) return;
        const stored = Object.assign({}, providerFilters);
        stored[providerId] = Object.assign({}, filters);
        providerFilters = stored;
        providerId = id;
        const descriptor = providerDescriptor(id);
        filters = Object.assign({}, providerFilters[id] || descriptor.defaultFilters || {});
        providerChoice.currentIndex = Math.max(0, providerIndex(id));
        syncFilterControls();
        updateCatalogue([], false);
        selected = ({});
        page = 0;
        actionMessage = "";
        query = "";
        search.text = "";
        searchDelay.stop();
        browse(false);
    }
    function loadProviders(initial) {
        service.request("providers", {}, (result, failure) => {
            if (failure || !result || !Array.isArray(result.providers)) {
                if (initial) { loading = false; error = failure || "Could not load wallpaper providers."; }
                return;
            }
            providerOptions = result.providers;
            providerCatalogReady = true;
            if (initial) {
                providerId = providerDescriptor(savedProvider) ? savedProvider : (providerDescriptor(result.currentProvider) ? result.currentProvider : "wallhaven");
                filters = Object.assign({}, providerDescriptor(providerId).defaultFilters || {}, providerFilters[providerId] || {});
                syncFilterControls();
            }
            providerChoice.currentIndex = Math.max(0, providerIndex(providerId));
            if (initial) browse(false);
        });
    }

    function focusCatalogue() {
        const view = gridMode ? grid : rail;
        const index = wallpapers.findIndex(item => wallpaperKey(item) === wallpaperKey(selected));
        if (index >= 0) {
            view.currentIndex = index;
            if (gridMode) grid.positionViewAtIndex(index, GridView.Contain);
            else rail.positionViewAtIndex(index, ListView.Contain);
        }
        view.forceActiveFocus();
        pagination.restart();
    }
    function activate() { if(active) focusCatalogue(); }

    function wallpaperKey(item) { return item && item.id ? String(item.provider || "wallhaven") + ":" + String(item.id) : ""; }
    function updateCatalogue(items, append) {
        wallpapers = Catalogue.update(catalogue, wallpapers, items, append, wallpaperKey);
    }

    function selectWallpaper(item) {
        if (!item || !item.id) return;
        selected = item;
        actionMessage = "";
        actionFailed = false;
        engineSetupMessage = "";
        engineReady = false;
        installationGeneration++;
        const index = wallpapers.findIndex(value => wallpaperKey(value) === wallpaperKey(item));
        if (index >= 0) {
            if (gridMode) {
                grid.currentIndex = index;
                if (grid.visible) grid.positionViewAtIndex(index, GridView.Contain);
            } else {
                rail.currentIndex = index;
                if (rail.visible) rail.positionViewAtIndex(index, ListView.Contain);
            }
        }
        Qt.callLater(root.refreshEngineInstallation);
    }

    function browse(append) {
        if (!active) { needsBrowse=true; loading=false; return; }
        needsBrowse=false;
        if (append && (loading || !page || favoritesView)) return;
        const generation = ++browseGeneration;
        const requestedPage = append ? page : 1;
        loading = true;
        error = "";
        service.request("browse", {
            favorites:favoritesView,
            provider:providerId,
            query:query,
            page:requestedPage,
            filters:filters
        }, (result, failure) => {
            if (generation !== browseGeneration) return;
            loading = false;
            if (failure) { error = failure; return; }
            updateCatalogue(result.items || [], append);
            page = favoritesView ? 0 : (result.next || 0);
            if (!append) {
                if (wallpapers.length) {
                    selectWallpaper(wallpapers.find(item => wallpaperKey(item) === wallpaperKey(selected)) || wallpapers[0]);
                } else {
                    selected = ({});
                    actionMessage = "";
                }
            }
            if (active) pagination.restart();
        });
    }

    function chooseRandom() {
        if (randomLoading) return;
        if (favoritesView) {
            favoritesView = false;
            browse(false);
        }
        const epoch = browseGeneration;
        const requestedProvider = providerId;
        randomLoading = true;
        actionMessage = "";
        actionFailed = false;
        service.request("random", {provider:providerId,query:query,filters:filters}, (result, failure) => {
            randomLoading = false;
            if (epoch !== browseGeneration || requestedProvider !== providerId || favoritesView) return;
            if (failure) { error = failure; return; }
            const item = result && result.wallpaper;
            if (!item) { error = providerName(providerId) + " did not return a random image."; return; }
            updateCatalogue([item], true);
            selectWallpaper(item);
        });
    }

    function toggleFavorite() {
        if (!selected || !selected.id || favoriteSaving) return;
        const wallpaper = selected;
        const wallpaperId = wallpaperKey(wallpaper);
        const generation = ++favoriteGeneration;
        const value = !isFavorite(wallpaperId);
        favoriteSaving = true;
        service.request("favorite", {wallpaper:wallpaper,favorite:value}, (result, failure) => {
            if (generation !== favoriteGeneration) return;
            favoriteSaving = false;
            if (failure) { actionMessage = failure; actionFailed = true; return; }
            const next = new Set(favoriteIds);
            if (value) next.add(wallpaperId); else next.delete(wallpaperId);
            favoriteIds = next;
            actionFailed = false;
            actionMessage = value ? "Added to Favorites." : "Removed from Favorites.";
            if (favoritesView) browse(false);
        });
    }

    function setDesktopWallpaper() {
        if (!selected || !selected.id || settingWallpaper) return;
        const wallpaper = selected;
        const key = wallpaperKey(wallpaper);
        settingWallpaper = true;
        engineSetupMessage = "";
        actionMessage = engineSelected ? "Starting Wallpaper Engine…" : "Downloading wallpaper…";
        actionFailed = false;
        service.request("set", {wallpaper:wallpaper}, (result, failure) => {
            settingWallpaper = false;
            if (key !== wallpaperKey(selected)) return;
            actionMessage = failure || (result ? result.message : "Wallpaper could not be set.");
            actionFailed = !!failure;
        });
    }

    function openSteamWorkshop() {
        if (!engineSelected || !selected.id || openingWorkshop) return;
        const key = wallpaperKey(selected);
        openingWorkshop = true;
        actionMessage = "Opening Steam…";
        actionFailed = false;
        service.request("openWorkshop", {workshopId:selected.id}, (result, failure) => {
            openingWorkshop = false;
            if (key !== wallpaperKey(selected)) return;
            actionMessage = failure || (result ? result.message : "Steam could not open the Workshop page.");
            actionFailed = !!failure;
        });
    }

    function refreshEngineInstallation() {
        if (!active || !engineSelected || !selected.id) return;
        const key = wallpaperKey(selected);
        const generation = ++installationGeneration;
        service.request("installationStatus", {wallpaper:selected}, (result, failure) => {
            if (generation !== installationGeneration || key !== wallpaperKey(selected)) return;
            engineSetupMessage = failure || (result ? result.message : "");
            engineReady = !failure && !!result && !!result.ready;
            if (!failure && result && result.wallpaper && result.wallpaper.installed !== selected.installed) {
                const updated = result.wallpaper;
                updateCatalogue(wallpapers.map(item => wallpaperKey(item) === key ? updated : item), false);
                selectWallpaper(updated);
                engineSetupMessage = result.message || "";
                engineReady = !!result.ready;
            }
        });
    }

    function applyFilters() {
        filters = Object.assign({}, pendingFilters);
        const stored = Object.assign({}, providerFilters);
        stored[providerId] = Object.assign({}, filters);
        providerFilters = stored;
        browse(false);
    }

    function resetFilters() {
        const descriptor = providerDescriptor(providerId);
        filters = Object.assign({}, descriptor ? descriptor.defaultFilters : {});
        const stored = Object.assign({}, providerFilters);
        stored[providerId] = Object.assign({}, filters);
        providerFilters = stored;
        syncFilterControls();
        browse(false);
    }

    function loadFavoriteIds() {
        service.request("browse", {favorites:true,query:"",page:1}, (result, failure) => {
            if (failure) { error = failure; return; }
            favoriteIds = new Set((result.items || []).map(item => wallpaperKey(item)));
        });
    }

    function dismissTransient() {
        if (gallery.visible) { gallery.close(); return true; }
        if (providerChoice.popup.visible) { providerChoice.popup.close(); return true; }
        for (let i=0;i<filterControls.count;i++) {
            const control=filterControls.itemAt(i)?.item;
            if (control?.dismissTransient && control.dismissTransient()) return true;
            if (control?.popup?.visible) { control.popup.close(); return true; }
        }
        if (filtersOpen) { filtersOpen=false; return true; }
        if (search.text) { search.text=""; return true; }
        if (searchOpen) { searchOpen=false; return true; }
        return false;
    }
    function savePreferences() {
        if (!preferencesReady) return;
        preferencesDelay.restart();
    }
    onGridModeChanged: savePreferences()
    onProviderIdChanged: savePreferences()
    onProviderFiltersChanged: savePreferences()
    onActiveChanged: {
        if (!active) {
            pagination.stop(); searchDelay.stop();
            gallery.close(); providerChoice.popup.close();
            for(let i=0;i<filterControls.count;i++) {
                const control=filterControls.itemAt(i)?.item;
                if(control?.dismissTransient) control.dismissTransient();
                else if(control?.popup) control.popup.close();
            }
        } else if (initialized) { if(needsBrowse && providerCatalogReady) browse(false); pagination.restart(); Qt.callLater(focusCatalogue); }
    }
    Component.onCompleted: {
        service.request("preferences", {}, (result, failure) => {
            if (result) {
                gridMode=!!result.grid;
                providerId=result.provider || "wallhaven"; savedProvider=result.provider || "";
                providerFilters=Object.assign({}, providerFilters, result.filters || {});
                initialized=!!result.provider;
            }
            preferencesReady=true;
            loadFavoriteIds(); loadProviders(true);
            initialized=true;
        });
    }
    Timer { id: preferencesDelay; interval: 200; onTriggered: service.request("savePreferences", {values:{grid:root.gridMode,provider:root.providerId,filters:root.providerFilters}}, (result, failure) => { if(failure) root.error=failure; }) }

    Timer { id: searchDelay; interval: 350; onTriggered: root.browse(false) }
    Timer {
        interval: 3000
        repeat: true
        running: root.active && root.engineSelected && !root.settingWallpaper
        onTriggered: root.refreshEngineInstallation()
    }
    Timer { id: pagination; interval: 100; onTriggered: {
        if (!root.active || root.favoritesView || root.loading || !root.page || !root.wallpapers.length) return;
        const nearEnd = root.gridMode
            ? grid.contentY + grid.height >= grid.contentHeight - grid.cellHeight * 2
            : rail.contentX + rail.width >= rail.contentWidth - rail.width * 0.55;
        if (nearEnd) root.browse(true);
    } }

    ImageGallery { id: gallery; parent: root; cacheService: picturesCache }


    MovieBackdrop {
        id: backdrop
        objectName: "picturesBackdrop"
        cacheService: picturesCache
        parent: root.backdropTarget || root
        anchors.fill: parent
        z: root.backdropTarget ? 0 : -1
        visible: root.active
        ownerKey: root.wallpaperKey(root.selected)
        gridMode: root.gridMode
        readingEdge: Math.min(0.75, (16 + Math.min(root.width * 0.7, 1000)) / Math.max(1, root.width))
        source: root.active ? root.selectedOriginalSource : ""
        poster: root.active ? root.selectedPreviewSource : ""
    }
    Component {
        id: choiceFilter
        MovieChoice {
            property var definition: null
            width: definition?.width || 150
            model: definition ? definition.options.map(option => option.label) : []
            currentIndex: definition ? root.filterIndex(definition) : 0
            Accessible.name: definition?.label || ""
            onActivated: index => root.updatePendingFilter(definition.key, definition.options[index].value)
        }
    }
    Component {
        id: tagsFilter
        PicturesTagPicker {
            property var definition: null
            width: definition?.width || 220
            options: definition?.options || []
            value: root.pendingFilters[definition?.key || "tagQuery"] || ""
            selectedLabel: root.pendingFilters.tagLabel || ""
            searchResults: root.tagSuggestionResults
            searchResultsQuery: root.tagSuggestionQuery
            searching: root.searchingTagSuggestions
            onValueChosen: (value,label) => { root.updatePendingFilter(definition.key,value); root.updatePendingFilter("tagLabel",label); }
            onTagSearchRequested: query => root.searchWallhavenTags(query)
        }
    }
    RowLayout {
        id: toolbar
        objectName: "picturesToolbar"
        parent: root.toolbarTarget || root
        width: parent.width
        height: root.toolbarHeight
        visible: root.active
        spacing: 8
        MovieButton { iconName: "globe"; text: qsTr("Browse"); highlighted: !root.favoritesView; onClicked: { root.favoritesView=false;root.browse(false); } }
        MovieButton { iconName: "star"; text: qsTr("Favorites"); highlighted: root.favoritesView; onClicked: { root.favoritesView=true;root.browse(false); } }
        Item { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0 }
        Flickable {
            id: filterFieldsView
            objectName: "inlinePicturesFilters"
            visible: root.filtersOpen && !root.favoritesView
            Layout.fillWidth: true
            Layout.preferredWidth: filterFields.implicitWidth
            Layout.minimumWidth: 120
            Layout.maximumWidth: filterFields.implicitWidth
            Layout.preferredHeight: 46
            contentWidth: filterFields.implicitWidth; contentHeight: height
            flickableDirection: Flickable.HorizontalFlick
            clip: true
            Row {
                id: filterFields; spacing: 8
                Repeater {
                    id: filterControls
                    model: root.providerDescriptor(root.providerId)?.filters || []
                    Loader {
                        required property var modelData
                        visible: root.filterVisible(modelData)
                        sourceComponent: modelData.type === "tags" ? tagsFilter : choiceFilter
                        onLoaded: item.definition=modelData
                    }
                }
                MovieButton { text: qsTr("Apply"); onClicked: root.applyFilters() }
                MovieButton { text: qsTr("Reset"); onClicked: root.resetFilters() }
            }
            WheelScroll { view: filterFieldsView; orientation: Qt.Horizontal; verticalToHorizontal: true }
            ScrollBar.horizontal: MovieScrollBar {}
        }
        MovieInput {
            id: search; objectName: "picturesSearch"
            visible: root.searchOpen
            Layout.preferredWidth: Math.min(320, root.width * 0.30)
            rightPadding: 42
            placeholderText: root.favoritesView ? qsTr("Search favorites…") : qsTr("Search %1…").arg(root.providerName(root.providerId))
            onTextChanged: {root.query=text;if(root.active)searchDelay.restart();}
            onAccepted: {searchDelay.stop();root.browse(false);}
            MovieIconButton {
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                width: 36; height: 36; visible: search.text.length > 0
                iconName: "x"; text: qsTr("Clear search")
                onClicked: {search.clear();search.forceActiveFocus();}
            }
        }
        MovieChoice {
            id: providerChoice; objectName: "picturesProviderChoice"
            Layout.preferredWidth: 180
            model: root.providerOptions.map(value => value.name)
            enabled: root.providerCatalogReady && !root.favoritesView
            Accessible.name: qsTr("Wallpaper provider")
            onActivated: index => root.selectProvider(root.providerOptions[index].id)
        }
        Item {
            Layout.minimumWidth: 28; Layout.maximumWidth: 28; Layout.preferredHeight: 28
            MovieSpinner {
                anchors.fill: parent
                running: root.active && !gallery.visible && (root.loading || root.randomLoading || root.settingWallpaper || wallpaperPreview.loading || backdrop.loading)
                visible: running
            }
        }
        MovieIconButton {
            objectName: "picturesSearchButton"
            iconName: "search"; text: qsTr("Search wallpapers"); highlighted: root.searchOpen
            onClicked: {root.searchOpen=!root.searchOpen;if(root.searchOpen)search.forceActiveFocus();else search.text="";}
        }
        MovieIconButton {
            objectName: "picturesFiltersButton"
            iconName: "sliders-horizontal"; text: qsTr("Filters")
            enabled: !root.favoritesView; highlighted: root.filtersOpen
            onClicked: {root.filtersOpen=!root.filtersOpen;root.syncFilterControls();}
        }
        MovieIconButton {
            objectName: "wallpaperViewButton"
            iconName: root.gridMode ? "panels-top-left" : "layout-grid"
            text: root.gridMode ? qsTr("Show wallpaper rail") : qsTr("Show grid")
            onClicked: {root.gridMode=!root.gridMode;Qt.callLater(root.focusCatalogue);}
        }
        MovieIconButton {
            objectName: "randomWallpaperButton"
            iconName: "shuffle"; text: qsTr("Select a random wallpaper")
            visible: root.providerSupports(root.providerId,"random")
            enabled: !root.randomLoading && root.providerCatalogReady
            onClicked: root.chooseRandom()
        }
        MovieIconButton { iconName: "refresh-cw"; text: qsTr("Refresh wallpapers"); enabled: !root.loading; onClicked: {root.loadProviders(false);root.loadFavoriteIds();root.browse(false);} }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: root.toolbarTarget ? 0 : root.toolbarHeight + 12
        spacing: 12
        RowLayout {
            visible: !!root.error; Layout.fillWidth: true
            MovieText { text: root.error; color: MovieStyle.danger; Layout.fillWidth: true; wrapMode: Text.Wrap }
            MovieButton { text: qsTr("Retry"); onClicked: root.providerCatalogReady ? root.browse(false) : root.loadProviders(true) }
            MovieIconButton { iconName: "x"; text: qsTr("Dismiss error"); onClicked: root.error="" }
        }
        Item {
            id: content
            objectName: "picturesContent"
            Layout.fillWidth: true; Layout.fillHeight: true
            GridView {
                id: grid; objectName: "wallpaperGrid"
                visible: root.gridMode
                width: parent.width * 0.51; height: parent.height
                cacheBuffer: height * 1.5
                clip: true; model: catalogue
                cellWidth: width / Math.max(2,Math.floor(width/240))
                cellHeight: cellWidth * 0.5625 + 70
                keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: WallpaperTile {
                    cacheService: picturesCache
                    width: grid.cellWidth-8; height: grid.cellHeight-8
                    highlighted: root.wallpaperKey(root.selected)===root.wallpaperKey(wallpaper)
                    favorite: root.isFavorite(wallpaper)
                    onClicked: {grid.forceActiveFocus();grid.currentIndex=index;root.selectWallpaper(wallpaper);}
                }
                onCurrentIndexChanged: if(activeFocus && currentIndex>=0 && currentIndex<root.wallpapers.length)root.selectWallpaper(root.wallpapers[currentIndex])
                Keys.onReturnPressed: if(currentItem)root.selectWallpaper(currentItem.wallpaper)
                Keys.onEnterPressed: if(currentItem)root.selectWallpaper(currentItem.wallpaper)
                onContentYChanged: if(root.active)pagination.restart()
                onContentHeightChanged: if(root.active)pagination.restart()
                onHeightChanged: if(root.active)pagination.restart()
                WheelScroll {view:grid;wheelStep:Math.max(360,grid.cellHeight*1.25)}
                ScrollBar.vertical: MovieScrollBar {}
            }
            ColumnLayout {
                id: detail
                objectName: "pictureDetails"
                x: root.gridMode ? parent.width * 0.55 : 16
                width: root.gridMode ? parent.width * 0.45 : Math.min(parent.width * 0.7,1000)
                height: root.gridMode ? parent.height : parent.height - Math.min(270,parent.height*0.38)
                visible: !!root.selected.id
                spacing: 8
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(72,Math.min(145,root.height*0.17))
                    MovieText {
                        anchors.fill: parent
                        text: root.selected.title || root.providerName(root.selected.provider || root.providerId)+" · "+(root.selected.id || "")
                        font.pixelSize: root.fontSize(Math.min(48,root.width/25)); font.bold: true
                        wrapMode: Text.Wrap; maximumLineCount: 2; verticalAlignment: Text.AlignVCenter
                    }
                }
                MovieText {
                    Layout.fillWidth: true
                    text: [root.selected.resolution,root.selected.fileType?.split("/").pop().toUpperCase(),root.selected.providerName].filter(Boolean).join("   ·   ")
                    color: MovieStyle.muted; wrapMode: Text.Wrap
                }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    MovieButton {
                        objectName: "setWallpaperButton"; iconName: "monitor"
                        text: root.settingWallpaper ? qsTr("Applying…") : qsTr("Set wallpaper & lock screen")
                        idleColor: MovieStyle.accent; enabled: !root.settingWallpaper
                        onClicked: root.setDesktopWallpaper()
                    }
                    MovieButton { objectName: "pictureFullImage"; iconName: "image"; text: qsTr("View full image"); enabled: !!root.selected.path; onClicked: gallery.show([{url:root.selected.path}],0,root.selected.title || qsTr("Wallpaper")) }
                    MovieIconButton { objectName: "favoriteWallpaperButton"; iconName: root.isFavorite(root.selected)?"star-filled":"star"; text: root.isFavorite(root.selected)?qsTr("Remove favorite"):qsTr("Add favorite"); enabled: !root.favoriteSaving; onClicked: root.toggleFavorite() }
                    MovieIconButton { objectName: "openWorkshopButton"; iconName: "globe"; text: root.engineSelected?(root.selected.installed?qsTr("Open in Steam"):qsTr("Download through Steam")):qsTr("Open source"); enabled: !!root.selected.url && !root.openingWorkshop; onClicked: {if(root.engineSelected)root.openSteamWorkshop();else Browser.open(root.selected.url,"pictures","",root.host);} }
                }
                MovieText { Layout.fillWidth: true; visible: !!root.engineSetupMessage && root.engineSelected && !root.settingWallpaper; text: root.engineSetupMessage; color: Theme.warning; wrapMode: Text.Wrap }
                MovieText { Layout.fillWidth: true; visible: !!root.actionMessage; text: root.actionMessage; color: root.actionFailed ? MovieStyle.danger : MovieStyle.muted; wrapMode: Text.Wrap }
                ScrollArea {
                    id: overview
                    objectName: "pictureOverview"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                    contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width; spacing: 12
                        MovieText { visible: !!root.selected.description; Layout.fillWidth: true; text: root.selected.description || ""; wrapMode: Text.Wrap; font.pixelSize: root.fontSize(16) }
                        MovieText { visible: !!root.selected.attribution; Layout.fillWidth: true; text: root.selected.attribution || ""; wrapMode: Text.Wrap; color: MovieStyle.muted }
                        Repeater {
                            model: root.selected.metadata || []
                            MovieText {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData.label+": "+modelData.value
                                color: MovieStyle.muted; wrapMode: Text.Wrap
                            }
                        }
                        Item {
                            objectName: "picturePreviewFrame"
                            readonly property real imageRatio: root.selected.width > 0 && root.selected.height > 0
                                ? root.selected.width / root.selected.height : wallpaperPreview.sourceAspectRatio || 16/9
                            Layout.alignment: Qt.AlignLeft
                            Layout.preferredHeight: Math.min(360, overview.availableWidth / imageRatio)
                            Layout.preferredWidth: Layout.preferredHeight * imageRatio
                            clip: true
                            ProgressiveImage {
                                id: wallpaperPreview; objectName: "selectedWallpaperImage"
                                cacheService: picturesCache
                                anchors.fill: parent
                                source: root.active ? root.selectedOriginalSource : ""
                                previewSource: root.active ? root.selectedPreviewSource : ""
                                ownerKey: root.wallpaperKey(root.selected)
                                fillMode: Image.PreserveAspectFit
                                horizontalAlignment: Image.AlignLeft
                            }
                            MovieText { anchors.centerIn: parent; visible: !!root.selected.id && !!wallpaperPreview.failedSource && !wallpaperPreview.loading; text: qsTr("Preview unavailable"); color: MovieStyle.muted }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: gallery.show([{url:root.selected.path}],0,root.selected.title || qsTr("Wallpaper")) }
                        }
                    }
                }
            }
            ListView {
                id: rail; objectName: "wallpaperRail"
                visible: !root.gridMode
                anchors.bottom: parent.bottom
                width: parent.width; height: Math.min(250,parent.height*0.36)
                cacheBuffer: width * 2
                orientation: ListView.Horizontal; spacing: 12; clip: true; model: catalogue
                keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: WallpaperTile {
                    cacheService: picturesCache
                    width: Math.max(180,Math.min(360,(rail.height-70)*1.78)); height: rail.height
                    highlighted: root.wallpaperKey(root.selected)===root.wallpaperKey(wallpaper)
                    favorite: root.isFavorite(wallpaper)
                    onClicked: {rail.forceActiveFocus();rail.currentIndex=index;root.selectWallpaper(wallpaper);}
                }
                onCurrentIndexChanged: if(activeFocus && currentIndex>=0 && currentIndex<root.wallpapers.length)root.selectWallpaper(root.wallpapers[currentIndex])
                Keys.onReturnPressed: if(currentItem)root.selectWallpaper(currentItem.wallpaper)
                Keys.onEnterPressed: if(currentItem)root.selectWallpaper(currentItem.wallpaper)
                onContentXChanged: if(root.active)pagination.restart()
                WheelScroll {view:rail;orientation:Qt.Horizontal;verticalToHorizontal:true;wheelStep:360}
                ScrollBar.horizontal: MovieScrollBar {}
            }
            MovieText {
                objectName: "picturesProviderLoading"
                anchors.centerIn: parent
                visible: root.loading && !root.selected.id
                text: qsTr("Loading %1…").arg(root.providerName(root.providerId))
                color: MovieStyle.muted
            }
            MovieText {
                anchors.centerIn: parent; width: Math.min(600,parent.width)
                horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: MovieStyle.muted
                visible: !root.selected.id && !root.loading && !root.error
                text: root.favoritesView ? qsTr("No saved wallpapers yet.") : root.providerId==="wallpaper_engine" ? qsTr("No wallpapers found. Choose Workshop or subscribe in Steam, then refresh.") : qsTr("No matching wallpapers.")
            }
        }
        Item { Layout.fillWidth: true; Layout.preferredHeight: 42 }
    }
}
