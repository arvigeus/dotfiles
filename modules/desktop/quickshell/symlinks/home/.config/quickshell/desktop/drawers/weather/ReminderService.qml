pragma Singleton
import QtQuick
import Quickshell

QtObject {
    id: root
    property var entries: []
    property int nextId: 1
    property var clock: () => Date.now()
    property double now: clock()
    readonly property bool hasPomodoro: entries.some(entry => entry.kind === "pomodoro")
    // Separate delivery from scheduling so tests never send real notifications.
    property var deliver: (title, body) => Quickshell.execDetached([
        "notify-send", "--app-name=Time and weather", "--icon=alarm-clock", "--urgency=normal",
        "--", title, escapeMarkup(body)
    ])

    function escapeMarkup(text: string): string {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function nextAlarm(time: string, at = clock(), onDate = 0): double {
        if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) return 0;
        const hour = Number(time.slice(0, 2)), minute = Number(time.slice(3));
        const start = Math.floor(at / 60000) * 60000 + 60000;
        // Search actual instants so DST gaps and repeated hours use the next
        // occurrence of the requested local time rather than normalizing it.
        for (let offset = 0; offset < 48 * 60; offset++) {
            const deadline = start + offset * 60000;
            const date = new Date(deadline);
            if (date.getHours() === hour && date.getMinutes() === minute) {
                if (onDate && Qt.formatDate(date, "yyyy-MM-dd") !== Qt.formatDate(new Date(onDate), "yyyy-MM-dd")) return 0;
                return deadline;
            }
        }
        return 0;
    }
    function addAlarm(time: string, message: string, onDate = 0): bool {
        now = clock();
        const deadline = nextAlarm(time, now, onDate);
        if (!deadline) return false;
        entries = entries.concat([{id: nextId++, kind: "alarm", deadline, message: message.trim().slice(0, 160)}]);
        return true;
    }
    function addPomodoro(focus, rest): bool {
        if (hasPomodoro || !Number.isInteger(focus) || !Number.isInteger(rest)
            || focus < 1 || focus > 1440 || rest < 1 || rest > 1440) return false;
        now = clock();
        entries = entries.concat([{id: nextId++, kind: "pomodoro", phase: "focus", focus, rest, deadline: now + focus * 60000}]);
        return true;
    }
    function stop(id: int): void { entries = entries.filter(entry => entry.id !== id); }
    function remaining(entry): string {
        const seconds = Math.max(0, Math.ceil((entry.deadline - now) / 1000));
        return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
    }
    function dueLabel(deadline: double): string {
        const date = new Date(deadline);
        const today = Qt.formatDate(date, "yyyy-MM-dd") === Qt.formatDate(new Date(now), "yyyy-MM-dd");
        return Qt.formatDateTime(date, today ? "HH:mm" : "ddd HH:mm");
    }
    function tick(at = clock()): void {
        now = at;
        const next = [];
        for (const entry of entries) {
            if (entry.deadline > at) { next.push(entry); continue; }
            if (entry.kind === "alarm") {
                deliver(qsTr("Reminder"), entry.message || qsTr("Your reminder is due."));
            } else {
                const phase = entry.phase === "focus" ? "break" : "focus";
                const minutes = phase === "break" ? entry.rest : entry.focus;
                deliver(phase === "break" ? qsTr("Time for a break") : qsTr("Time to focus"),
                    phase === "break" ? qsTr("Take a %1-minute break.").arg(minutes) : qsTr("Focus for %1 minutes.").arg(minutes));
                // After sleep, send one reminder and start the next phase now;
                // never replay a backlog of missed focus/break notifications.
                next.push(Object.assign({}, entry, {phase, deadline: at + minutes * 60000}));
            }
        }
        if (JSON.stringify(next) !== JSON.stringify(entries)) entries = next;
    }
    readonly property Timer scheduler: Timer {
        interval: 1000; repeat: true; running: root.entries.length > 0
        onTriggered: root.tick()
    }
}
