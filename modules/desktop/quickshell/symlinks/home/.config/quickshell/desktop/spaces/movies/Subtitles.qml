import QtQuick
import "../../ui"
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell

ColumnLayout {
    id: root
    property bool showLoading: true
    function fontSize(value) { return Math.round(value * MovieStyle.fontSize / 14); }
    property var host
    function dismissTransient() {
        if (!visible) return false;
        if (adjustPath) { adjustPath = ""; return true; }
        if (addingLanguage) { addingLanguage = false; return true; }
        return false;
    }
    property var files: []
    property string requestedPath: ""
    property string path: ""
    property int generation: 0
    property int queryGeneration: 0
    property bool loading: false
    property bool searching: false
    property bool moreLoading: false
    property bool changing: false
    property string error: ""
    property string info: ""
    property var inventory: ({files:[],embedded:[],release:{},fps:0,languages:[]})
    property var results: []
    property string searchToken: ""
    property int nextPage: 0
    property var languages: []
    property string extraLanguage: ""
    property bool addingLanguage: false
    property int resultDisplayLimit: 24
    property var adjustedFileIds: []
    property string adjustPath: ""
    readonly property var availableTracks: (inventory.files || []).map(file => Object.assign({source:"file"}, file))
        .concat((inventory.embedded || []).map(track => Object.assign({source:"embedded"}, track)))
    readonly property var shownResults: results.slice(0, resultDisplayLimit)
    spacing: 8

    SubtitleService { id: service; onFailed: message => root.error = message }

    function refresh() {
        if (!visible || !path) return;
        const current = ++generation;
        loading = true; error = "";
        service.request("inspect", {path:path}, (result, failure) => {
            if (current !== generation) return;
            loading = false;
            if (failure) { error = failure; return; }
            inventory = result;
            if (!languages.length) languages = result.languages.length ? result.languages : ["en"];
        });
    }
    function search() {
        if (!path || !languages.length) return;
        const current = generation;
        const query = ++queryGeneration;
        searching = true; error = ""; info = ""; results = []; resultDisplayLimit = 24; adjustedFileIds = []; searchToken = ""; nextPage = 0;
        subtitleScroll.contentItem.contentY = 0;
        service.request("search", {path:path,languages:languages}, (result, failure) => {
            if (current !== generation || query !== queryGeneration) return;
            searching = false;
            if (failure) { error = failure; return; }
            results = result.items;
            searchToken = result.searchId;
            languages = result.languages;
            nextPage = result.nextPage;
            if (!results.length) info = "No subtitles found for these languages. Try another language or release.";
        });
    }
    function loadMore() {
        if (!nextPage || moreLoading) return;
        const current = generation;
        const query = queryGeneration;
        moreLoading = true;
        service.request("search", {path:path,languages:languages,page:nextPage,searchId:searchToken}, (result, failure) => {
            if (current !== generation || query !== queryGeneration) return;
            moreLoading = false;
            if (failure) { error = failure; nextPage = 0; return; }
            results = results.concat(result.items);
            nextPage = result.nextPage;
        });
    }
    function maybeLoadMore() {
        if (!visible || !results.length || searching || moreLoading) return;
        const view = subtitleScroll.contentItem;
        if (!view || view.height <= 0 || view.contentY + view.height < view.contentHeight - 120) return;
        if (resultDisplayLimit < results.length) resultDisplayLimit = Math.min(resultDisplayLimit + 24, results.length);
        else if (nextPage > 0) loadMore();
    }
    function canAdjust(row) {
        return !!(row.fps && inventory.fps && Math.abs(row.fps - inventory.fps) > 0.01);
    }
    function toggleAdjustment(fileId) {
        adjustedFileIds = adjustedFileIds.includes(fileId)
            ? adjustedFileIds.filter(id => id !== fileId) : adjustedFileIds.concat([fileId]);
    }
    function download(row) {
        if (changing) return;
        const current = generation;
        changing = true; error = "";
        service.request("download", {path:path,fileId:row.fileId,searchId:searchToken,adapt:adjustedFileIds.includes(row.fileId)}, (result, failure) => {
            if (current !== generation) return;
            changing = false;
            if (failure) { error = failure; return; }
            info = "Saved " + result.path.split("/").pop() + (result.adapted ? " with timing adjusted to the video." : ".")
                + (result.remaining === undefined || result.remaining === null ? "" : " Downloads left: " + result.remaining + ".");
            refresh();
        });
    }
    function extract(row) {
        const current = generation;
        changing = true; error = "";
        service.request("extract", {path:path,index:row.index}, (result, failure) => {
            if (current !== generation) return;
            changing = false;
            if (failure) { error = failure; return; }
            info = "Extracted " + result.path.split("/").pop() + ".";
            refresh();
        });
    }
    function retime(source, sourceFps, offset) {
        if (changing) return;
        const current = generation;
        changing = true; error = "";
        service.request("retime", {path:path,subtitle:source,sourceFps:sourceFps || String(inventory.fps),offset:offset || "0"}, (result, failure) => {
            if (current !== generation) return;
            changing = false;
            if (failure) { error = failure; return; }
            if (adjustPath === source) adjustPath = "";
            info = "Saved " + result.path.split("/").pop() + ". Original kept as " + result.backup.split("/").pop() + ".";
            refresh();
        });
    }
    function remove(source) {
        const current = generation;
        changing = true; error = "";
        service.request("remove", {path:path,subtitle:source}, (result, failure) => {
            if (current !== generation) return;
            changing = false;
            if (failure) { error = failure; return; }
            info = "Removed " + result.removed.split("/").pop() + ".";
            refresh();
        });
    }
    function playWith(source) {
        const current = generation;
        service.request("play_with", {path:path,subtitle:source}, (result, failure) => {
            if (current !== generation) return;
            if (failure) error = failure;
            else External.launch(result.command, root.host);
        });
    }
    function toggleLanguage(code) {
        if (!languages.includes(code) && languages.length >= 5) { error = "Choose up to five languages."; return; }
        languages = languages.includes(code) ? languages.filter(value => value !== code) : languages.concat([code]);
        resetSearch();
    }
    function resetSearch() {
        ++queryGeneration;
        searching = false; moreLoading = false; results = []; resultDisplayLimit = 24; adjustedFileIds = [];
        searchToken = ""; nextPage = 0; info = ""; error = "";
    }
    function languageName(code) {
        return ({en:"English",bg:"Bulgarian",vi:"Vietnamese",fr:"French",de:"German",es:"Spanish",
                 it:"Italian",pt:"Portuguese",ru:"Russian",ja:"Japanese",ko:"Korean",zh:"Chinese"})[code] || code.toUpperCase();
    }
    function addLanguage() {
        const typed = extraLanguage.trim().toLowerCase();
        const code = ({bul:"bg",vie:"vi",eng:"en"})[typed] || typed;
        if (!/^[a-z]{2,3}$/.test(code)) { error = "Enter a two or three letter language code."; return; }
        if (!languages.includes(code) && languages.length >= 5) { error = "Choose up to five languages."; return; }
        if (!languages.includes(code)) { languages = languages.concat([code]); resetSearch(); }
        extraLanguage = ""; error = ""; addingLanguage = false;
    }
    onFilesChanged: {
        if (!files.some(file => file.path === path)) path = files.length ? files[0].path : "";
    }
    onRequestedPathChanged: if (requestedPath && files.some(file => file.path === requestedPath)) path = requestedPath
    onPathChanged: { results = []; resultDisplayLimit = 24; adjustedFileIds = []; searchToken = ""; nextPage = 0; languages = []; addingLanguage = false; searching = false; moreLoading = false; changing = false; ++queryGeneration; inventory = ({files:[],embedded:[],release:{},fps:0,languages:[]}); adjustPath = ""; ++generation; refresh(); }
    onResultsChanged: fillTimer.restart()
    onVisibleChanged: if (visible) refresh()
    Timer { id: fillTimer; interval: 80; onTriggered: root.maybeLoadMore() }

    RowLayout {
        Layout.fillWidth: true
        MovieText { Layout.fillWidth: true; text: root.files.length === 1 ? root.files[0].path.split("/").pop() : "Video"; elide: Text.ElideMiddle; visible: root.files.length === 1 }
        MovieChoice {
            visible: root.files.length > 1
            Layout.fillWidth: true
            model: root.files.map(file => (file.season !== undefined ? "S" + String(file.season).padStart(2,"0") + "E" + String(file.episode).padStart(2,"0") + " · " : "") + file.path.split("/").pop())
            currentIndex: Math.max(0,root.files.findIndex(file => file.path === root.path))
            onActivated: index => root.path = root.files[index].path
            Accessible.name: "Local video"
        }
        MovieSpinner { running: root.loading || root.searching || root.moreLoading || root.changing; visible: root.showLoading && running; Layout.preferredWidth: 28; Layout.preferredHeight: 28 }
        MovieButton { iconName: "refresh-cw"; text: "Refresh"; enabled: !!root.path && !root.loading; onClicked: root.refresh() }
    }
    MovieText { visible: !!root.error; text: root.error; color: MovieStyle.danger; Layout.fillWidth: true; wrapMode: Text.Wrap }
    MovieText { visible: !!root.info; text: root.info; color: MovieStyle.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
    ScrollArea {
        id: subtitleScroll
        objectName: "subtitleScroll"
        Layout.fillWidth: true; Layout.fillHeight: true; clip: true
        contentWidth: availableWidth
        Connections {
            target: subtitleScroll.contentItem
            function onContentYChanged() { root.maybeLoadMore(); }
            function onContentHeightChanged() { fillTimer.restart(); }
            function onHeightChanged() { fillTimer.restart(); }
        }
        ColumnLayout {
            width: parent.width; spacing: 10
            MovieText { text: "Available subtitles"; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(17); font.bold: true; visible: !!root.path }
            MovieText { text: "No subtitles found in this video or beside it."; visible: !!root.path && !root.loading && !root.availableTracks.length; color: MovieStyle.muted }
            Repeater {
                model: root.availableTracks
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: Math.max(58, trackContent.implicitHeight + 16)
                    radius: MovieStyle.controlRadius; color: MovieStyle.surface; border.color: MovieStyle.border
                    ColumnLayout {
                        id: trackContent
                        anchors.fill: parent; anchors.margins: 8; spacing: 6
                        RowLayout {
                            Layout.fillWidth: true; spacing: 6
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 2
                                MovieText { Layout.fillWidth: true; text: root.languageName(modelData.language) + (modelData.forced ? " · Forced" : ""); font.weight: Font.DemiBold }
                                MovieText {
                                    Layout.fillWidth: true; color: MovieStyle.muted; elide: Text.ElideMiddle
                                    text: modelData.source === "file"
                                        ? "On disk · " + modelData.name + " · " + modelData.format.toUpperCase()
                                        : "Embedded · " + (modelData.title || modelData.codec) + " · " + modelData.codec
                                }
                            }
                            MovieIconButton { visible: modelData.source === "file"; iconName: "play"; text: "Play with this subtitle"; onClicked: root.playWith(modelData.path) }
                            MovieButton {
                                objectName: "diskAdjust"
                                visible: modelData.source === "file" && modelData.format === "srt" && !!root.inventory.fps
                                iconName: "sliders-horizontal"; text: "Adjust"; highlighted: root.adjustPath === modelData.path
                                onClicked: root.adjustPath = root.adjustPath === modelData.path ? "" : modelData.path
                            }
                            MovieButton { visible: modelData.source === "embedded" && modelData.extractable; text: "Extract SRT"; enabled: !root.changing; onClicked: root.extract(modelData) }
                            HoldDelete { visible: modelData.source === "file" && modelData.managed; enabled: !root.changing; onActivated: root.remove(modelData.path) }
                        }
                        Flow {
                            id: timingRow
                            objectName: "timingControls"
                            visible: root.adjustPath === modelData.path && modelData.source === "file"
                            Layout.fillWidth: true; spacing: 8
                            readonly property bool validTiming: sourceRate.text.trim() !== "" && !isNaN(Number(sourceRate.text)) && !isNaN(Number(timingOffset.text || "0"))
                            readonly property bool timingChanged: validTiming && (Math.abs(Number(sourceRate.text) - root.inventory.fps) > 0.00001 || Number(timingOffset.text || "0") !== 0)
                            RowLayout {
                                spacing: 8
                                MovieText { text: "Subtitle fps"; color: MovieStyle.muted }
                                MovieInput {
                                    id: sourceRate
                                    Layout.preferredWidth: 100; text: root.inventory.fps ? String(root.inventory.fps) : ""
                                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                                    Accessible.name: "Subtitle frame rate"
                                }
                                MovieText { text: "Video " + root.inventory.fps + " fps"; color: MovieStyle.muted }
                            }
                            RowLayout {
                                spacing: 8
                                MovieText { text: "Offset (s)"; color: MovieStyle.muted }
                                MovieInput {
                                    id: timingOffset
                                    objectName: "timingOffset"
                                    Layout.preferredWidth: 90; text: "0"
                                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                                    Accessible.name: "Subtitle time offset in seconds"
                                    onAccepted: if (timingRow.timingChanged && !root.changing) root.retime(modelData.path, sourceRate.text, text)
                                }
                            }
                            MovieButton { objectName: "saveTiming"; iconName: "save"; text: "Save"; enabled: !root.changing && timingRow.timingChanged; onClicked: root.retime(modelData.path, sourceRate.text, timingOffset.text) }
                        }
                    }
                }
            }
            MovieText { text: "Find more on OpenSubtitles"; font.family: MovieStyle.fontFamily; font.pixelSize: fontSize(17); font.bold: true; visible: !!root.path; Layout.topMargin: 10 }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Repeater {
                    model: [{code:"en",name:"English"},{code:"bg",name:"Bulgarian"},{code:"vi",name:"Vietnamese"}]
                    MovieButton { required property var modelData; text: modelData.name; highlighted: root.languages.includes(modelData.code); onClicked: root.toggleLanguage(modelData.code) }
                }
                Repeater {
                    model: root.languages.filter(code => !["bg","vi","en"].includes(code))
                    MovieButton { required property string modelData; text: root.languageName(modelData); highlighted: true; onClicked: root.toggleLanguage(modelData) }
                }
                MovieIconButton { iconName: "plus"; text: "Add language"; onClicked: { root.addingLanguage = !root.addingLanguage; if (root.addingLanguage) Qt.callLater(() => languageField.forceActiveFocus()); } }
                MovieInput { id: languageField; visible: root.addingLanguage; width: 142; placeholderText: "Code, e.g. fr"; text: root.extraLanguage; onTextChanged: root.extraLanguage = text; onAccepted: root.addLanguage(); Accessible.name: "Language code" }
                MovieIconButton { visible: root.addingLanguage; iconName: "check"; text: "Save language"; onClicked: root.addLanguage() }
            }
            RowLayout {
                Layout.fillWidth: true
                MovieButton { iconName: "search"; text: "Search subtitles"; enabled: !!root.path && !!root.inventory.configured && root.languages.length > 0 && !root.searching; onClicked: root.search() }
                MovieText { visible: !!root.path && !root.inventory.configured; Layout.fillWidth: true; text: "Add an OpenSubtitles API key to media.json to search."; color: MovieStyle.muted; wrapMode: Text.Wrap }
            }
            MovieText { visible: root.results.length > 0; text: root.results.length + (root.nextPage > 0 ? " matches so far" : " matches") + " · Best matches first"; color: MovieStyle.muted; Layout.fillWidth: true }
            Repeater {
                model: root.shownResults
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: Math.max(60, resultRow.implicitHeight + 16)
                    radius: MovieStyle.controlRadius; color: MovieStyle.surface; border.color: MovieStyle.border
                    RowLayout {
                        id: resultRow
                        anchors.fill: parent; anchors.margins: 8; spacing: 6
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 2
                            MovieText { text: root.languageName(modelData.language) + " · " + modelData.release; Layout.fillWidth: true; elide: Text.ElideMiddle; font.weight: Font.DemiBold }
                            MovieText { text: [modelData.hashMatch ? "Exact video" : "", modelData.releaseMatch ? "Release match" : "", modelData.trusted ? "Trusted" : "", modelData.forced ? "Forced" : "", modelData.hearingImpaired ? "Hearing impaired" : "", modelData.fps ? (root.canAdjust(modelData) ? modelData.fps + " fps · Video " + root.inventory.fps + " fps" : modelData.fps + " fps") : "", modelData.downloads + " downloads"].filter(Boolean).join(" · "); color: MovieStyle.muted; Layout.fillWidth: true; elide: Text.ElideRight }
                        }
                        MovieButton {
                            visible: root.canAdjust(modelData)
                            iconName: "sliders-horizontal"; text: "Adjust"
                            highlighted: root.adjustedFileIds.includes(modelData.fileId)
                            Accessible.name: (highlighted ? "Disable" : "Enable") + " timing adjustment for " + modelData.release
                            ToolTip.text: "Adjust " + modelData.fps + " fps subtitles to " + root.inventory.fps + " fps when downloading"
                            onClicked: root.toggleAdjustment(modelData.fileId)
                        }
                        MovieButton { iconName: "download"; text: "Download"; enabled: !root.changing; onClicked: root.download(modelData) }
                    }
                }
            }
            MovieSpinner { visible: root.showLoading && root.moreLoading; running: visible; Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 28; Layout.preferredHeight: 28 }
        }
    }
}
