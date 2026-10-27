import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../movies"

ColumnLayout {
    id: root
    required property var controller
    readonly property var video: controller.selected || ({})
    readonly property string accessNotice: {
        if (["private", "needs_auth"].includes(video.availability)) return "This video requires an eligible signed-in YouTube account.";
        return "";
    }
    spacing: 8
    function resetQuestion() { question.clear(); }
    MovieText {
        Layout.fillWidth: true
        text: root.video.title || ""; font.bold: true
        font.pixelSize: Math.min(root.controller.gridMode ? 36 : 48, Math.max(26, root.controller.width / 25))
        wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight
    }
    MovieText {
        Layout.fillWidth: true; color: MovieStyle.muted; wrapMode: Text.Wrap
        text: [root.video.creator, root.video.date, root.video.duration ? Math.floor(root.video.duration / 60) + " min" : "",
               root.video.views ? Number(root.video.views).toLocaleString() + " views" : ""].filter(Boolean).join("   ·   ")
    }
    Flow {
        Layout.fillWidth: true; spacing: 8
        MovieButton {
            objectName: "streamingPlay"; text: "Watch"; iconName: "play"; idleColor: MovieStyle.accent
            enabled: !root.controller.commandPending && !root.controller.playOpening && !root.accessNotice
            onClicked: root.controller.play(false)
        }
        MovieButton { text: "Listen"; iconName: "headphones"; enabled: !root.controller.commandPending && !root.accessNotice; onClicked: root.controller.play(true) }
        MovieIconButton { objectName: "streamingYouTube"; visible: !root.accessNotice; text: "Open on YouTube"; iconName: "globe"; onClicked: root.controller.openYouTube() }
        MovieButton { visible: !!root.accessNotice; text: "Open on YouTube"; iconName: "globe"; onClicked: root.controller.openYouTube() }
        MovieButton {
            objectName: "streamingSubscribe"
            visible: !!root.video.channel
            text: root.controller.followedChannel(root.video) ? "Unsubscribe" : "Subscribe"
            iconName: "video"; highlighted: !!root.controller.followedChannel(root.video)
            enabled: !root.controller.commandPending; onClicked: root.controller.toggleSubscription(root.video)
        }
    }
    Flickable {
        Layout.fillWidth: true; Layout.preferredHeight: 42; clip: true
        contentWidth: detailTabs.implicitWidth; contentHeight: height
        Row {
            id: detailTabs; spacing: 4
            Repeater {
                model: [{id:"overview",name:"Overview"},{id:"summary",name:"Summary"},{id:"chapters",name:"Chapters"},{id:"downloads",name:"Downloads"}]
                MovieTab {
                    required property var modelData
                    objectName: "streamingDetailTab:" + modelData.id
                    text: modelData.name; highlighted: root.controller.detailTab === modelData.id
                    onClicked: root.controller.detailTab = modelData.id
                }
            }
        }
    }
    MovieText {
        objectName: "streamingDetailError"; Layout.fillWidth: true
        visible: !!text; text: root.controller.detailError || root.accessNotice
        wrapMode: Text.Wrap; color: root.controller.detailError ? MovieStyle.danger : MovieStyle.muted
        maximumLineCount: 3; elide: Text.ElideRight
    }
    ScrollArea {
        id: content; Layout.fillWidth: true; Layout.fillHeight: true; clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: content.availableWidth; spacing: 12
            MovieText {
                visible: root.controller.detailTab === "overview"; Layout.fillWidth: true
                text: root.video.description || (root.controller.detailLoading ? "" : "No description available.")
                wrapMode: Text.Wrap
            }
            ColumnLayout {
                visible: root.controller.detailTab === "summary"; Layout.fillWidth: true; spacing: 10
                MovieButton {
                    objectName: "streamingSummary"; text: "Summarize video"
                    enabled: root.controller.gemini && !root.controller.commandPending && !root.accessNotice
                    onClicked: root.controller.startJob("analyze", {videoId:root.video.id})
                }
                MovieText { visible: !root.controller.gemini; Layout.fillWidth: true; text: "A Gemini API key is needed for video analysis."; color: MovieStyle.muted; wrapMode: Text.Wrap }
                RowLayout {
                    Layout.fillWidth: true
                    MovieInput {
                        id: question; objectName: "streamingQuestion"; Layout.fillWidth: true; Layout.minimumWidth: 0
                        maximumLength: 2000; placeholderText: "Ask about this video…"; enabled: root.controller.gemini && !root.accessNotice
                        onAccepted: if (ask.enabled) ask.clicked()
                    }
                    MovieButton {
                        id: ask; text: "Ask Gemini"; enabled: root.controller.gemini && !!question.text.trim() && !root.controller.commandPending && !root.accessNotice
                        onClicked: root.controller.startJob("analyze", {videoId:root.video.id, question:question.text})
                    }
                }
                MovieText { visible: !!root.controller.answer; Layout.fillWidth: true; text: root.controller.answeredQuestion; font.bold: true; wrapMode: Text.Wrap }
                TextEdit {
                    objectName: "streamingAnswer"; visible: !!root.controller.answer
                    Layout.fillWidth: true; Layout.preferredHeight: contentHeight
                    text: root.controller.answer; readOnly: true; selectByMouse: true
                    textFormat: TextEdit.MarkdownText; wrapMode: TextEdit.Wrap
                    color: MovieStyle.text; selectionColor: MovieStyle.accent
                    font.family: MovieStyle.fontFamily; font.pixelSize: MovieStyle.fontSize
                }
            }
            ColumnLayout {
                visible: root.controller.detailTab === "chapters"; Layout.fillWidth: true; spacing: 6
                MovieText { visible: !root.video.chapters?.length; text: "This video has no published chapters."; color: MovieStyle.muted }
                Repeater {
                    model: root.video.chapters || []
                    MovieButton {
                        required property var modelData
                        Layout.fillWidth: true
                        text: Math.floor(modelData.start / 60) + ":" + String(modelData.start % 60).padStart(2, "0") + "  " + modelData.title
                        enabled: !root.controller.commandPending; onClicked: root.controller.play(false, modelData.start)
                    }
                }
            }
            Flow {
                visible: root.controller.detailTab === "downloads"; Layout.fillWidth: true; spacing: 8
                MovieButton { objectName: "streamingDownload"; text: "Download video"; iconName: "download"; enabled: !root.controller.commandPending && !root.accessNotice; onClicked: root.controller.startJob("download", {videoId:root.video.id, audio:false}) }
                MovieButton { objectName: "streamingAudio"; text: "Download audio"; iconName: "music"; enabled: !root.controller.commandPending && !root.accessNotice; onClicked: root.controller.startJob("download", {videoId:root.video.id, audio:true}) }
            }
        }
    }
}
