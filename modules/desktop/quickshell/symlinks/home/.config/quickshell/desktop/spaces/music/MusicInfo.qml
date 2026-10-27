import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Window
import QtQml.Models
import "../../ui"
import "../movies"

Popup {
    id: root
    objectName: "musicInformation"
    required property var files
    required property var catalogue
    property var coverService
    property var song: null
    property var original: ({})
    property var draft: ({})
    property var fileSignature: []
    property string originalPath: ""
    property string relativePath: ""
    property string fileInfo: ""
    property string coverDraft: ""
    property string fetchedLyrics: ""
    property string message: ""
    property bool importantMessage: false
    property string jobId: ""
    property string operation: ""
    property bool busy: false
    property bool reading: false
    property bool previewLoaded: false
    property bool lookingUp: false
    property bool editing: false
    property bool ready: false
    property int generation: 0
    readonly property bool editable: song?.source === "nextcloud" || song?.source === "music-local"
    readonly property bool dirty: editing && (!!coverDraft || JSON.stringify(original) !== JSON.stringify(draft))
    readonly property bool pathDirty: relativePath !== originalPath
    property alias coverPicker: coverChooser
    signal saved(var song, var result)
    width: Math.min(820, parent.width - 40)
    height: Math.min(900, parent.height - 40)
    anchors.centerIn: parent
    modal: true
    focus: true
    padding: 20
    closePolicy: Popup.NoAutoClose
    palette.window: MovieStyle.surface
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
    background: Rectangle { color: MovieStyle.surface; radius: 8; border.color: MovieStyle.border }

    function previewTags(item) {
        return {title:item.title || "", artist:item.artist || "", album:item.album || "",
                album_artist:item.albumArtist || "", date:item.releaseDate || "",
                genre:(item.genreNames || []).join("; "), track:String(item.trackNumber || ""),
                disc:String(item.discNumber || ""), composer:"", comment:"", lyrics:item.lyrics || ""};
    }
    function setMessage(text, important) {
        importantMessage = !!important;
        message = text || "";
    }
    function showSong(item) {
        if (busy || (song && song.id === item.id && song.source === item.source && (editing || reading || previewLoaded))) { open(); return; }
        if (dirty) { setMessage("Save or cancel your edits before opening another song.", true); open(); return; }
        const token = ++generation;
        song = item; lookingUp = false; editing = false; ready = false; reading = true; previewLoaded = false;
        coverDraft = ""; fetchedLyrics = ""; fileSignature = []; setMessage("");
        original = previewTags(item); draft = Object.assign({}, original);
        originalPath = String(item.serverPath || "").replace(/^\/+/, ""); relativePath = originalPath;
        fileInfo = item.fileInfo || ""; open();
        catalogue.request("song-info", {song:item, lane:"info"}, (result, failure) => {
            if (token !== generation) return;
            reading = false;
            if (failure) { setMessage(failure, true); return; }
            previewLoaded = true;
            song = Object.assign({}, song, result.song || {});
            original = Object.assign({}, original, result.tags || {}); draft = Object.assign({}, original);
            originalPath = result.relativePath || originalPath; relativePath = originalPath;
            fileInfo = result.fileInfo || fileInfo;
        });
    }
    function prepare() {
        if (editable && !editing && !busy && !reading && !pathDirty && originalPath) run("info");
    }
    function chooseCover(file) {
        if (file && editing && ready && !busy) coverDraft = String(file);
    }
    function run(action) {
        if (!song || busy || reading || !editable) return;
        if (action === "save" && (!editing || !ready)) return;
        if (action === "move" && (editing || !originalPath || !pathDirty)) return;
        if (action === "info" && (editing || pathDirty || !originalPath)) return;
        ++generation; lookingUp = false; busy = true; jobId = ""; operation = action;
        setMessage(action === "info" ? "Preparing metadata editing…" : action === "move" ? "Moving…" : "Saving locally and on Nextcloud…");
        const changes = ({});
        if (action === "save") for (const key of Object.keys(draft)) if (draft[key] !== original[key]) changes[key] = draft[key];
        const args = {action:action, song:song, title:action === "info" ? "Prepare metadata editing" : action === "move" ? "Move song" : "Save metadata"};
        if (action === "save") { args.tags = changes; args.artwork = coverDraft || null; args.signature = fileSignature; }
        if (action === "move") args.relativePath = relativePath;
        files.startJob("file-job", args, (identifier, error) => {
            if (error) complete({}, error);
            else jobId = identifier;
        });
    }
    function complete(result, failure) {
        const action = result.action || operation;
        busy = false; jobId = ""; operation = "";
        if (failure) { setMessage(failure, true); return; }
        if (action === "info") {
            original = Object.assign({}, previewTags(song), result.tags || {});
            draft = Object.assign({}, original);
            if (!draft.lyrics && fetchedLyrics) draft = Object.assign({}, draft, {lyrics:fetchedLyrics});
            fileSignature = result.signature || []; fileInfo = result.fileInfo || fileInfo;
            originalPath = result.relativePath || originalPath; relativePath = originalPath;
            song = Object.assign({}, song, {local:true, localPath:result.path, pendingUpload:result.pendingUpload});
            ready = true; editing = true; setMessage("");
            return;
        }
        const rel = result.relativePath || originalPath;
        song = Object.assign({}, song, {serverPath:"/" + rel, localPath:result.local === false ? "" : result.path || song.localPath,
            local:result.local !== false, notUploaded:result.synced ? false : !!song.notUploaded,
            pendingUpload:action === "save" ? !result.synced : !!song.pendingUpload, coverVersion:Date.now()});
        originalPath = rel; relativePath = rel;
        if (action === "save") {
            original = Object.assign({}, draft, result.tags || {}); draft = Object.assign({}, original);
            fileSignature = result.signature || fileSignature; fileInfo = result.fileInfo || fileInfo;
            coverDraft = ""; fetchedLyrics = "";
            if (result.synced) { editing = false; ready = false; }
        }
        setMessage(result.error ? "Saved locally. " + result.error : action === "move" ? "Song moved." :
            result.synced ? "Saved locally and on Nextcloud." : result.message || "Saved locally. The server file was not updated.", !!result.error || (action !== "move" && !result.synced));
        saved(song, result);
    }
    function cancelEdits() {
        if (busy) return;
        ++generation; lookingUp = false; editing = false; ready = false;
        coverDraft = ""; fetchedLyrics = ""; draft = Object.assign({}, original); setMessage("");
    }
    function lookupLyrics() {
        if (!song || busy || reading || lookingUp) return;
        const token = ++generation, previous = String(draft.lyrics || "");
        lookingUp = true; setMessage("Fetching lyrics…");
        catalogue.request("lyrics", {song:Object.assign({}, song, draft), refresh:true, lane:"info"}, (result, failure) => {
            if (token !== generation) return;
            lookingUp = false;
            if (String(draft.lyrics || "") !== previous) return;
            if (failure || !result?.available) { setMessage(failure || "No matching lyrics found.", !!failure); return; }
            fetchedLyrics = result.lyrics; draft = Object.assign({}, draft, {lyrics:result.lyrics});
            setMessage(editing ? "Lyrics loaded. Save to keep them in the file and on Nextcloud." : "Lyrics loaded. Edit metadata to save them.");
        });
    }
    function restoreFocus() {
        Qt.callLater(() => { if (visible) contentItem.forceActiveFocus(); });
    }
    function dismissTransient() {
        if (coverChooser.visible) coverChooser.reject();
        else if (editing && !busy) cancelEdits();
        else close();
        return true;
    }
    onClosed: { coverChooser.close(); ++generation; lookingUp = false; reading = false; }
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
        onAccepted: { root.chooseCover(selectedFile); root.restoreFocus(); }
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
            Layout.fillWidth: true; spacing: 16
            Item {
                Layout.preferredWidth: 88; Layout.preferredHeight: 88
                MusicCover { objectName:"musicInfoCover"; anchors.fill:parent; record:root.song; previewSource:root.coverDraft; service:root.coverService; fetchEnabled:root.visible }
                MovieIconButton {
                    objectName:"musicChooseCover"; anchors.right:parent.right; anchors.bottom:parent.bottom
                    anchors.rightMargin:4; anchors.bottomMargin:4
                    implicitWidth:32; implicitHeight:32; horizontalPadding:6; verticalPadding:6
                    iconName:"pencil"; text:"Edit cover art"; iconColor:MovieStyle.text
                    visible:root.editing && root.ready; enabled:!root.busy
                    onClicked:coverChooser.open()
                }
            }
            ColumnLayout {
                objectName: "musicInfoHeading"
                Layout.fillWidth:true; Layout.minimumWidth:0; spacing:5
                MovieText { objectName:"musicInfoTitle"; Layout.fillWidth:true; text:"Song information"; font.bold:true; font.pixelSize:MovieStyle.fontSize * 1.3 }
                MovieText { objectName:"musicFileInfo"; Layout.fillWidth:true; visible:!!root.fileInfo; text:root.fileInfo; color:MovieStyle.muted; wrapMode:Text.Wrap }
            }
            MovieButton {
                objectName:root.editing ? "musicCancelMetadata" : "musicEditMetadata"
                visible:root.editable; text:root.editing ? "Cancel" : "Edit metadata"; iconName:root.editing ? "x" : "pencil"
                enabled:!root.busy && (root.editing || (!root.reading && !!root.originalPath && !root.pathDirty))
                onClicked:root.editing ? root.cancelEdits() : root.prepare()
            }
            MovieButton { objectName:"musicSaveTags"; visible:root.editing; text:"Save"; iconName:"save"; enabled:root.editing && root.ready && !root.busy && (root.dirty || !!root.song?.notUploaded || !!root.song?.pendingUpload); onClicked:root.run("save") }
            MovieIconButton { iconName:"x"; text:"Close information"; onClicked:root.close() }
        }
        ScrollArea {
            id:editorScroll; clip:true
            Layout.fillWidth:true; Layout.fillHeight:true; contentWidth:availableWidth
            ColumnLayout {
                width:editorScroll.availableWidth; spacing:12
                GridLayout {
                    Layout.fillWidth:true; columns:2; columnSpacing:16; rowSpacing:10; uniformCellWidths:true
                    Repeater {
                        model:[{key:"title",name:"Title"},{key:"artist",name:"Artist"},{key:"album",name:"Album"},{key:"album_artist",name:"Album artist"},{key:"date",name:"Date"},{key:"genre",name:"Genre"},{key:"track",name:"Track / total"},{key:"disc",name:"Disc / total"},{key:"composer",name:"Composer"},{key:"comment",name:"Comment"}]
                        delegate:ColumnLayout {
                            required property var modelData
                            Layout.fillWidth:true; spacing:4
                            MovieText { text:modelData.name; color:MovieStyle.muted }
                            MovieInput {
                                objectName:"musicTag:" + modelData.key; Layout.fillWidth:true
                                text:root.draft[modelData.key] || ""; readOnly:!root.editing || !root.ready || root.busy
                                placeholderText:root.reading ? "Loading…" : root.editing ? "No value" : "Not provided"
                                Accessible.name:modelData.name
                                onTextEdited:if (root.editing) root.draft = Object.assign({},root.draft,{[modelData.key]:text})
                                Keys.onEscapePressed:root.dismissTransient()
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth:true
                    MovieText { Layout.fillWidth:true; text:"Lyrics"; font.bold:true }
                    MovieButton { objectName:"musicFetchLyrics"; text:root.lookingUp ? "Fetching…" : "Fetch lyrics"; iconName:"refresh-cw"; enabled:!root.busy && !root.reading && !root.lookingUp; onClicked:root.lookupLyrics() }
                }
                TextArea {
                    objectName:"musicLyrics"; Layout.fillWidth:true; Layout.minimumHeight:180
                    text:root.draft.lyrics || ""; readOnly:!root.editing || !root.ready || root.busy
                    wrapMode:TextEdit.Wrap; color:MovieStyle.text; font.family:MovieStyle.fontFamily; font.pixelSize:MovieStyle.fontSize; selectByMouse:true
                    placeholderText:root.reading ? "Loading…" : "No lyrics loaded"; placeholderTextColor:MovieStyle.muted
                    background:Rectangle { color:"#211b24"; radius:4; border.color:parent.activeFocus ? MovieStyle.accent : MovieStyle.border }
                    onTextChanged:if (activeFocus && !readOnly) root.draft = Object.assign({},root.draft,{lyrics:text})
                    Keys.onEscapePressed:root.dismissTransient()
                }
            }
        }
        MovieText { objectName:"musicInfoMessage"; Layout.fillWidth:true; visible:root.importantMessage && !!root.message; text:root.message; wrapMode:Text.Wrap; color:MovieStyle.danger }
        MovieText { text:"Path inside Music"; color:MovieStyle.muted }
        RowLayout {
            Layout.fillWidth:true
            MovieInput {
                objectName:"musicMovePath"; Layout.fillWidth:true; text:root.relativePath
                readOnly:!root.editable || !root.originalPath || root.editing || root.busy || root.reading
                placeholderText:root.reading ? "Loading…" : "Path unavailable from the server"
                Accessible.name:"Music-relative file path"
                onTextEdited:root.relativePath = text
                Keys.onEscapePressed:root.dismissTransient()
            }
            MovieButton { objectName:"musicMove"; text:"Move"; iconName:"folder"; enabled:root.editable && !!root.originalPath && root.pathDirty && !root.editing && !root.busy && !root.reading; onClicked:root.run("move") }
        }
    }
}
