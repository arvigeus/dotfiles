import "../../ui"
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root

    property bool showLoading: true
    property bool showStatus: true
    property var host
    property bool popupActivity: false
    required property var title
    property bool tracksLoading: false
    property string lookupError: ""
    property string query: ""
    property string error: ""
    property string info: ""
    property bool searching: false
    property bool pollLoading: false
    property bool connected: false
    property bool connectionLoading: false
    property bool canStartQbittorrent: false
    property bool startLoading: false
    property bool launchPending: false
    property bool launchTimedOut: false
    property double launchDeadline: 0
    property int searchId: -1
    property string contextId: ""
    property int generation: 0
    property var results: []
    property var extraResults: []
    property bool extraSearching: false
    property string extraError: ""
    property string extraInfo: ""
    property bool extraSearchEnabled: false
    property int resultTotal: 0
    property bool moreLoading: false
    property var jobs: []
    property string reviewJobId: ""
    property var reviewFiles: []
    property bool reviewLoading: false
    property var inspectRow: ({})
    property var inspectFiles: []
    property var selectedFiles: []
    property bool inspectLoading: false
    readonly property var catalogueTracks: Array.isArray((title || {}).tracks) ? title.tracks.filter(track => {
        return track && track.kind === "song" && track.id;
    }) : []
    property var service: ownedService

    signal extraSearchRequested(string query)
    signal extraResultRequested(var result)
    signal contextReset
    signal imported
    signal trackLookupRequested(string query)

    function showJobPanel() {
        jobPanel.open();
    }

    function dismissTransient() {
        if (jobPanel.visible) {
            jobPanel.close();
            return true;
        }
        if (activity.visible) {
            activity.close();
            return true;
        }
        if (!visible)
            return false;

        if (reviewJobId) {
            reviewJobId = "";
            reviewFiles = [];
            return true;
        }
        if (inspectRow.url) {
            inspectRow = ({});
            inspectFiles = [];
            return true;
        }
        return false;
    }

    function currentContextId() {
        const item = title || {};
        return String(item.kind || "") + ":" + String(item.scope || "") + ":" + String(item.id || "") + ":" + String(item.season === undefined ? "" : item.season) + ":" + String(item.episode === undefined ? "" : item.episode);
    }

    function suggestedQuery() {
        const item = title || {};
        const year = item.kind === "tv" || (item.kind === "music" && item.scope === "artist") ? "" : String(item.year || item.firstPublishYear || item.releaseDate || "").slice(0, 4);
        const prefix = item.kind === "music" && item.scope !== "artist" && item.artist ? item.artist + " " : "";
        const suffix = item.kind === "book" && item.author ? " " + item.author : "";
        const episode = item.kind === "tv" ? item.season === undefined ? " complete" : " S" + String(item.season).padStart(2, "0") + (item.episode === undefined ? "" : "E" + String(item.episode).padStart(2, "0")) : "";
        const artist = item.kind === "music" && item.scope === "artist" ? " discography" : "";
        return prefix + (item.title || "") + (year ? " " + year : "") + suffix + episode + artist;
    }

    function sizeLabel(bytes) {
        const value = Number(bytes) || 0;
        return value >= 1.07374e+09 ? (value / 1.07374e+09).toFixed(2) + " GiB" : value >= 1.04858e+06 ? (value / 1.04858e+06).toFixed(1) + " MiB" : value >= 1024 ? (value / 1024).toFixed(1) + " KiB" : value + " B";
    }

    function prepare() {
        contextId = currentContextId();
        ++generation;
        if (searchId >= 0)
            service.request("stop", {
                "job_id": searchId
            }, () => {});

        searchId = -1;
        results = [];
        resultTotal = 0;
        searching = false;
        pollLoading = false;
        moreLoading = false;
        error = "";
        lookupError = "";
        info = "";
        reviewJobId = "";
        reviewFiles = [];
        reviewLoading = false;
        inspectRow = ({});
        inspectFiles = [];
        selectedFiles = [];
        inspectLoading = false;
        query = suggestedQuery();
        contextReset();
        if (service.monitorJobs)
            applyJobs(service.jobs);
        else
            jobs = [];
        if (visible)
            connect();
    }

    function connect() {
        if (connectionLoading)
            return;

        connectionLoading = true;
        service.request("probe", {}, (result, failure) => {
            connectionLoading = false;
            if (!visible)
                return;

            connected = !failure && !!result && result.connected;
            canStartQbittorrent = !failure && !!result && result.canStart && !startLoading && !launchPending;
            if (connected) {
                launchPending = false;
                launchTimedOut = false;
                error = result.plugins.length ? "" : "Enable a search plugin in qBittorrent first.";
            } else if (!launchPending && !startLoading) {
                error = launchTimedOut ? "qBittorrent did not become available. Check that it started and its Web UI is enabled." : failure || (result && result.error) || "Cannot connect to qBittorrent.";
            }
            if (!launchPending)
                refreshJobs();
        });
    }

    function startQbittorrent() {
        if (!canStartQbittorrent || startLoading || launchPending)
            return;

        startLoading = true;
        canStartQbittorrent = false;
        launchTimedOut = false;
        error = "";
        service.request("start_qbittorrent", {}, (result, failure) => {
            startLoading = false;
            if (failure) {
                error = failure;
                canStartQbittorrent = true;
                return;
            }
            if (result && result.started && host) {
                host.hide();
                return;
            }
            launchPending = true;
            launchDeadline = Date.now() + 30000;
            connect();
        });
    }

    function find() {
        if (!query.trim())
            return;

        const pattern = query.trim();
        if (extraSearchEnabled)
            extraSearchRequested(pattern);

        const current = ++generation;
        const previous = searchId;
        searchId = -1;
        results = [];
        resultTotal = 0;
        searching = true;
        pollLoading = false;
        moreLoading = false;
        error = "";
        info = "";
        const begin = () => {
            if (current !== generation)
                return;

            service.request("search", {
                "query": pattern,
                "title": title
            }, (result, failure) => {
                if (current !== generation)
                    return;

                if (failure) {
                    searching = false;
                    error = failure;
                    return;
                }
                searchId = result.id;
                pollSearch();
            });
        };
        if (previous >= 0)
            service.request("stop", {
                "job_id": previous
            }, begin);
        else
            begin();
    }

    function pollSearch() {
        if (searchId < 0 || pollLoading || moreLoading)
            return;

        const id = searchId;
        const current = generation;
        const operation = results.length >= 100 ? "status" : "results";
        pollLoading = true;
        service.request(operation, {
            "job_id": id,
            "title": title,
            "offset": 0
        }, (result, failure) => {
            if (current !== generation || id !== searchId)
                return;

            pollLoading = false;
            if (failure) {
                searching = false;
                error = failure;
                return;
            }
            if (operation === "results")
                results = result.items;

            resultTotal = result.total;
            searching = result.running;
            if (!result.running && !results.length)
                info = "No results from the enabled search plugins.";

            Qt.callLater(maybeLoadMore);
        });
    }

    function maybeLoadMore() {
        if (!visible || reviewJobId || resultList.height <= 0 || pollLoading || moreLoading || searchId < 0 || results.length >= resultTotal)
            return;

        if (resultList.contentY + resultList.height >= resultList.contentHeight - 280)
            loadMore();
    }

    function loadMore() {
        if (searchId < 0 || pollLoading || moreLoading || results.length >= resultTotal)
            return;

        const id = searchId;
        const current = generation;
        const offset = results.length;
        moreLoading = true;
        service.request("results", {
            "job_id": id,
            "title": title,
            "offset": offset
        }, (result, failure) => {
            if (current !== generation || id !== searchId)
                return;

            moreLoading = false;
            if (failure) {
                error = failure;
                return;
            }
            results = results.concat(result.items);
            resultTotal = result.total;
            Qt.callLater(maybeLoadMore);
        });
    }

    function refreshJobs() {
        if (service.monitorJobs) {
            service.refreshJobs();
            applyJobs(service.jobs);
            return;
        }
        service.request("jobs", {}, (result, failure) => {
            if (failure) {
                if (connected)
                    error = failure;

                return;
            }
            applyJobs(result);
        });
    }

    function applyJobs(result) {
        const previous = jobs.filter(job => {
            return job.status === "imported";
        }).map(job => {
            return job.id;
        });
        const aliases = [title.id, title.imdbId].filter(Boolean);
        if (title.tmdbId)
            aliases.push("tmdb:" + title.kind + ":" + title.tmdbId);

        jobs = result.filter(job => {
            return job.kind === title.kind && aliases.includes(job.titleId);
        });
        if (!service.monitorJobs && jobs.some(job => {
            return job.status === "imported" && !previous.includes(job.id);
        }))
            imported();
    }

    function queue(row) {
        if (row.yearMismatch) {
            error = "This result names a different year. Refine the search before downloading.";
            return;
        }
        if (row.episodeMismatch) {
            error = "This result names a different episode. Refine the search before downloading.";
            return;
        }
        if (row.seasonMismatch) {
            error = "This result names a different season. Refine the search before downloading.";
            return;
        }
        if (title.kind === "music") {
            inspectRow = row;
            inspectFiles = [];
            selectedFiles = [];
            fetchFiles();
            return;
        }
        commitQueue(row, null);
    }

    function fetchFiles() {
        if (!inspectRow.url || inspectLoading)
            return;

        const url = inspectRow.url;
        inspectLoading = true;
        service.request("inspect", {
            "url": url
        }, (result, failure) => {
            if (inspectRow.url !== url)
                return;

            inspectLoading = false;
            if (failure) {
                error = failure;
                inspectRow = ({});
                return;
            }
            if (!result.ready)
                return;

            const audio = result.files.filter(file => {
                return file.audio;
            });
            if (!audio.length) {
                error = "This torrent has no supported audio files.";
                inspectRow = ({});
                return;
            }
            if (audio.length === 1) {
                commitQueue(inspectRow, [audio[0].index]);
                inspectRow = ({});
                return;
            }
            inspectFiles = result.files;
        });
    }

    function commitQueue(row, selected) {
        const args = {
            "title": title,
            "url": row.url
        };
        const context = currentContextId();
        if (selected !== null)
            args.selected_files = selected;

        service.pendingDownloads++;
        service.request("queue", args, (result, failure) => {
            if (!failure && service.monitorJobs)
                service.jobs = service.jobs.concat([
                    {
                        "id": result.id,
                        "titleId": result.titleId,
                        "kind": args.title.kind,
                        "status": "queued",
                        "active": true,
                        "savePath": result.savePath
                    }
                ]);

            service.pendingDownloads--;
            if (context !== currentContextId()) {
                refreshJobs();
                return;
            }
            if (failure) {
                error = failure;
            } else {
                info = args.title.kind === "movie" || args.title.kind === "tv" ? "Downloading to " + result.savePath + ". Completed files appear in Local automatically." : "Added to qBittorrent. Import starts when the download completes.";
                inspectRow = ({});
                inspectFiles = [];
                selectedFiles = [];
                refreshJobs();
            }
        });
    }

    function review(job) {
        error = "";
        reviewJobId = job.id;
        reviewFiles = [];
        reviewLoading = true;
        trackPicker.currentIndex = 0;
        artistField.text = title.artist || "";
        albumField.text = title.album || "";
        dateField.text = title.releaseDate || "";
        service.request("review", {
            "job_id": job.id
        }, (result, failure) => {
            if (reviewJobId !== job.id)
                return;

            reviewLoading = false;
            if (failure)
                error = failure;
            else
                reviewFiles = result;
        });
    }

    function importFile(file) {
        const args = {
            "job_id": reviewJobId,
            "path": file.path
        };
        if (title.kind === "tv") {
            if (!seasonField.text || !episodeField.text) {
                error = "Enter the season and episode number.";
                return;
            }
            args.season = Number(seasonField.text);
            args.episode = Number(episodeField.text);
        }
        if (title.kind === "music") {
            if (title.scope === "album" || title.scope === "artist") {
                const track = catalogueTracks[trackPicker.currentIndex - 1];
                if (!track) {
                    error = "Choose a catalogue song for this file.";
                    return;
                }
                args.track = track;
            }
            args.artist = artistField.text;
            args.album = albumField.text;
            args.releaseDate = dateField.text;
        }
        service.change("import_selected", args, (result, failure) => {
            if (failure) {
                error = failure;
            } else {
                info = result.remaining ? "Imported into Local. " + result.remaining + " audio files remain to match." : "Imported into Local.";
                reviewFiles = reviewFiles.filter(item => {
                    return item.path !== file.path;
                });
                if (!result.remaining) {
                    reviewJobId = "";
                    reviewFiles = [];
                }
                trackPicker.currentIndex = 0;
                refreshJobs();
                imported();
            }
        });
    }

    function deleteJob(job) {
        service.change("delete_job", {
            "job_id": job.id
        }, (result, failure) => {
            if (failure) {
                error = failure;
                return;
            }
            info = "Removed the download and its files.";
            if (reviewJobId === job.id) {
                reviewJobId = "";
                reviewFiles = [];
            }
            refreshJobs();
            imported();
        });
    }

    onErrorChanged: {
        if (popupActivity && error)
            activity.notify(error, true);
    }
    onLookupErrorChanged: {
        if (popupActivity && lookupError)
            activity.notify(lookupError, true);
    }
    onInfoChanged: {
        if (popupActivity && info)
            activity.notify(info, false);
    }
    spacing: 8
    onTitleChanged: {
        if (currentContextId() !== contextId) {
            prepare();
        }
    }
    onCatalogueTracksChanged: trackPicker.currentIndex = 0
    onVisibleChanged: {
        if (visible) {
            if (!query)
                query = suggestedQuery();

            connect();
        } else {
            activity.close();
            jobPanel.close();
        }
    }
    Component.onCompleted: prepare()
    Component.onDestruction: {
        if (searchId >= 0) {
            service.request("stop", {
                "job_id": searchId
            }, () => {});
        }
    }

    TorrentService {
        id: ownedService

        onFailed: message => {
            return root.error = message;
        }
    }

    Connections {
        function onJobsChanged() {
            root.applyJobs(root.service.jobs);
        }

        target: root.service
    }

    Timer {
        interval: 1800
        repeat: true
        running: root.visible && root.searching
        onTriggered: root.pollSearch()
    }

    Timer {
        interval: 1500
        repeat: true
        running: root.visible && !!root.inspectRow.url && !root.inspectFiles.length
        onTriggered: root.fetchFiles()
    }

    Timer {
        interval: 5000
        repeat: true
        running: root.visible && root.connected && !root.service.monitorJobs
        onTriggered: root.refreshJobs()
    }

    Timer {
        interval: 1800
        repeat: true
        running: root.visible && root.launchPending
        onTriggered: {
            if (Date.now() >= root.launchDeadline) {
                root.launchPending = false;
                root.launchTimedOut = true;
                root.error = "qBittorrent did not become available. Check that it started and its Web UI is enabled.";
                root.connect();
            } else {
                root.connect();
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        MovieInput {
            id: searchField

            Layout.fillWidth: true
            text: root.query
            placeholderText: root.extraSearchEnabled ? "Search providers and qBittorrent…" : "Search qBittorrent…"
            onTextChanged: root.query = text
            onAccepted: root.find()
        }

        MovieButton {
            iconName: "search"
            text: "Search"
            enabled: !!root.query.trim()
            onClicked: root.find()
        }

        MovieSpinner {
            running: root.searching || root.extraSearching
            visible: root.showLoading && running
            Layout.preferredWidth: 26
            Layout.preferredHeight: 26
        }
    }

    MovieText {
        visible: !!root.extraError
        Layout.fillWidth: true
        text: root.extraError
        color: MovieStyle.danger
        wrapMode: Text.Wrap
    }

    MovieText {
        visible: root.showStatus && !!root.extraInfo && !root.extraSearching
        Layout.fillWidth: true
        text: root.extraInfo
        color: MovieStyle.muted
        wrapMode: Text.Wrap
    }

    MovieText {
        visible: !root.popupActivity && !!root.error
        Layout.fillWidth: true
        text: root.error
        color: MovieStyle.danger
        wrapMode: Text.Wrap
    }

    RowLayout {
        visible: root.canStartQbittorrent || root.startLoading || root.launchPending

        MovieButton {
            iconName: "power"
            text: "Start qBittorrent"
            enabled: root.canStartQbittorrent && !root.startLoading && !root.launchPending
            onClicked: root.startQbittorrent()
        }

        MovieSpinner {
            running: root.startLoading || root.launchPending
            visible: root.showLoading && running
            Layout.preferredWidth: 24
            Layout.preferredHeight: 24
        }
    }

    MovieText {
        visible: root.showStatus && !root.popupActivity && !!root.info
        Layout.fillWidth: true
        text: root.info
        color: MovieStyle.muted
        wrapMode: Text.Wrap
    }

    ListView {
        id: resultList

        visible: !root.reviewJobId && !root.inspectRow.url
        Layout.fillWidth: true
        Layout.fillHeight: visible
        clip: true
        model: root.extraResults.concat(root.results)
        spacing: 6
        onContentYChanged: root.maybeLoadMore()
        onContentHeightChanged: root.maybeLoadMore()
        onHeightChanged: root.maybeLoadMore()

        WheelScroll {
            view: resultList
        }

        ScrollBar.vertical: MovieScrollBar {}

        footer: MovieSpinner {
            width: resultList.width
            height: root.showLoading && root.moreLoading ? 36 : 0
            running: root.moreLoading
            visible: root.showLoading && running
        }

        delegate: Rectangle {
            id: resultRow

            required property var modelData
            readonly property bool providerOffer: modelData.source === "provider"
            readonly property string titleText: providerOffer ? String(modelData.title || "") : modelData.name

            width: resultList.width
            height: resultColumn.implicitHeight + 12
            radius: MovieStyle.controlRadius
            color: MovieStyle.surface
            border.color: MovieStyle.border

            ColumnLayout {
                id: resultColumn

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 6
                spacing: 3

                MovieText {
                    Layout.fillWidth: true
                    text: resultRow.titleText
                    wrapMode: Text.Wrap
                    font.bold: true
                }

                MovieText {
                    visible: resultRow.providerOffer
                    Layout.fillWidth: true
                    color: MovieStyle.muted
                    wrapMode: Text.Wrap
                    text: (resultRow.modelData.authors || []).join(", ")
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    MovieText {
                        Layout.fillWidth: true
                        text: resultRow.providerOffer ? ["Provider: " + resultRow.modelData.provider, resultRow.modelData.format || "Unknown format", resultRow.modelData.size_bytes !== undefined && resultRow.modelData.size_bytes !== null ? root.sizeLabel(resultRow.modelData.size_bytes) : resultRow.modelData.size || "Unknown size", resultRow.modelData.language, resultRow.modelData.year].filter(Boolean).join(" · ") : "qBittorrent · " + root.sizeLabel(resultRow.modelData.size) + " · " + resultRow.modelData.seeders + " seeds" + (resultRow.modelData.site ? " · " + resultRow.modelData.site : "") + (resultRow.modelData.yearMismatch ? " · Different year" : "") + (resultRow.modelData.episodeMismatch ? " · Different episode" : "") + (resultRow.modelData.seasonMismatch ? " · Different season" : "")
                        color: resultRow.modelData.yearMismatch || resultRow.modelData.episodeMismatch || resultRow.modelData.seasonMismatch ? MovieStyle.danger : MovieStyle.muted
                        wrapMode: Text.Wrap
                    }

                    MovieIconButton {
                        objectName: resultRow.providerOffer ? "providerDownloadButton" : ""
                        visible: resultRow.providerOffer
                        iconName: "download"
                        text: "Download " + resultRow.titleText
                        onClicked: root.extraResultRequested(resultRow.modelData)
                    }

                    MovieIconButton {
                        iconName: "info"
                        text: "Release details for " + resultRow.titleText
                        visible: !resultRow.providerOffer && !!resultRow.modelData.descriptionUrl
                        onClicked: Browser.open(resultRow.modelData.descriptionUrl, ({
                                "movie": "movies",
                                "tv": "series",
                                "book": "books",
                                "game": "games",
                                "music": "music"
                            })[root.title.kind] || "", "", root.host)
                    }

                    MovieIconButton {
                        visible: !resultRow.providerOffer
                        iconName: "download"
                        text: "Download " + resultRow.titleText
                        enabled: !resultRow.providerOffer && !resultRow.modelData.yearMismatch && !resultRow.modelData.episodeMismatch && !resultRow.modelData.seasonMismatch && !!resultRow.modelData.url
                        onClicked: root.queue(resultRow.modelData)
                    }
                }
            }
        }
    }

    MovieButton {
        visible: !!root.inspectRow.url
        iconName: "arrow-left"
        text: "Back to results"
        onClicked: {
            root.inspectRow = ({});
            root.inspectFiles = [];
            root.selectedFiles = [];
        }
    }

    MovieText {
        visible: !!root.inspectRow.url && root.inspectFiles.length > 0
        Layout.fillWidth: true
        text: "Choose audio files to download."
        color: MovieStyle.muted
    }

    MovieSpinner {
        visible: root.showLoading && root.inspectLoading
        running: visible
    }

    ListView {
        id: inspectList

        visible: !!root.inspectRow.url && root.inspectFiles.length > 0
        Layout.fillWidth: true
        Layout.fillHeight: visible
        clip: true
        model: root.inspectFiles
        spacing: 6

        WheelScroll {
            view: inspectList
        }

        ScrollBar.vertical: MovieScrollBar {}

        delegate: CheckBox {
            required property var modelData

            width: inspectList.width
            enabled: modelData.audio
            text: modelData.path + " · " + root.sizeLabel(modelData.size)
            checked: root.selectedFiles.includes(modelData.index)
            onToggled: root.selectedFiles = checked ? root.selectedFiles.concat([modelData.index]) : root.selectedFiles.filter(index => {
                return index !== modelData.index;
            })
        }
    }

    MovieButton {
        visible: !!root.inspectRow.url && root.inspectFiles.length > 0
        iconName: "download"
        text: "Download selected files"
        enabled: root.selectedFiles.length > 0
        onClicked: root.commitQueue(root.inspectRow, root.selectedFiles)
    }

    Repeater {
        model: root.popupActivity ? [] : root.jobs

        RowLayout {
            required property var modelData

            Layout.fillWidth: true

            MovieText {
                Layout.fillWidth: true
                text: modelData.title + " · " + modelData.status + " · " + Math.round(modelData.progress * 100) + "%" + (modelData.message ? " · " + modelData.message : "")
                color: modelData.status === "review" ? MovieStyle.danger : MovieStyle.muted
                wrapMode: Text.Wrap
            }

            MovieButton {
                visible: modelData.status === "review"
                text: "Review files"
                onClicked: root.review(modelData)
            }

            HoldDelete {
                torrent: true
                onActivated: root.deleteJob(modelData)
            }
        }
    }

    OperationCenter {
        id: activity

        parent: root
        notificationTitle: "Find"
    }

    Popup {
        id: jobPanel

        parent: root
        width: Math.min(600, root.width - 24)
        height: Math.min(implicitHeight, root.height - 24)
        x: (root.width - width) / 2
        y: (root.height - height) / 2
        modal: false
        focus: true
        popupType: Popup.Item
        padding: 14

        background: Rectangle {
            color: MovieStyle.surface
            border.color: MovieStyle.border
            radius: MovieStyle.controlRadius
        }

        contentItem: ColumnLayout {
            spacing: 10

            RowLayout {
                Layout.fillWidth: true

                MovieText {
                    text: "Downloads for " + (root.title.title || "this item")
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }

                MovieIconButton {
                    iconName: "x"
                    text: "Close download panel"
                    onClicked: jobPanel.close()
                }
            }

            Repeater {
                model: root.jobs

                RowLayout {
                    required property var modelData

                    Layout.fillWidth: true

                    MovieText {
                        Layout.fillWidth: true
                        text: modelData.title + " · " + modelData.status + " · " + Math.round((modelData.progress || 0) * 100) + "%"
                        elide: Text.ElideRight
                    }

                    MovieButton {
                        visible: modelData.status === "review"
                        text: "Review files"
                        onClicked: {
                            root.review(modelData);
                            jobPanel.close();
                        }
                    }

                    HoldDelete {
                        torrent: true
                        onActivated: root.deleteJob(modelData)
                    }
                }
            }

            MovieText {
                visible: !root.jobs.length
                text: "No tracked downloads for this item"
                color: MovieStyle.muted
            }
        }
    }

    MovieButton {
        visible: !!root.reviewJobId
        iconName: "arrow-left"
        text: "Back to results"
        onClicked: {
            root.reviewJobId = "";
            root.reviewFiles = [];
            root.reviewLoading = false;
        }
    }

    RowLayout {
        visible: !!root.reviewJobId && root.title.kind === "tv"
        Layout.fillWidth: true

        MovieInput {
            id: seasonField

            Layout.preferredWidth: 75
            placeholderText: "Season"

            validator: IntValidator {
                bottom: 0
                top: 99
            }
        }

        MovieInput {
            id: episodeField

            Layout.preferredWidth: 80
            placeholderText: "Episode"

            validator: IntValidator {
                bottom: 1
                top: 999
            }
        }

        MovieText {
            Layout.fillWidth: true
            text: "Confirm numbering before import."
            color: MovieStyle.muted
        }
    }

    RowLayout {
        visible: !!root.reviewJobId && root.title.kind === "music"
        Layout.fillWidth: true

        MovieChoice {
            id: trackPicker

            visible: root.title.scope === "album" || root.title.scope === "artist"
            Layout.fillWidth: true
            model: ["Choose catalogue song"].concat(root.catalogueTracks.map(track => {
                return track.title + " — " + track.album;
            }))
            onActivated: {
                const track = root.catalogueTracks[currentIndex - 1];
                if (track) {
                    artistField.text = track.artist || "";
                    albumField.text = track.album || "";
                    dateField.text = track.releaseDate || root.title.releaseDate || "";
                }
            }
        }

        MovieInput {
            id: artistField

            Layout.fillWidth: true
            placeholderText: "Artist"
            text: root.title.artist || ""
        }

        MovieInput {
            id: albumField

            Layout.fillWidth: true
            placeholderText: "Album"
            text: root.title.album || ""
        }

        MovieInput {
            id: dateField

            Layout.preferredWidth: 150
            placeholderText: "YYYY-MM-DD"
            text: root.title.releaseDate || ""
        }
    }

    MovieText {
        visible: !root.tracksLoading && !!root.reviewJobId && root.title.kind === "music" && (root.title.scope === "album" || root.title.scope === "artist")
        Layout.fillWidth: true
        text: root.catalogueTracks.length ? "Match each audio file to its catalogue song before importing." : "Search the catalogue below to find the matching song."
        color: MovieStyle.muted
        wrapMode: Text.Wrap
    }

    RowLayout {
        visible: !!root.reviewJobId && root.title.kind === "music" && (root.title.scope === "album" || root.title.scope === "artist")
        Layout.fillWidth: true

        MovieInput {
            id: songLookup

            Layout.fillWidth: true
            placeholderText: "Find catalogue song by title or artist…"
            onAccepted: root.trackLookupRequested(text.trim())
        }

        MovieIconButton {
            iconName: "search"
            text: "Search catalogue songs"
            enabled: !!songLookup.text.trim() && !root.tracksLoading
            onClicked: root.trackLookupRequested(songLookup.text.trim())
        }
    }

    MovieText {
        visible: !root.popupActivity && !!root.lookupError
        Layout.fillWidth: true
        text: root.lookupError
        color: MovieStyle.danger
        wrapMode: Text.Wrap
    }

    ListView {
        id: reviewList

        objectName: "torrentReviewList"
        visible: !!root.reviewJobId
        Layout.fillWidth: true
        Layout.fillHeight: visible
        clip: true
        model: root.reviewFiles
        spacing: 6

        WheelScroll {
            view: reviewList
        }

        MovieSpinner {
            anchors.centerIn: parent
            running: root.reviewLoading
            visible: root.showLoading && running
        }

        ScrollBar.vertical: MovieScrollBar {}

        delegate: RowLayout {
            required property var modelData

            width: reviewList.width
            height: Math.max(42, fileName.implicitHeight + 10)

            MovieText {
                id: fileName

                Layout.fillWidth: true
                text: modelData.path + (modelData.tags && modelData.tags.title ? " · " + modelData.tags.title + " — " + modelData.tags.artist : "")
                wrapMode: Text.Wrap
            }

            MovieButton {
                text: "Import"
                onClicked: root.importFile(modelData)
            }
        }
    }
}
