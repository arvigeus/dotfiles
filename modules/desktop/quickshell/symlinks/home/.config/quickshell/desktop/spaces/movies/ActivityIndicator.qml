import "../../ui" as Desktop
import QtQuick

Item {
    id: root

    property bool active: true
    property string spinnerName: ""
    property var tasks: []
    property var jobs: []
    readonly property var currentTasks: {
        const next = (tasks || []).filter(Boolean);
        for (const job of jobs || []) {
            if (job.state !== "queued" && job.state !== "running" && job.active !== true)
                continue;

            const title = job.title || "Transfer";
            const percent = job.total > 0 ? " · " + Math.min(100, Math.round(job.done * 100 / job.total)) + "%" : job.progress > 0 ? " · " + Math.round(job.progress * 100) + "%" : "";
            next.push({
                "key": "job:" + String(job.job_id || job.id),
                "text": title + (job.detail ? " · " + job.detail : "") + percent
            });
        }
        return next;
    }
    readonly property bool busy: currentTasks.length > 0
    readonly property bool running: active && busy
    readonly property string tooltipText: running ? currentTasks.map(task => {
        return task.text;
    }).join("\n") : ""

    function task(pending, key, text) {
        return pending ? {
            "key": key,
            "text": text
        } : null;
    }

    objectName: "spaceActivityIndicator"
    visible: running
    implicitWidth: 28
    implicitHeight: 28
    Accessible.role: Accessible.StaticText
    Accessible.name: tooltipText

    MovieSpinner {
        objectName: root.spinnerName
        anchors.fill: parent
        running: root.running
        visible: running
    }

    Desktop.PassiveToolTip {
        objectName: "spaceActivityTooltip"
        target: root
        text: root.tooltipText
        maximumLineCount: 24
    }
}
