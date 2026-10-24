import QtQuick
import "../../ui"
import QtQuick.Controls
import QtQuick.Layouts

// Floats above the module; progress never participates in its layout.
Popup {
    id: root
    function fontSize(value) { return Math.round(value * MovieStyle.fontSize / 14); }
    property var jobs: []
    property string notificationTitle: "Movies"
    property var dismissedJobs: []
    readonly property var shownJobs: jobs.filter(job => !dismissedJobs.includes(String(job.job_id)))
    readonly property bool hasFinishedJobs: shownJobs.some(job => ["finished", "failed", "cancelled"].includes(job.state))
    readonly property int activeCount: jobs.filter(j => j.state === "running" || j.state === "queued").length
    property bool retryAvailable: false
    readonly property bool hasActivity: shownJobs.length > 0 || retryAvailable
    property string retryText: "Retry"
    signal retryRequested()
    signal actionRequested(var job)
    signal secondaryActionRequested(var job)
    signal cancelRequested(string jobId)
    width: Math.min(430, parent ? parent.width - 24 : 430)
    height: Math.min(implicitHeight, parent ? parent.height - 24 : 600)
    x: parent ? parent.width - width - 12 : 0
    y: parent ? parent.height - height - 12 : 0
    padding: 14
    margins: 12
    z: 100
    modal: false
    focus: false
    closePolicy: Popup.NoAutoClose
    popupType: Popup.Item

    function notify(text, error) {
        if (!text) return;
        // Status is retained in the activity panel; no detached notifier.
        showActivity();
    }
    function showActivity() {
        if (hasActivity && parent && parent.visible) open();
    }
    onHasActivityChanged: if (!hasActivity) { dismiss.stop(); close(); }
    function dismissJob(jobId) {
        const job = jobs.find(job => String(job.job_id) === String(jobId));
        if (!job || ["queued", "running"].includes(job.state)) return;
        dismissedJobs = dismissedJobs.filter(id => id !== String(jobId)).concat([String(jobId)]);
    }
    function dismissFinished() {
        const ids = shownJobs.filter(job => ["finished", "failed", "cancelled"].includes(job.state)).map(job => String(job.job_id));
        dismissedJobs = dismissedJobs.concat(ids);
    }
    onJobsChanged: dismissedJobs = dismissedJobs.filter(id => jobs.some(job => String(job.job_id) === id && !["queued", "running"].includes(job.state)))
    function sizeLabel(value) {
        if (value >= 1073741824) return (value / 1073741824).toFixed(1) + " GB";
        if (value >= 1048576) return (value / 1048576).toFixed(1) + " MB";
        if (value >= 1024) return (value / 1024).toFixed(1) + " KB";
        return Math.floor(value || 0) + " B";
    }
    function remaining(job) {
        if (job.eta === null || job.eta === undefined || job.eta < 1) return "Estimating time…";
        const seconds = Math.ceil(job.eta);
        return seconds < 60 ? seconds + "s remaining" : Math.ceil(seconds / 60) + "m remaining";
    }
    onActiveCountChanged: { if (activeCount > 0) { dismiss.stop(); showActivity(); } else if (visible) dismiss.restart(); }
    Connections {
        target: root.parent
        function onVisibleChanged() {
            if (!root.parent.visible) root.close();
            else if (root.activeCount) root.showActivity();
        }
    }
    Timer { id: dismiss; interval: 7000; onTriggered: { if (!root.activeCount) root.close(); } }
    background: Rectangle { radius: MovieStyle.controlRadius; color: MovieStyle.surface; border.color: MovieStyle.border }
    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            MovieIcon { name: root.activeCount ? "download" : "bell"; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
            MovieText { text: root.activeCount ? "Activity · " + root.activeCount + " active" : "Activity"; Layout.fillWidth: true; font.weight: Font.DemiBold }
            MovieIconButton { objectName: "dismissFinishedActivity"; visible: root.hasFinishedJobs; iconName: "trash-2"; text: "Dismiss finished activity"; implicitWidth: 30; implicitHeight: 30; onClicked: root.dismissFinished() }
            MovieIconButton { iconName: "x"; text: "Hide activity"; implicitWidth: 30; implicitHeight: 30; onClicked: root.close() }
        }
        MovieButton { objectName: "activityRetry"; visible: root.retryAvailable; text: root.retryText; onClicked: root.retryRequested() }
        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(360, jobColumn.implicitHeight)
            visible: root.shownJobs.length > 0
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                id: jobColumn
                width: parent.width
                spacing: 12
                Repeater {
                    model: root.shownJobs.slice().reverse().slice(0, 16)
                    delegate: ColumnLayout {
                        id: row
                        required property var modelData
                        readonly property bool active: ["queued", "running"].includes(modelData.state)
                        Layout.fillWidth: true
                        spacing: 4
                        RowLayout {
                            Layout.fillWidth: true
                            MovieText { Layout.fillWidth: true; text: row.modelData.title; elide: Text.ElideRight; font.weight: Font.Medium }
                            MovieIconButton {
                                objectName: "cancelActivity:" + row.modelData.job_id
                                visible: row.active && row.modelData.cancellable !== false
                                enabled: !row.modelData.cancel_requested
                                iconName: "x"; text: "Cancel transfer"; implicitWidth: 28; implicitHeight: 28
                                onClicked: root.cancelRequested(row.modelData.job_id)
                            }
                            MovieIconButton {
                                objectName: "dismissActivity:" + row.modelData.job_id
                                visible: !row.active
                                iconName: "x"; text: "Dismiss activity"; implicitWidth: 28; implicitHeight: 28
                                onClicked: root.dismissJob(row.modelData.job_id)
                            }
                        }
                        MovieText { Layout.fillWidth: true; text: row.modelData.error || row.modelData.detail || row.modelData.state; elide: Text.ElideMiddle; color: row.modelData.state === "failed" ? MovieStyle.danger : MovieStyle.muted }
                        MovieButton { objectName: "activityAction:" + row.modelData.job_id; visible: !!row.modelData.actionLabel; text: row.modelData.actionLabel || ""; onClicked: root.actionRequested(row.modelData) }
                        MovieButton { visible: !!row.modelData.secondaryActionLabel; text: row.modelData.secondaryActionLabel || ""; onClicked: root.secondaryActionRequested(row.modelData) }
                        ProgressBar {
                            visible: row.active && row.modelData.progressVisible !== false
                            Layout.fillWidth: true
                            indeterminate: !row.modelData.total
                            from: 0; to: Math.max(1, row.modelData.total || 0); value: row.modelData.done || 0
                        }
                        MovieText {
                            visible: row.active && (row.modelData.total > 0 || row.modelData.done > 0)
                            Layout.fillWidth: true
                            text: (row.modelData.unit === "tracks"
                                ? Number(row.modelData.done || 0).toFixed(1) + " / " + row.modelData.total + " tracks"
                                : root.sizeLabel(row.modelData.done) + (row.modelData.total ? " / " + root.sizeLabel(row.modelData.total) : " transferred")
                                    + (row.modelData.speed ? " · " + root.sizeLabel(row.modelData.speed) + "/s" : ""))
                                + (row.modelData.total ? " · " + root.remaining(row.modelData) : "")
                            color: MovieStyle.muted
                            font.pixelSize: fontSize(11)
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
    }
}
