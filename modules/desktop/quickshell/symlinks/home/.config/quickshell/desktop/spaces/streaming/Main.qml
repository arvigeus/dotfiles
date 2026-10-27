import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../../ui" as Desktop
import "../movies"
import "../movies/Catalogue.js" as Models

Item {
    id: root
    objectName: "streamingBrowser"
    property var host
    property var notify: argv => Quickshell.execDetached(argv)
    property bool active: false
    property var toolbarTarget: null
    property var backdropTarget: null
    property real toolbarHeight: 46
    property var initialFocus: searchOpen ? search : tab === "posts" ? postsView : gridMode ? grid : rail
    property bool initialized: false
    property bool initializing: false
    property bool loading: false
    property bool detailLoading: false
    property bool commandPending: false
    property bool jobPolling: false
    property bool statusPolling: false
    property bool jobsActive: false
    property bool gemini: false
    property bool gridMode: false
    property bool searchOpen: false
    property bool playOpening: false
    property bool updatingCatalogue: false
    property string tab: "feed"
    property string channel: ""
    property string error: ""
    property string detailError: ""
    property string detailTab: "overview"
    property string notice: ""
    property int page: 0
    property bool more: false
    property var pageKeys: []
    property var pendingViewRestore: null
    property int browseGeneration: 0
    property int detailGeneration: 0
    property var videos: []
    property var posts: []
    property var tabViews: ({})
    property var selected: null
    property var channels: []
    property var jobs: []
    property var finishedJobs: ({})
    property var playback: ({playing:false})
    property string answer: ""
    property string answeredQuestion: ""
    property bool channelsOpen: false
    property bool jobsOpen: false
    readonly property bool narrow: width < 900

    Worker {
        id: service; objectName: "streamingService"
        backendDirectory: "spaces/streaming"; backend: "backend.py"
        spaceId: "streaming"; serviceName: "Streaming"
        onFailed: message => root.error = message
    }
    ListModel { id: videoModel }
    ListModel { id: postModel }
    MovieBackdrop {
        objectName: "streamingBackdrop"
        parent: root.backdropTarget || root
        anchors.fill: parent; z: root.backdropTarget ? 0 : -1
        visible: root.active && root.tab !== "posts"; gridMode: root.gridMode
        ownerKey: root.selected?.id || ""
        source: root.active && root.tab !== "posts" && root.selected ? root.selected.backdrop || "https://i.ytimg.com/vi/" + root.selected.id + "/sd2.jpg" : ""
        poster: root.active && root.tab !== "posts" ? root.selected?.thumbnail || "" : ""
        readingEdge: Math.min(0.75, (16 + Math.min(root.width * 0.7, 1000)) / Math.max(1, root.width))
    }
    function settings(result) { channels = result.channels || []; gridMode = !!result.grid_mode; }
    function toggleLayout() {
        gridMode = !gridMode;
        service.request("layout", {grid_mode:gridMode}, (result, failure) => { if (failure) error = failure; });
    }
    function openYouTube() { if (selected?.id) Desktop.Apps.launch(["xdg-open", "https://www.youtube.com/watch?v=" + selected.id]); }
    function openPost(id) { if (/^Ug[A-Za-z0-9_-]{10,100}$/.test(id)) Desktop.Apps.launch(["xdg-open", "https://www.youtube.com/post/" + id]); }
    function followedChannel(video) {
        return channels.find(channel => channel.url === video.followedChannelUrl
                             || (video.channelId && channel.id === video.channelId)
                             || channel.url.toLowerCase() === String(video.channel || "").toLowerCase()
                             || channel.url.toLowerCase() === String(video.channelHandle || "").toLowerCase()
                             || (channel.aliases || []).includes(video.channel)) || null;
    }
    function toggleSubscription(video) {
        const followed = followedChannel(video);
        command(followed ? "unsubscribe" : "subscribe", followed ? {url:followed.url} : {url:video.channel,channelId:video.channelId || "",name:video.creator || ""}, result => {
            settings(result);
            if (followed && channel === followed.url) channel = "";
            if (tab === "posts" || (tab === "feed" && !search.text.trim())) browse(false);
        });
    }
    function isMemberVideo(video) { return ["subscriber_only", "premium_only"].includes(video.availability); }
    function schedulePagination() { if (active && initialized) pagination.restart(); }
    function maybeLoadMore() {
        if (!active || !initialized || loading || error || !more || searchDelay.running || channelsOpen || jobsOpen) return;
        const view = tab === "posts" ? postsView : gridMode ? grid : rail;
        if (!view.visible || view.width <= 0 || view.height <= 0) return;
        const horizontal = tab !== "posts" && !gridMode;
        const viewport = horizontal ? view.width : view.height;
        const extent = horizontal ? view.contentWidth : view.contentHeight;
        const position = horizontal ? view.contentX - view.originX : view.contentY - view.originY;
        const margin = tab === "posts" ? Math.max(300, viewport * 0.5) : gridMode ? grid.cellHeight * 2 : viewport * 0.5;
        if (position + viewport >= extent - margin) browse(true);
    }
    onGridModeChanged: schedulePagination()
    onWidthChanged: schedulePagination()
    onHeightChanged: schedulePagination()
    onChannelsOpenChanged: if (!channelsOpen) schedulePagination()
    onJobsOpenChanged: if (!jobsOpen) schedulePagination()
    function initialize() {
        if (initializing) return;
        initializing = true;
        service.request("init", {}, (result, failure) => {
            initializing = false;
            if (failure) { error = failure; return; }
            settings(result.settings); gemini = result.gemini;
            initialized = true; if (active) browse(false);
        });
    }
    function browse(append, refresh) {
        if (!initialized || !active || (append && (loading || !more))) return;
        const generation = ++browseGeneration;
        pagination.stop();
        const next = append ? page + 1 : 0;
        loading = true; error = ""; notice = "";
        const target = tab === "feed" && search.text.trim() ? "search" : tab;
        service.request("browse", {tab:target, query:search.text, channel:channel, page:next, refresh:!!refresh}, (result, failure) => {
            if (generation !== browseGeneration) return;
            loading = false;
            if (failure) { error = failure; return; }
            if (result.channels) channels = result.channels;
            page = next; more = !!result.more; notice = result.warning || "";
            const key = result.pageKey || JSON.stringify((result.items || []).map(item => item.id).sort());
            if (!append) pageKeys = [key];
            else if (pageKeys.includes(key)) more = false;
            else pageKeys = pageKeys.concat([key]);
            if (tab === "posts") {
                posts = Models.update(postModel, posts, result.items || [], append);
                if (!append) postsView.positionViewAtBeginning();
                schedulePagination();
                return;
            }
            updatingCatalogue = true;
            videos = Models.update(videoModel, videos, (result.items || []).filter(item => !isMemberVideo(item)), append);
            updatingCatalogue = false;
            if (!append) {
                grid.positionViewAtBeginning(); rail.positionViewAtBeginning();
                if (!videos.length) { selected = null; detailGeneration++; detailLoading = false; }
                else if (!videos.some(video => video.id === selected?.id)) select(videos[0]);
            }
            schedulePagination();
        });
    }
    function switchTab(value) {
        if (tab === value || !["feed", "posts"].includes(value)) return;
        tabViews[tab] = {query:search.text, videos:videos, page:page, more:more, scroll:grid.contentY, railScroll:rail.contentX,
                         selected:selected, answer:answer, answeredQuestion:answeredQuestion, detailTab:detailTab,posts:posts,postsScroll:postsView.contentY,pageKeys:pageKeys};
        browseGeneration++; detailGeneration++; loading = detailLoading = false;
        pagination.stop(); error = "";
        restoreView.stop(); pendingViewRestore = null;
        tab = value;
        const view = tabViews[value];
        search.text = view?.query || ""; page = view?.page || 0; more = !!view?.more;
        pageKeys = view?.pageKeys || [];
        searchOpen = !!search.text;
        videos = Models.update(videoModel, videos, view?.videos || [], false, item => item.id + (item.localPath ? (item.audio ? ":audio" : ":video") : ""));
        selected = view?.selected || null; answer = view?.answer || ""; answeredQuestion = view?.answeredQuestion || "";
        detailTab = view?.detailTab || "overview"; detailError = "";
        posts = Models.update(postModel, posts, view?.posts || [], false);
        if (value === "posts") { selected = null; detailGeneration++; detailLoading = false; }
        if (!view) browse(false);
        else { pendingViewRestore = view; restoreView.restart(); }
    }
    function select(video) {
        const generation = ++detailGeneration;
        selected = video; answer = ""; answeredQuestion = ""; details.resetQuestion(); detailLoading = true;
        detailError = ""; detailTab = "overview";
        service.request("details", {videoId:video.id}, (result, failure) => {
            if (generation !== detailGeneration) return;
            detailLoading = false;
            if (failure) { detailError = failure; return; }
            if (isMemberVideo(result)) {
                videos = Models.update(videoModel, videos, videos.filter(item => item.id !== result.id), false);
                selected = null;
                if (videos.length) select(videos[0]);
                schedulePagination();
                return;
            }
            selected = Object.assign({}, video, result);
            updatingCatalogue = true;
            videos = Models.update(videoModel, videos, videos.map(item => item.id === result.id ? Object.assign({}, item, result) : item), false,
                                   item => item.id + (item.localPath ? (item.audio ? ":audio" : ":video") : ""));
            updatingCatalogue = false;
        });
    }
    function command(op, args, callback) {
        if (commandPending) return;
        commandPending = true; error = "";
        service.request(op, args, (result, failure) => {
            commandPending = false;
            if (failure) {
                if (op === "play") { detailError = failure; playOpening = false; }
                else error = failure;
                return;
            }
            if (callback) callback(result);
        });
    }
    function play(audio, start) {
        if (!selected) return;
        audio = audio || !!selected.audio;
        const args = {videoId:selected.id, audio:audio};
        if (start !== undefined) args.start = start;
        detailError = "";
        command("play", args, result => { playback = result; playOpening = !audio; status(); });
    }
    function startJob(op, args) {
        command(op, args, result => {
            jobs = jobs.concat([{job_id:result.job_id, state:"queued", title:op === "analyze" ? "Analyze video" : args.audio ? "Download audio" : "Download video", detail:"Queued", done:0, total:0}]);
            jobsActive = true; pollJobs();
        });
    }
    function pollJobs() {
        if (jobPolling) return;
        jobPolling = true;
        service.request("jobs", {}, (result, failure) => {
            jobPolling = false;
            if (failure) { error = failure; jobsActive = false; return; }
            jobs = result.jobs || [];
            jobsActive = jobs.some(job => job.state === "queued" || job.state === "running");
            for (const job of jobs) {
                if (["queued", "running"].includes(job.state) || finishedJobs[job.job_id]) continue;
                finishedJobs[job.job_id] = true;
                if (job.state === "finished") {
                    const value = job.result || {};
                    if (value.kind === "analysis" && selected?.id === value.videoId) {
                        answer = value.text; answeredQuestion = value.question || "Summary"; detailTab = "summary";
                    }
                    if (value.kind === "download") {
                        notice = value.audio ? "Saved to Music. Review and upload it in My Library." : "Video saved to Videos/Streaming.";
                    }
                } else if (job.state === "failed") error = job.error || "The operation failed.";
                if (job.state !== "cancelled")
                    root.notify(["notify-send", "-a", "Streaming", job.state === "finished" ? job.title + " complete" : job.title + " failed", job.state === "finished" ? job.result?.path || "Your video analysis is ready." : job.error || "Try again."]);
            }
        });
    }
    function status() {
        if (statusPolling) return;
        statusPolling = true;
        service.request("status", {}, (result, failure) => {
            statusPolling = false;
            if (failure) { error = failure; return; }
            const title = playback.title || "Streaming";
            playback = Object.assign({title:title}, result);
            if (result.error) { detailError = result.error; playOpening = false; }
            else if (playOpening && result.playing && !result.connecting) { playOpening = false; root.host?.hide(); }
            else if (!result.playing) playOpening = false;
        });
    }
    function subscribe(url) {
        command("subscribe", {url:url}, result => { settings(result); channelInput.clear(); if (tab === "posts" || tab === "feed") browse(false); });
    }
    function dismissTransient() {
        if (channelsOpen || jobsOpen) { channelsOpen = jobsOpen = false; return true; }
        if (detailTab !== "overview") { detailTab = "overview"; return true; }
        if (search.text) { search.clear(); browse(false); return true; }
        if (searchOpen) { searchOpen = false; return true; }
        return false;
    }
    function handleOpen(payload) {
        if (payload?.url) { if (tab !== "feed") switchTab("feed"); search.text = payload.url; searchOpen = true; if (initialized && active) browse(false); }
    }
    onActiveChanged: {
        if (!active) { channelsOpen = jobsOpen = false; searchDelay.stop(); pagination.stop(); }
        else if (initialized) { if (tab === "posts" ? !posts.length : !videos.length) browse(false); status(); schedulePagination(); }
    }
    Component.onCompleted: initialize()
    Timer { id: searchDelay; interval: 350; onTriggered: root.browse(false) }
    Timer { id: pagination; interval: 120; onTriggered: root.maybeLoadMore() }
    Timer {
        id: restoreView; interval: 0
        onTriggered: {
            const view = root.pendingViewRestore;
            root.pendingViewRestore = null;
            if (!view) return;
            grid.contentY = view.scroll; rail.contentX = view.railScroll || 0; postsView.contentY = view.postsScroll || 0;
            root.schedulePagination();
        }
    }
    Timer { interval: 700; repeat: true; running: root.jobsActive; onTriggered: root.pollJobs() }
    Timer { interval: root.playOpening ? 350 : 2000; repeat: true; running: (root.active || root.playOpening) && root.playback.playing; onTriggered: root.status() }

    RowLayout {
        objectName: "streamingToolbar"
        parent: root.toolbarTarget || root
        width: parent.width; height: root.toolbarHeight; visible: root.active; spacing: 8
        Flickable {
            id: collectionTabs
            Layout.fillWidth: true; Layout.preferredHeight: 44
            contentWidth: tabs.implicitWidth; contentHeight: height; clip: true
            Desktop.WheelScroll { view: collectionTabs; orientation: Qt.Horizontal; verticalToHorizontal: true }
            Row {
                id: tabs; spacing: 4
                Repeater {
                    model: [{id:"feed",name:"Discover",icon:"globe"},{id:"posts",name:"Posts",icon:"file-text"}]
                    MovieTab {
                        required property var modelData
                        objectName: "streamingTab:" + modelData.id
                        text: modelData.name; iconName: modelData.icon; highlighted: root.tab === modelData.id
                        onClicked: root.switchTab(modelData.id)
                    }
                }
            }
        }
        MovieInput {
            id: search; objectName: "streamingSearch"; visible: root.searchOpen
            Layout.preferredWidth: Math.min(320, root.width * 0.3); Layout.minimumWidth: 90
            placeholderText: root.tab === "feed" ? "Search YouTube or paste a URL" : root.tab === "posts" ? "Search posts" : "Filter videos"
            onAccepted: root.browse(false)
            onTextEdited: searchDelay.restart()
        }
        Item {
            Layout.preferredWidth: 28; Layout.preferredHeight: 28
            ActivityIndicator {
                anchors.fill: parent; active: root.active
                jobs: root.jobs
                tasks: [
                    task(root.initializing, "init", "Opening Streaming…"),
                    task(root.loading, "browse", root.tab === "posts" ? "Loading posts…" : "Loading videos…"),
                    task(root.detailLoading, "details", "Loading video details…"),
                    task(root.commandPending, "command", "Updating Streaming…"),
                    task(root.playOpening, "player", "Opening player…")
                ]
            }
        }
        MovieIconButton { iconName: "search"; text: "Search videos"; highlighted: root.searchOpen; onClicked: { root.searchOpen = !root.searchOpen; if (root.searchOpen) search.forceActiveFocus(); } }
        MovieIconButton { iconName: "refresh-cw"; text: "Refresh"; enabled: root.initialized && !root.loading; onClicked: root.browse(false, true) }
        MovieIconButton { objectName: "streamingLayoutToggle"; visible: root.tab !== "posts"; iconName: root.gridMode ? "panels-top-left" : "layout-grid"; text: root.gridMode ? "Show video rail" : "Show grid"; onClicked: root.toggleLayout() }
        MovieIconButton { objectName: "streamingChannels"; iconName: "video"; text: "Follow channels"; onClicked: { root.channelsOpen = !root.channelsOpen; root.jobsOpen = false; } }
        MovieIconButton { objectName: "streamingJobs"; iconName: "bell"; text: root.jobsActive ? "Operations in progress" : "Operations"; highlighted: root.jobsActive; onClicked: { root.jobsOpen = !root.jobsOpen; root.channelsOpen = false; root.pollJobs(); } }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.topMargin: root.toolbarTarget ? 0 : root.toolbarHeight + 12
        spacing: 12
        MovieText { objectName: "streamingError"; Layout.fillWidth: true; visible: !!text; text: root.error; color: MovieStyle.danger; wrapMode: Text.Wrap }
        Item {
            id: catalogueArea; Layout.fillWidth: true; Layout.fillHeight: true
            readonly property real railHeight: Math.min(250, height * 0.36)
            PostsFeed { id: postsView; anchors.fill: parent; controller: root; visible: root.tab === "posts"; model: root.tab === "posts" ? postModel : null; onPaginationCheckRequested: root.schedulePagination() }
            GridView {
                id: grid; objectName: "streamingGrid"
                visible: root.tab !== "posts" && root.gridMode; clip: true; model: root.tab !== "posts" ? videoModel : null
                width: root.narrow ? parent.width : parent.width * 0.51
                height: root.narrow && root.selected ? parent.height * 0.45 : parent.height
                cellWidth: width / Math.max(1, Math.floor(width / 280))
                cellHeight: cellWidth * 9 / 16 + 90
                keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: VideoCard {
                    required property string payload
                    required property int index
                    video: JSON.parse(payload); width: grid.cellWidth - 8; height: grid.cellHeight - 8
                    selected: root.selected?.id === video.id
                    onClicked: { grid.forceActiveFocus(); grid.currentIndex = index; root.select(video); }
                }
                onCurrentItemChanged: if (!root.updatingCatalogue && activeFocus && currentItem && currentItem.video.id !== root.selected?.id) root.select(currentItem.video)
                onContentYChanged: root.schedulePagination()
                onContentHeightChanged: root.schedulePagination()
                Desktop.WheelScroll { view: grid; wheelStep: Math.max(360, grid.cellHeight * 1.25) }
                ScrollBar.vertical: MovieScrollBar {}
            }
            StreamingDetails {
                id: details; objectName: "streamingDetails"; controller: root
                visible: root.tab !== "posts" && !!root.selected
                x: root.gridMode && !root.narrow ? parent.width * 0.55 : 16
                y: root.gridMode && root.narrow ? parent.height * 0.49 : 0
                width: root.gridMode ? root.narrow ? parent.width - 32 : parent.width * 0.45 : Math.min(parent.width * 0.7, 1000)
                height: root.gridMode ? root.narrow ? parent.height * 0.51 : parent.height : parent.height - catalogueArea.railHeight - 20
            }
            ListView {
                id: rail; objectName: "streamingRail"
                anchors.bottom: parent.bottom; width: parent.width; height: catalogueArea.railHeight
                visible: root.tab !== "posts" && !root.gridMode; clip: true; model: root.tab !== "posts" ? videoModel : null
                orientation: ListView.Horizontal; spacing: 12
                keyNavigationEnabled: true; keyNavigationWraps: false
                delegate: VideoCard {
                    required property string payload
                    required property int index
                    video: JSON.parse(payload); width: Math.max(160, (rail.height - 96) * 16 / 9); height: rail.height
                    selected: root.selected?.id === video.id
                    onClicked: { rail.forceActiveFocus(); rail.currentIndex = index; root.select(video); }
                }
                onCurrentItemChanged: if (!root.updatingCatalogue && activeFocus && currentItem && currentItem.video.id !== root.selected?.id) root.select(currentItem.video)
                onContentXChanged: root.schedulePagination()
                onContentWidthChanged: root.schedulePagination()
                Desktop.WheelScroll { view: rail; orientation: Qt.Horizontal; verticalToHorizontal: true; wheelStep: 360 }
                ScrollBar.horizontal: MovieScrollBar {}
            }
            MovieText {
                anchors.centerIn: parent; width: Math.min(parent.width - 32, 600)
                visible: root.tab !== "posts" && !root.loading && !root.videos.length && !root.selected
                horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; color: MovieStyle.muted
                text: search.text.trim() || root.channels.length ? "No public videos found. Try another search or refresh the feed." : "Follow your favorite channels to build your feed.\nSearch YouTube to find something to watch."
            }
            Rectangle {
                objectName: "streamingChannelsPanel"; visible: root.channelsOpen
                anchors.fill: parent; color: MovieStyle.surface; radius: 12; z: 5
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 20; spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        MovieText { Layout.fillWidth: true; text: "Following"; font.pixelSize: 24; font.bold: true }
                        MovieIconButton { iconName: "x"; text: "Close channels"; onClicked: root.channelsOpen = false }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        MovieInput { id: channelInput; objectName: "streamingChannelInput"; Layout.fillWidth: true; placeholderText: "YouTube channel URL or @handle"; onAccepted: if (text.trim()) root.subscribe(text) }
                        MovieButton { text: "Follow"; enabled: !!channelInput.text.trim() && !root.commandPending; onClicked: root.subscribe(channelInput.text) }
                    }
                    ListView {
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: root.channels; spacing: 8
                        delegate: RowLayout {
                            required property var modelData
                            width: ListView.view.width
                            MovieButton { Layout.fillWidth: true; text: modelData.name; onClicked: { root.channel = modelData.url; root.tab = "feed"; root.channelsOpen = false; root.browse(false); } }
                            MovieButton { text: "Unfollow"; enabled: !root.commandPending; onClicked: root.command("unsubscribe", {url:modelData.url}, result => { root.settings(result); if (root.channel === modelData.url) root.channel = ""; root.browse(false); }) }
                        }
                        ScrollBar.vertical: MovieScrollBar {}
                    }
                    MovieButton { text: "All followed channels"; onClicked: { root.channel = ""; root.tab = "feed"; root.channelsOpen = false; root.browse(false); } }
                }
            }
            Rectangle {
                objectName: "streamingJobsPanel"; visible: root.jobsOpen
                anchors.fill: parent; color: MovieStyle.surface; radius: 12; z: 5
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 20; spacing: 12
                    RowLayout {
                        Layout.fillWidth: true
                        MovieText { Layout.fillWidth: true; text: "Operations"; font.pixelSize: 24; font.bold: true }
                        MovieIconButton { iconName: "x"; text: "Close operations"; onClicked: root.jobsOpen = false }
                    }
                    ListView {
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; model: root.jobs; spacing: 16
                        delegate: ColumnLayout {
                            required property var modelData
                            width: ListView.view.width; spacing: 6
                            MovieText { Layout.fillWidth: true; text: modelData.title; font.bold: true }
                            MovieText { Layout.fillWidth: true; text: modelData.error || modelData.detail; wrapMode: Text.Wrap; color: modelData.state === "failed" ? MovieStyle.danger : MovieStyle.muted }
                            ProgressBar {
                                Layout.fillWidth: true; visible: ["queued", "running"].includes(modelData.state)
                                from: 0; to: Math.max(1, modelData.total); value: modelData.done
                                indeterminate: !modelData.total
                                background: Rectangle { implicitHeight: 4; color: MovieStyle.border; radius: 2 }
                                contentItem: Item { implicitHeight: 4; Rectangle { width: parent.width * (modelData.total > 0 ? Math.min(1, modelData.done / modelData.total) : 0.2); height: 4; color: MovieStyle.accent; radius: 2 } }
                            }
                            MovieButton { visible: ["queued", "running"].includes(modelData.state); text: modelData.cancel_requested ? "Cancelling…" : "Cancel"; enabled: !modelData.cancel_requested; onClicked: root.command("cancel", {job_id:modelData.job_id}, () => root.pollJobs()) }
                            MovieButton { visible: modelData.state === "finished" && modelData.result?.kind === "analysis"; text: "Read answer"; onClicked: { const value = modelData.result; root.select({id:value.videoId,title:"YouTube video",creator:""}); root.answer = value.text; root.answeredQuestion = value.question || "Summary"; root.detailTab = "summary"; root.jobsOpen = false; } }
                        }
                        ScrollBar.vertical: MovieScrollBar {}
                    }
                }
            }
        }
        RowLayout {
            visible: root.playback.playing; Layout.fillWidth: true
            MovieIconButton { iconName: root.playback.paused ? "play" : "pause"; text: root.playback.paused ? "Resume" : "Pause"; onClicked: root.command("pause", {}, result => root.playback = Object.assign({title:root.playback.title}, result)) }
            MovieText { Layout.fillWidth: true; text: root.playback.title || "Streaming"; elide: Text.ElideRight }
            MovieIconButton { iconName: "square"; text: "Stop"; onClicked: root.command("stop", {}, result => root.playback = result) }
        }
    }
}
