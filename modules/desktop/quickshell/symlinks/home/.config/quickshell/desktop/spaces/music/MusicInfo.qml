import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import QtQml.Models
import "../../ui"
import "../movies"

MovieStyle.Panel {
    id: root
    objectName: "musicInformation"
    required property var files
    required property var catalogue
    property var coverService
    property var song: null
    property var original: ({})
    property var draft: ({})
    property var touched: ({})
    property var knownFields: []
    property var changes: ({})
    property string fileSignature: ""
    property string remoteVersion: ""
    property string originalPath: ""
    property string relativePath: ""
    property string fileInfo: ""
    property string coverDraft: ""
    property bool loadingTags: false
    property bool loadingStoredLyrics: false
    property string storedLyrics: ""
    readonly property string displayedLyrics: draft.lyrics || (touched.lyrics ? "" : storedLyrics)
    property bool tagsLoaded: false
    property string tagError: ""
    property int tagGeneration: 0
    property int lyricGeneration: 0
    property string message: ""
    property bool importantMessage: false
    property string jobId: ""
    property string operation: ""
    property bool busy: false
    property bool reading: false
    property bool previewLoaded: false
    property bool lookingUp: false
    property bool editing: false
    property int generation: 0
    readonly property bool editable: song?.source === "nextcloud" || song?.source === "music-local"
    readonly property bool dirty: editing && (!!coverDraft || Object.keys(changes).length > 0)
    readonly property bool pathDirty: relativePath !== originalPath
    readonly property string playCountText: song?.playCount !== undefined && song?.playCount !== null ? String(song.playCount) + (song.playCount === 1 ? " play" : " plays") : ""
    property alias coverPicker: coverChooser
    signal saved(var song, var result)
    maximumPanelWidth: 820
    maximumPanelHeight: 900
    modal: true
    closePolicy: Popup.NoAutoClose
    palette.window: MovieStyle.background
    palette.windowText: MovieStyle.text
    palette.base: MovieStyle.background
    palette.alternateBase: MovieStyle.surface
    palette.text: MovieStyle.text
    palette.button: MovieStyle.raised
    palette.buttonText: MovieStyle.text
    palette.light: MovieStyle.surface
    palette.midlight: MovieStyle.raised
    palette.mid: MovieStyle.border
    palette.dark: MovieStyle.border
    palette.shadow: "#000000"
    palette.highlight: MovieStyle.accentSurface
    palette.highlightedText: MovieStyle.text
    palette.placeholderText: MovieStyle.muted
    palette.accent: MovieStyle.accent
    palette.toolTipBase: MovieStyle.surface
    palette.toolTipText: MovieStyle.text
    function previewTags(item) {
        return {
            title: item.title || "",
            artist: item.artist || "",
            album: item.album || "",
            album_artist: item.albumArtist || "",
            date: item.releaseDate || "",
            genre: (item.genreNames || []).join("; "),
            track: String(item.trackNumber || ""),
            disc: String(item.discNumber || ""),
            composer: "",
            comment: "",
            lyrics: item.lyrics || ""
        };
    }
    function setMessage(text, important) {
        importantMessage = !!important;
        message = text || "";
    }
    function updateChanges() {
        const pending = ({});
        for (const key of Object.keys(touched))
            if (!knownFields.includes(key) || draft[key] !== original[key])
                pending[key] = draft[key] || "";
        changes = pending;
    }
    function editTag(key, value) {
        if (!editing || busy)
            return;
        if (lookingUp && ["lyrics", "title", "artist", "album"].includes(key)) {
            ++lyricGeneration;
            lookingUp = false;
        }
        touched = Object.assign({}, touched, {
            [key]: true
        });
        draft = Object.assign({}, draft, {
            [key]: value
        });
        updateChanges();
    }
    function applyTags(result) {
        const values = result.tags || {}, known = result.knownFields || Object.keys(values);
        const baseline = Object.assign({}, original), next = Object.assign({}, draft);
        for (const key of known) {
            baseline[key] = values[key] || "";
            if (!touched[key])
                next[key] = baseline[key];
        }
        original = baseline;
        draft = next;
        knownFields = Array.from(new Set(knownFields.concat(known)));
        if (result.signature !== undefined) {
            fileSignature = result.signature;
            remoteVersion = "";
        }
        if (result.remoteVersion !== undefined) {
            remoteVersion = result.remoteVersion;
            fileSignature = "";
        }
        fileInfo = result.fileInfo || fileInfo;
        updateChanges();
    }
    function loadFileTags() {
        if (!editable || busy || loadingTags || !originalPath)
            return;
        const token = ++tagGeneration;
        loadingTags = true;
        tagError = "";
        catalogue.request("file-tags", {
            song: song,
            lane: "info-tags"
        }, (result, failure) => {
            if (token !== tagGeneration)
                return;
            loadingTags = false;
            if (failure) {
                tagError = failure;
                return;
            }
            tagsLoaded = true;
            applyTags(result);
        });
    }
    function loadStoredLyrics() {
        if (song?.source !== "nextcloud" || song.local || song.localPath || !originalPath || loadingStoredLyrics || busy)
            return;
        const token = generation, path = originalPath;
        loadingStoredLyrics = true;
        catalogue.request("stored-lyrics", {
            song: Object.assign({}, song, {
                serverPath: path
            }),
            lane: "info"
        }, (result, failure) => {
            if (token !== generation || path !== originalPath)
                return;
            loadingStoredLyrics = false;
            if (!failure)
                storedLyrics = result.lyrics || "";
        });
    }
    function placeholder(key) {
        if (knownFields.includes(key))
            return "No value";
        return loadingTags ? "Loading existing value…" : "Existing value not loaded";
    }
    function showSong(item) {
        if (busy || (song && song.id === item.id && song.source === item.source && (editing || reading || previewLoaded))) {
            open();
            if (!tagsLoaded)
                loadFileTags();
            loadStoredLyrics();
            return;
        }
        if (dirty) {
            setMessage("Save or cancel your edits before opening another song.", true);
            open();
            return;
        }
        const token = ++generation;
        song = item;
        lookingUp = false;
        editing = false;
        reading = true;
        previewLoaded = false;
        coverDraft = "";
        ++tagGeneration;
        ++lyricGeneration;
        loadingTags = false;
        loadingStoredLyrics = false;
        storedLyrics = "";
        tagsLoaded = false;
        tagError = "";
        remoteVersion = "";
        touched = ({});
        changes = ({});
        fileSignature = "";
        setMessage("");
        original = previewTags(item);
        knownFields = Object.keys(original).filter(key => !!original[key]);
        draft = Object.assign({}, original);
        originalPath = String(item.serverPath || "").replace(/^\/+/, "");
        const initialPath = originalPath;
        relativePath = originalPath;
        fileInfo = item.fileInfo || "";
        open();
        loadStoredLyrics();
        catalogue.request("song-info", {
            song: item,
            lane: "info"
        }, (result, failure) => {
            if (token !== generation)
                return;
            reading = false;
            if (failure) {
                setMessage(failure, true);
                return;
            }
            previewLoaded = true;
            song = Object.assign({}, song, result.song || {});
            // A slow preview must not replace edits made while it was loading.
            if (!tagsLoaded) {
                applyTags(result);
                if (result.signature !== undefined)
                    tagsLoaded = true;
            }
            const moving = pathDirty;
            originalPath = result.relativePath || originalPath;
            if (originalPath !== initialPath) {
                loadingStoredLyrics = false;
                storedLyrics = "";
                loadStoredLyrics();
            }
            if (!moving)
                relativePath = originalPath;
            if (!tagsLoaded)
                fileInfo = result.fileInfo || fileInfo;
            if (!tagsLoaded)
                loadFileTags();
        });
        if (!tagsLoaded && !item.local && !item.localPath && item.source !== "music-local")
            loadFileTags();
    }
    function prepare() {
        if (!editable || editing || busy || pathDirty)
            return;
        editing = true;
        setMessage("");
        if (!tagsLoaded && !reading)
            loadFileTags();
    }
    function chooseCover(file) {
        if (file && editing && !busy)
            coverDraft = String(file);
    }
    function run(action) {
        if (!song || busy || !editable)
            return;
        if (action === "save" && (!editing || !originalPath))
            return;
        if (action === "move" && (editing || !originalPath || !pathDirty))
            return;
        ++generation;
        ++tagGeneration;
        loadingStoredLyrics = false;
        ++lyricGeneration;
        reading = false;
        loadingTags = false;
        lookingUp = false;
        busy = true;
        jobId = "";
        operation = action;
        setMessage(action === "move" ? "Moving…" : "Saving locally and on Nextcloud…");
        const args = {
            action: action,
            song: song,
            title: action === "move" ? "Move song" : "Save metadata"
        };
        if (action === "save") {
            args.tags = changes;
            args.artwork = coverDraft || null;
            args.signature = fileSignature;
            args.remoteVersion = remoteVersion;
        }
        if (action === "move")
            args.relativePath = relativePath;
        files.startJob("file-job", args, (identifier, error) => {
            if (error)
                complete({}, error);
            else
                jobId = identifier;
        });
    }
    function complete(result, failure) {
        const action = result.action || operation;
        busy = false;
        jobId = "";
        operation = "";
        if (failure) {
            setMessage(failure, true);
            tagError = "Reload metadata to check the current values. Your draft will be kept.";
            return;
        }
        const rel = result.relativePath || originalPath;
        song = Object.assign({}, song, {
            serverPath: "/" + rel,
            localPath: result.local === false ? "" : result.path || song.localPath,
            local: result.local !== false,
            notUploaded: result.synced ? false : !!song.notUploaded,
            pendingUpload: action === "save" ? !result.synced : !!song.pendingUpload,
            coverVersion: Date.now()
        });
        originalPath = rel;
        relativePath = rel;
        storedLyrics = "";
        if (action === "save") {
            original = Object.assign({}, draft, result.tags || {});
            draft = Object.assign({}, original);
            knownFields = Object.keys(result.tags || original);
            touched = ({});
            changes = ({});
            fileSignature = result.signature || fileSignature;
            fileInfo = result.fileInfo || fileInfo;
            coverDraft = "";
            remoteVersion = "";
            tagsLoaded = true;
            if (result.synced) {
                editing = false;
            }
        } else
            loadStoredLyrics();
        setMessage(result.error ? "Saved locally. " + result.error : action === "move" ? "Song moved." : result.synced ? "Saved locally and on Nextcloud." : result.message || "Saved locally. The server file was not updated.", !!result.error || (action !== "move" && !result.synced));
        saved(song, result);
    }
    function cancelEdits() {
        if (busy)
            return;
        ++lyricGeneration;
        lookingUp = false;
        editing = false;
        coverDraft = "";
        touched = ({});
        changes = ({});
        draft = Object.assign({}, original);
        setMessage("");
    }
    function lookupLyrics() {
        if (!song || busy || reading || lookingUp || (editable && pathDirty))
            return;
        const token = ++lyricGeneration, previous = String(draft.lyrics || "");
        lookingUp = true;
        setMessage("Fetching lyrics…");
        catalogue.request("lyrics", {
            song: Object.assign({}, song, draft, {
                lyrics: displayedLyrics
            }),
            refresh: true,
            lane: "info"
        }, (result, failure) => {
            if (token !== lyricGeneration)
                return;
            lookingUp = false;
            if (String(draft.lyrics || "") !== previous)
                return;
            if (failure || !result?.available) {
                setMessage(failure || "No matching lyrics found.", !!failure);
                return;
            }
            if (editable) {
                prepare();
                editTag("lyrics", result.lyrics);
            } else {
                draft = Object.assign({}, draft, {
                    lyrics: result.lyrics
                });
            }
            setMessage("Lyrics loaded. Save to keep them in the file and on Nextcloud.");
        });
    }
    function restoreFocus() {
        Qt.callLater(() => {
            if (visible)
                contentItem.forceActiveFocus();
        });
    }
    function dismissTransient() {
        if (coverChooser.visible)
            coverChooser.reject();
        else if (editing && !busy)
            cancelEdits();
        else
            close();
        return true;
    }
    onClosed: {
        coverChooser.close();
        ++generation;
        ++tagGeneration;
        ++lyricGeneration;
        lookingUp = false;
        loadingTags = false;
        loadingStoredLyrics = false;
        reading = false;
    }
    Component.onDestruction: coverChooser.close()
    FileDialog {
        id: coverChooser
        objectName: "musicCoverPicker"
        title: "Choose cover art"
        parentWindow: root.parent.Window.window
        options: FileDialog.DontUseNativeDialog
        popupType: Popup.Item
        nameFilters: ["Images (*.jpg *.jpeg *.png *.webp)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            root.chooseCover(selectedFile);
            root.restoreFocus();
        }
        onRejected: root.restoreFocus()
    }
    Instantiator {
        model: ["window", "windowText", "base", "alternateBase", "text", "button", "buttonText", "light", "midlight", "mid", "dark", "shadow", "highlight", "highlightedText", "placeholderText", "accent", "toolTipBase", "toolTipText"]
        delegate: Binding {
            required property string modelData
            target: coverChooser.parentWindow ? coverChooser.parentWindow.palette : null
            property: modelData
            value: root.palette[modelData] || MovieStyle.surface
            when: root.visible && coverChooser.visible
        }
    }
    contentItem: ColumnLayout {
        spacing: 12
        Keys.onEscapePressed: root.dismissTransient()
        RowLayout {
            objectName: "musicInfoHeader"
            Layout.fillWidth: true
            spacing: 16
            Item {
                Layout.preferredWidth: 88
                Layout.preferredHeight: 88
                MusicCover {
                    objectName: "musicInfoCover"
                    anchors.fill: parent
                    record: root.song
                    previewSource: root.coverDraft
                    service: root.coverService
                    fetchEnabled: root.visible
                }
                MovieIconButton {
                    objectName: "musicChooseCover"
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 4
                    anchors.bottomMargin: 4
                    implicitWidth: 32
                    implicitHeight: 32
                    horizontalPadding: 6
                    verticalPadding: 6
                    iconName: "pencil"
                    text: "Edit cover art"
                    iconColor: MovieStyle.text
                    visible: root.editing
                    enabled: !root.busy
                    onClicked: coverChooser.open()
                }
            }
            ColumnLayout {
                objectName: "musicInfoHeading"
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                spacing: 5
                MovieStyle.PanelTitle {
                    objectName: "musicInfoTitle"
                    Layout.fillWidth: true
                    text: "Song information"
                }
                MovieText {
                    objectName: "musicFileInfo"
                    Layout.fillWidth: true
                    visible: !!text
                    text: [root.fileInfo, root.playCountText].filter(value => !!value).join(" · ")
                    color: MovieStyle.muted
                    wrapMode: Text.Wrap
                }
            }
            MovieButton {
                objectName: root.editing ? "musicCancelMetadata" : "musicEditMetadata"
                visible: root.editable
                text: root.editing ? "Cancel" : "Edit metadata"
                iconName: root.editing ? "x" : "pencil"
                enabled: !root.busy && (root.editing || !root.pathDirty)
                onClicked: root.editing ? root.cancelEdits() : root.prepare()
            }
            MovieButton {
                objectName: "musicSaveTags"
                visible: root.editing
                text: "Save"
                iconName: "save"
                enabled: root.editing && !!root.originalPath && !root.busy && (root.dirty || !!root.song?.notUploaded || !!root.song?.pendingUpload)
                onClicked: root.run("save")
            }
            MovieStyle.PanelClose {
                Layout.alignment: Qt.AlignTop
                text: "Close information"
                onClicked: root.close()
            }
        }
        ScrollArea {
            id: editorScroll
            clip: true
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            ColumnLayout {
                width: editorScroll.availableWidth
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    visible: root.loadingTags || !!root.tagError
                    MovieText {
                        Layout.fillWidth: true
                        text: root.loadingTags ? "Loading existing metadata…" : root.tagError
                        color: MovieStyle.muted
                        wrapMode: Text.Wrap
                    }
                    MovieButton {
                        objectName: "musicReloadTags"
                        text: "Reload metadata"
                        visible: !!root.tagError
                        enabled: !root.busy && !root.loadingTags
                        onClicked: root.loadFileTags()
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 16
                    rowSpacing: 10
                    uniformCellWidths: true
                    Repeater {
                        model: [
                            {
                                key: "title",
                                name: "Title"
                            },
                            {
                                key: "artist",
                                name: "Artist"
                            },
                            {
                                key: "album",
                                name: "Album"
                            },
                            {
                                key: "album_artist",
                                name: "Album artist"
                            },
                            {
                                key: "date",
                                name: "Date"
                            },
                            {
                                key: "genre",
                                name: "Genre"
                            },
                            {
                                key: "track",
                                name: "Track / total"
                            },
                            {
                                key: "disc",
                                name: "Disc / total"
                            },
                            {
                                key: "composer",
                                name: "Composer"
                            },
                            {
                                key: "comment",
                                name: "Comment"
                            }
                        ]
                        delegate: ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 4
                            MovieText {
                                text: modelData.name
                                color: MovieStyle.muted
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                MovieInput {
                                    objectName: "musicTag:" + modelData.key
                                    Layout.fillWidth: true
                                    text: root.draft[modelData.key] || ""
                                    readOnly: !root.editing || root.busy
                                    placeholderText: root.placeholder(modelData.key)
                                    Accessible.name: modelData.name
                                    onTextEdited: root.editTag(modelData.key, text)
                                    Keys.onEscapePressed: root.dismissTransient()
                                }
                                MovieIconButton {
                                    objectName: "musicClearTag:" + modelData.key
                                    visible: root.editing
                                    enabled: !root.busy
                                    iconName: "x"
                                    text: "Clear " + modelData.name.toLowerCase()
                                    onClicked: root.editTag(modelData.key, "")
                                }
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    MovieText {
                        Layout.fillWidth: true
                        text: "Lyrics"
                        font.bold: true
                    }
                    MovieButton {
                        objectName: "musicClearLyrics"
                        visible: root.editing
                        enabled: !root.busy
                        text: "Clear"
                        iconName: "x"
                        onClicked: root.editTag("lyrics", "")
                    }
                    MovieButton {
                        objectName: "musicFetchLyrics"
                        text: root.lookingUp ? "Fetching…" : "Fetch lyrics"
                        iconName: "refresh-cw"
                        enabled: !root.busy && !root.reading && !root.lookingUp && (!root.editable || !root.pathDirty)
                        onClicked: root.lookupLyrics()
                    }
                }
                TextArea {
                    objectName: "musicLyrics"
                    Layout.fillWidth: true
                    Layout.minimumHeight: 180
                    text: root.displayedLyrics
                    readOnly: !root.editing || root.busy
                    wrapMode: TextEdit.Wrap
                    color: MovieStyle.text
                    font.family: MovieStyle.fontFamily
                    font.pixelSize: MovieStyle.fontSize
                    selectByMouse: true
                    placeholderText: root.reading || root.loadingTags || root.loadingStoredLyrics ? "Loading existing lyrics…" : root.knownFields.includes("lyrics") ? "No embedded lyrics" : "Existing lyrics not loaded"
                    placeholderTextColor: MovieStyle.muted
                    background: Rectangle {
                        color: "#211b24"
                        radius: 4
                        border.color: parent.activeFocus ? MovieStyle.accent : MovieStyle.border
                    }
                    onTextChanged: if (activeFocus && !readOnly && text !== root.displayedLyrics)
                        root.editTag("lyrics", text)
                    Keys.onEscapePressed: root.dismissTransient()
                }
            }
        }
        MovieText {
            objectName: "musicInfoMessage"
            Layout.fillWidth: true
            visible: root.importantMessage && !!root.message
            text: root.message
            wrapMode: Text.Wrap
            color: MovieStyle.danger
        }
        MovieText {
            text: "Path inside Music"
            color: MovieStyle.muted
        }
        RowLayout {
            Layout.fillWidth: true
            MovieInput {
                objectName: "musicMovePath"
                Layout.fillWidth: true
                text: root.relativePath
                // A lyrics result is staged for this path; it cannot change meanwhile.
                readOnly: !root.editable || !root.originalPath || root.editing || root.busy || root.reading || root.lookingUp
                placeholderText: root.reading ? "Loading…" : "Path unavailable from the server"
                Accessible.name: "Music-relative file path"
                onTextEdited: root.relativePath = text
                Keys.onEscapePressed: root.dismissTransient()
            }
            MovieButton {
                objectName: "musicMove"
                text: "Move"
                iconName: "folder"
                enabled: root.editable && !!root.originalPath && root.pathDirty && !root.editing && !root.busy && !root.reading && !root.lookingUp
                onClicked: root.run("move")
            }
        }
    }
}
