import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"
import "../movies"
import "../radio" as RadioUi
import "../movies/Catalogue.js" as Models

Item {
    id: root
    objectName: "televisionBrowser"
    property var host
    property bool active: false
    property var toolbarTarget: null
    property var backdropTarget: null
    property real toolbarHeight: 46
    property var initialFocus: searchOpen ? search : channelList
    property bool initialized: false
    property bool loading: false
    property bool refreshing: false
    property bool needsBrowse: false
    property bool needsRefresh: false
    property bool saving: false
    property bool commandPending: false
    property bool statusPending: false
    property bool searchOpen: false
    property bool filtersOpen: false
    property string country: ""
    property string language: ""
    property string category: ""
    property var streamChoices: ({})
    property var favorites: []
    property var channels: []
    property var filters: ({countries:[],languages:[],categories:[]})
    property var playback: ({playing:false,paused:false,channelId:"",streamId:""})
    property int total: 0
    property int nextOffset: -1
    property int browseGeneration: 0
    property int commandGeneration: 0
    property string error: ""
    property string saveError: ""
    property string playbackError: ""
    property string notice: ""
    readonly property bool busy: loading || refreshing || saving || commandPending

    Worker {
        id: service; objectName: "televisionService"
        backendDirectory: "spaces/television"; backend: "backend.py"
        serviceName: "Television"; spaceId: "television"
        onFailed: message => root.error = message
    }
    ListModel { id: channelModel }
    Rectangle {
        objectName: "televisionBackground"
        parent: root.backdropTarget || root
        anchors.fill: parent; z: root.backdropTarget ? 0 : -1
        color: "#000000"; visible: root.active
    }
    function activate() { if (active) initialFocus.forceActiveFocus(); }
    function isFavorite(channel) { return favorites.some(item => item.id === channel.id); }
    function applySummary(result) { filters = result.filters || ({countries:[],languages:[],categories:[]}); }
    function initialize() {
        loading = true; error = "";
        service.request("init", {}, (result, failure) => {
            loading = false;
            if (failure) { error = failure; return; }
            country = result.settings.country || ""; language = result.settings.language || "";
            category = result.settings.category || ""; streamChoices = result.settings.streams || ({});
            favorites = result.favorites || []; applySummary(result);
            initialized = true; needsRefresh = !!result.stale;
            browse(false);
            if (active && needsRefresh) refresh();
        });
    }
    function persist() {
        if (!initialized) return;
        service.request("settings-save", {settings:{country:country,language:language,category:category,streams:streamChoices}}, (result, failure) => { saveError = failure || ""; });
    }
    function browse(append) {
        if (!initialized) return;
        if (!active) { needsBrowse = true; return; }
        if (append && (loading || nextOffset < 0)) return;
        needsBrowse = false; searchDelay.stop();
        const generation = ++browseGeneration;
        const offset = append ? nextOffset : 0;
        loading = true;
        service.request("browse", {query:search.text.trim(),country:country,language:language,category:category,offset:offset}, (result, failure) => {
            if (generation !== browseGeneration) return;
            loading = false;
            if (failure) { error = failure; return; }
            channels = Models.update(channelModel, channels, result.items || [], append);
            total = result.total || 0; nextOffset = result.nextOffset >= 0 ? result.nextOffset : -1;
            if (!append) { channelList.currentIndex = channels.length ? 0 : -1; channelList.positionViewAtBeginning(); }
        });
    }
    function refresh() {
        if (!initialized || refreshing) return;
        if (!active) { needsRefresh = true; return; }
        needsRefresh = false; refreshing = true; error = ""; notice = "";
        service.request("refresh", {}, (result, failure) => {
            refreshing = false;
            if (failure) { error = failure; return; }
            applySummary(result); notice = result.warning || ""; browse(false);
        });
    }
    function scheduleBrowse() { if (initialized) { if (active) searchDelay.restart(); else needsBrowse = true; } }
    function maybeLoadMore() {
        if (active && !loading && nextOffset >= 0 && channelList.contentY + channelList.height >= channelList.contentHeight - 240) browse(true);
    }
    function toggleFavorite(channel) {
        if (saving) return;
        saving = true;
        service.request("favorite", {channel:channel,value:!isFavorite(channel)}, (result, failure) => {
            saving = false; saveError = failure || "";
            if (!failure) { favorites = result; browse(false); }
        });
    }
    function streamIndex(channel) {
        const index = (channel.streams || []).findIndex(item => item.id === streamChoices[channel.id]);
        return Math.max(0, index);
    }
    function streamLabel(stream, index) {
        return ["Stream " + (index + 1), stream.quality, stream.feed, ...(stream.labels || [])].filter(Boolean).join(" · ");
    }
    function chooseStream(channel, index) {
        const stream = channel.streams[index]; if (!stream) return;
        streamChoices = Object.assign({}, streamChoices, {[channel.id]:stream.id}); persist();
        if (playback.playing && playback.channelId === channel.id) play(channel);
    }
    function play(channel) {
        const stream = channel?.streams[streamIndex(channel)]; if (!stream) return;
        const generation = ++commandGeneration;
        commandPending = true; playbackError = "";
        service.request("play", {channelId:channel.id,streamId:stream.id}, (result, failure) => {
            if (generation !== commandGeneration) return;
            commandPending = false;
            if (failure) { playbackError = failure; return; }
            playback = result;
            if (active && result.playing && host) host.hide();
        });
    }
    function playerCommand(op) {
        const generation = ++commandGeneration;
        commandPending = true; playbackError = "";
        service.request(op, {}, (result, failure) => {
            if (generation !== commandGeneration) return;
            commandPending = false;
            if (failure) playbackError = failure;
            else { playback = result; playbackError = result.error || ""; }
        });
    }
    function refreshStatus() {
        if (!active || statusPending || commandPending) return;
        const generation = commandGeneration; statusPending = true;
        service.request("status", {}, (result, failure) => {
            statusPending = false;
            if (generation !== commandGeneration) return;
            if (failure) playbackError = failure;
            else { playback = result; if (result.error) playbackError = result.error; }
        });
    }
    function menuOffset(button, width) {
        const target = toolbarTarget || root, x = button.mapToItem(target, 0, 0).x;
        return Math.max(-x, Math.min(0, target.width - x - width));
    }
    function chooseFilter(kind, name) {
        const options = filters[kind] || [];
        const item = options.find(value => value.name === name);
        if (kind === "countries") country = item?.code || "";
        else if (kind === "languages") language = item?.code || "";
        else category = item?.code || "";
        persist(); browse(false);
    }
    function label(kind, code, fallback) { return (filters[kind] || []).find(item => item.code === code)?.name || code || fallback; }
    function closeMenus() {
        countryMenu.close(); languageMenu.close(); categoryMenu.close();
        for (const child of channelList.contentItem.children) if (child.closeMenu) child.closeMenu();
    }
    function dismissTransient() {
        if (countryMenu.visible || languageMenu.visible || categoryMenu.visible) { closeMenus(); return true; }
        for (const child of channelList.contentItem.children) if (child.closeMenu && child.closeMenu()) return true;
        if (filtersOpen) { filtersOpen = false; return true; }
        if (search.text.length) { search.clear(); return true; }
        if (searchOpen) { searchOpen = false; return true; }
        return false;
    }
    onActiveChanged: {
        if (!active) {
            if (searchDelay.running) needsBrowse = true;
            searchDelay.stop(); pagination.stop(); closeMenus();
        } else if (initialized) {
            if (needsBrowse) browse(false);
            if (needsRefresh) refresh();
            refreshStatus(); Qt.callLater(activate);
        }
    }
    Component.onCompleted: initialize()
    Timer { id: searchDelay; interval: 300; onTriggered: root.browse(false) }
    Timer { id: pagination; interval: 120; onTriggered: root.maybeLoadMore() }
    Timer { objectName: "televisionStatusTimer"; interval: 2000; repeat: true; running: root.active && root.playback.playing; onTriggered: root.refreshStatus() }

    RowLayout {
        objectName: "televisionToolbar"; parent: root.toolbarTarget || root
        width: parent.width; height: root.toolbarHeight; visible: root.active; spacing: 8
        MovieText { objectName: "televisionChannelHeading"; text: "Channels"; font.bold: true }
        MovieText { objectName: "televisionChannelCount"; text: root.total.toLocaleString(); color: MovieStyle.muted }
        Item { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0 }
        Flickable {
            id: inlineFilters; visible: root.filtersOpen
            Layout.fillWidth: true; Layout.preferredWidth: fields.implicitWidth; Layout.minimumWidth: 110
            Layout.maximumWidth: fields.implicitWidth; Layout.preferredHeight: 46
            clip: true; contentWidth: fields.implicitWidth; contentHeight: height; flickableDirection: Flickable.HorizontalFlick
            WheelScroll { view: inlineFilters; orientation: Qt.Horizontal; verticalToHorizontal: true }
            ScrollBar.horizontal: MovieScrollBar {}
            Row {
                id: fields; spacing: 8
                MovieButton {
                    id: countryButton; objectName: "televisionCountry"; width: 180
                    text: root.label("countries", root.country, "All countries"); iconName: "map-pin"
                    onClicked: countryMenu.visible ? countryMenu.close() : countryMenu.open()
                    RadioUi.FilterMenu {
                        id: countryMenu; y: countryButton.height + 4; width: Math.min(320, root.width); height: Math.min(420, root.height)
                        x: root.menuOffset(countryButton, width); placeholder: "Search countries…"
                        options: [{name:"All countries",code:""}].concat(root.filters.countries || []); selectedNames: [countryButton.text]
                        onChosen: name => { root.chooseFilter("countries", name); close(); }
                    }
                }
                MovieButton {
                    id: languageButton; width: 155; text: root.label("languages", root.language, "All languages"); iconName: "languages"
                    onClicked: languageMenu.visible ? languageMenu.close() : languageMenu.open()
                    RadioUi.FilterMenu {
                        id: languageMenu; y: languageButton.height + 4; width: Math.min(320, root.width); height: Math.min(420, root.height)
                        x: root.menuOffset(languageButton, width); placeholder: "Search languages…"
                        options: [{name:"All languages",code:""}].concat(root.filters.languages || []); selectedNames: [languageButton.text]
                        onChosen: name => { root.chooseFilter("languages", name); close(); }
                    }
                }
                MovieButton {
                    id: categoryButton; width: 155; text: root.label("categories", root.category, "All categories"); iconName: "list"
                    onClicked: categoryMenu.visible ? categoryMenu.close() : categoryMenu.open()
                    RadioUi.FilterMenu {
                        id: categoryMenu; y: categoryButton.height + 4; width: Math.min(320, root.width); height: Math.min(420, root.height)
                        x: root.menuOffset(categoryButton, width); placeholder: "Search categories…"
                        options: [{name:"All categories",code:""}].concat(root.filters.categories || []); selectedNames: [categoryButton.text]
                        onChosen: name => { root.chooseFilter("categories", name); close(); }
                    }
                }
                MovieButton { text: "Reset"; onClicked: { root.country = ""; root.language = ""; root.category = ""; root.persist(); root.browse(false); } }
            }
        }
        MovieInput {
            id: search; objectName: "televisionSearch"; visible: root.searchOpen; rightPadding: 40
            Layout.preferredWidth: Math.min(300, root.width * 0.25); Layout.minimumWidth: 100
            placeholderText: "Search channels…"; Accessible.name: "Search television channels"
            onTextChanged: root.scheduleBrowse(); onAccepted: root.browse(false)
            MovieIconButton { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 36; height: 36; visible: !!search.text; iconName: "x"; text: "Clear channel search"; onClicked: { search.clear(); search.forceActiveFocus(); } }
        }
        Item { Layout.minimumWidth: 28; Layout.maximumWidth: 28; Layout.preferredHeight: 28
            MovieSpinner { objectName: "televisionLoadingIndicator"; anchors.fill: parent; running: root.active && root.busy; visible: running }
        }
        MovieIconButton { objectName: "televisionPause"; visible: root.playback.playing; enabled: !root.commandPending; iconName: root.playback.paused ? "play" : "pause"; text: root.playback.paused ? "Resume Television" : "Pause Television"; onClicked: root.playerCommand("pause") }
        MovieIconButton { objectName: "televisionStop"; visible: root.playback.playing || root.commandPending; iconName: "square"; text: "Stop Television"; onClicked: root.playerCommand("stop") }
        MovieIconButton { objectName: "televisionSearchButton"; highlighted: root.searchOpen; iconName: "search"; text: "Search channels"; onClicked: { root.searchOpen = !root.searchOpen; if (root.searchOpen) search.forceActiveFocus(); else search.clear(); } }
        MovieIconButton { objectName: "televisionFiltersButton"; highlighted: root.filtersOpen || !!root.country || !!root.language || !!root.category; iconName: "sliders-horizontal"; text: "Channel filters"; onClicked: root.filtersOpen = !root.filtersOpen }
        MovieIconButton { objectName: "televisionRefresh"; iconName: "refresh-cw"; text: "Refresh channel directory"; enabled: !root.refreshing; onClicked: root.initialized ? root.refresh() : root.initialize() }
    }

    ColumnLayout {
        anchors.fill: parent; spacing: 12
        RowLayout {
            visible: !!root.error || !!root.saveError || !!root.playbackError || !!root.notice; Layout.fillWidth: true
            MovieText { Layout.fillWidth: true; wrapMode: Text.Wrap; text: [root.error,root.saveError,root.playbackError,root.notice].filter(Boolean).join("\n"); color: root.error || root.saveError || root.playbackError ? MovieStyle.danger : MovieStyle.muted }
            MovieButton { text: "Retry"; visible: !!root.error; enabled: !root.refreshing; onClicked: root.initialized ? root.refresh() : root.initialize() }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: MovieStyle.border }
        Item {
            Layout.fillWidth: true; Layout.fillHeight: true
            ListView {
                id: channelList; objectName: "televisionChannelList"; anchors.fill: parent
                clip: true; spacing: 2; model: channelModel; activeFocusOnTab: true; keyNavigationEnabled: true; keyNavigationWraps: false
                onContentYChanged: if (root.active) pagination.restart()
                Keys.onReturnPressed: if (currentItem) root.play(currentItem.channel)
                Keys.onEnterPressed: if (currentItem) root.play(currentItem.channel)
                Keys.onSpacePressed: if (root.playback.playing) root.playerCommand("pause"); else if (currentItem) root.play(currentItem.channel)
                delegate: Rectangle {
                    id: row
                    required property string payload
                    required property int index
                    readonly property var channel: JSON.parse(payload)
                    readonly property bool playing: root.playback.playing && root.playback.channelId === channel.id
                    width: channelList.width; height: Math.max(78, info.implicitHeight + 24); radius: 6
                    color: playing ? MovieStyle.accentSurface : hover.containsMouse ? "#18ffffff" : "transparent"
                    border.width: channelList.activeFocus && channelList.currentIndex === index ? 1 : 0; border.color: MovieStyle.accent
                    function closeMenu() { if (quality.popup.visible) { quality.popup.close(); return true; } return false; }
                    MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; onClicked: { channelList.currentIndex = row.index; channelList.forceActiveFocus(); } onDoubleClicked: root.play(row.channel) }
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 12; spacing: 12
                        MovieIconButton { objectName: "televisionPlay:" + row.index; iconName: "play"; text: "Watch " + row.channel.name; onClicked: { channelList.currentIndex = row.index; root.play(row.channel); } }
                        ColumnLayout {
                            id: info; Layout.fillWidth: true; spacing: 5
                            MovieText { Layout.fillWidth: true; text: row.channel.name; font.bold: true; font.pixelSize: MovieStyle.fontSize * 1.2; elide: Text.ElideRight }
                            MovieText { Layout.fillWidth: true; color: MovieStyle.muted; elide: Text.ElideRight; text: [row.channel.countryName,(row.channel.languageNames || []).join(" / "),(row.channel.categoryNames || []).join(" · ")].filter(Boolean).join("   /   ") }
                        }
                        MovieChoice {
                            id: quality; objectName: "televisionStream:" + row.index; Layout.preferredWidth: Math.min(270, root.width * 0.24)
                            model: (row.channel.streams || []).map(root.streamLabel); currentIndex: root.streamIndex(row.channel)
                            Accessible.name: "Stream and quality for " + row.channel.name
                            onActivated: index => root.chooseStream(row.channel, index)
                        }
                        Item {
                            visible: root.width > 700; implicitWidth: MovieStyle.controlHeight; implicitHeight: MovieStyle.controlHeight
                            MovieIconButton { anchors.fill: parent; visible: !!row.channel.website; iconName: "globe"; text: "Channel website"; onClicked: Browser.open(row.channel.website, "television", "", root.host) }
                        }
                        MovieIconButton { objectName: "televisionFavorite:" + row.index; enabled: !root.saving; highlighted: root.isFavorite(row.channel); iconName: highlighted ? "star-filled" : "star"; text: highlighted ? "Remove favorite " + row.channel.name : "Favorite " + row.channel.name; onClicked: root.toggleFavorite(row.channel) }
                    }
                }
                WheelScroll { view: channelList; wheelStep: 330 }
                ScrollBar.vertical: MovieScrollBar {}
                footer: MovieButton { visible: root.nextOffset >= 0; enabled: !root.loading; text: root.loading ? "Loading channels…" : "Load more channels"; onClicked: root.browse(true) }
            }
            MovieText {
                anchors.centerIn: parent; width: Math.min(480, parent.width - 40); horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                visible: !root.channels.length; color: MovieStyle.muted
                text: root.loading || root.refreshing ? "Loading channels…" : root.error ? "" : "No channels match these filters."
            }
        }
    }
}
