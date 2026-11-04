pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Reminders belong to the login session: they are saved in the runtime
// directory, so shell reloads and restarts keep them and logout clears them.
Singleton {
    id: root
    readonly property alias scheduler: scheduler
    readonly property alias store: store
    property var entries: []
    property int nextId: 1
    property bool restored: false
    property var clock: () => Date.now()
    property double now: clock()
    readonly property bool hasPomodoro: entries.some(entry => entry.kind === "pomodoro")
    // Separate delivery from scheduling so tests never send real notifications.
    // Alarms are critical so Do Not Disturb still shows them until dismissed;
    // focus/break prompts are normal and follow it.
    property var deliver: (title, body, urgency) => Quickshell.execDetached(["notify-send", "--app-name=Time and weather", "--icon=alarm-clock", "--urgency=" + urgency, "--", title, escapeMarkup(body)])

    function escapeMarkup(text: string): string {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
    function validMinutes(value): bool {
        return Number.isInteger(value) && value >= 1 && value <= 1440;
    }
    // Saved entries are re-validated and copied field by field.
    function normalized(entry) {
        if (!entry || !Number.isInteger(entry.id) || entry.id < 1 || typeof entry.deadline !== "number" || !isFinite(entry.deadline))
            return null;
        if (entry.kind === "alarm" && /^\d{4}-\d{2}-\d{2}$/.test(entry.date) && /^([01]\d|2[0-3]):[0-5]\d$/.test(entry.time) && Number.isInteger(entry.zone) && typeof entry.message === "string")
            return {
                id: entry.id,
                kind: "alarm",
                deadline: entry.deadline,
                date: entry.date,
                time: entry.time,
                zone: entry.zone,
                message: entry.message.slice(0, 160)
            };
        if (entry.kind === "pomodoro" && ["focus", "break"].includes(entry.phase) && validMinutes(entry.focus) && validMinutes(entry.rest))
            return {
                id: entry.id,
                kind: "pomodoro",
                phase: entry.phase,
                focus: entry.focus,
                rest: entry.rest,
                deadline: entry.deadline
            };
        return null;
    }
    function restore(text: string): void {
        let saved = [];
        try {
            saved = text ? JSON.parse(text).entries : [];
        } catch (_) {}
        const ids = new Set();
        let pomodoro = false;
        const rows = [];
        for (const entry of Array.isArray(saved) ? saved : []) {
            const row = normalized(entry);
            if (!row || ids.has(row.id) || row.kind === "pomodoro" && pomodoro)
                continue;
            ids.add(row.id);
            pomodoro = pomodoro || row.kind === "pomodoro";
            rows.push(row);
        }
        nextId = rows.reduce((last, row) => Math.max(last, row.id), 0) + 1;
        entries = rows;
        restored = true;
    }
    function nextAlarm(time: string, at = clock(), onDate = 0): double {
        if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time))
            return 0;
        const hour = Number(time.slice(0, 2)), minute = Number(time.slice(3));
        const start = Math.floor(at / 60000) * 60000 + 60000;
        // Search actual instants so DST gaps and repeated hours use the next
        // occurrence of the requested local time rather than normalizing it.
        for (let offset = 0; offset < 48 * 60; offset++) {
            const deadline = start + offset * 60000;
            const date = new Date(deadline);
            if (date.getHours() === hour && date.getMinutes() === minute) {
                if (onDate && Qt.formatDate(date, "yyyy-MM-dd") !== Qt.formatDate(new Date(onDate), "yyyy-MM-dd"))
                    return 0;
                return deadline;
            }
        }
        return 0;
    }
    // The UTC offset at the deadline itself changes with the system timezone,
    // not with DST transitions before it.
    function zoneOffset(deadline: double): int {
        return new Date(deadline).getTimezoneOffset();
    }
    // First instant of a local date and time in the current system timezone.
    function localAlarm(date: string, time: string): double {
        const [year, month, day] = date.split("-").map(Number);
        const midnight = new Date(year, month - 1, day).getTime();
        // A time inside a DST gap becomes the normalized instant after the gap.
        return nextAlarm(time, midnight - 60000, midnight) || new Date(year, month - 1, day, Number(time.slice(0, 2)), Number(time.slice(3))).getTime();
    }
    function addAlarm(time: string, message: string, onDate = 0): bool {
        now = clock();
        const deadline = nextAlarm(time, now, onDate);
        if (!deadline)
            return false;
        entries = entries.concat([
            {
                id: nextId++,
                kind: "alarm",
                deadline,
                date: Qt.formatDate(new Date(deadline), "yyyy-MM-dd"),
                time,
                zone: zoneOffset(deadline),
                message: message.trim().slice(0, 160)
            }
        ]);
        return true;
    }
    function addPomodoro(focus, rest): bool {
        if (hasPomodoro || !Number.isInteger(focus) || !Number.isInteger(rest) || focus < 1 || focus > 1440 || rest < 1 || rest > 1440)
            return false;
        now = clock();
        entries = entries.concat([
            {
                id: nextId++,
                kind: "pomodoro",
                phase: "focus",
                focus,
                rest,
                deadline: now + focus * 60000
            }
        ]);
        return true;
    }
    function stop(id: int): void {
        entries = entries.filter(entry => entry.id !== id);
    }
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
        for (let entry of entries) {
            if (entry.kind === "alarm" && zoneOffset(entry.deadline) !== entry.zone) {
                // The timezone changed: keep the alarm's local date and time.
                // One that has already passed in the new zone is due now.
                const deadline = localAlarm(entry.date, entry.time);
                entry = Object.assign({}, entry, {
                    deadline,
                    zone: zoneOffset(deadline)
                });
            }
            if (entry.deadline > at) {
                next.push(entry);
                continue;
            }
            if (entry.kind === "alarm") {
                deliver(qsTr("Reminder"), entry.message || qsTr("Your reminder is due."), "critical");
            } else {
                const phase = entry.phase === "focus" ? "break" : "focus";
                const minutes = phase === "break" ? entry.rest : entry.focus;
                deliver(phase === "break" ? qsTr("Time for a break") : qsTr("Time to focus"), phase === "break" ? qsTr("Take a %1-minute break.").arg(minutes) : qsTr("Focus for %1 minutes.").arg(minutes), "normal");
                // After sleep, send one reminder and start the next phase now;
                // never replay a backlog of missed focus/break notifications.
                next.push(Object.assign({}, entry, {
                    phase,
                    deadline: at + minutes * 60000
                }));
            }
        }
        if (JSON.stringify(next) !== JSON.stringify(entries))
            entries = next;
    }
    onEntriesChanged: if (restored)
        store.setText(JSON.stringify({
            entries
        }))
    // Overdue alarms fire once on the first tick; an overdue focus cycle sends
    // one prompt and starts its next phase.
    Component.onCompleted: restore(store.text())
    Timer {
        id: scheduler
        interval: 1000
        repeat: true
        running: root.entries.length > 0
        onTriggered: root.tick()
    }
    FileView {
        id: store
        path: {
            const base = Quickshell.env("XDG_RUNTIME_DIR") || "";
            return base.startsWith("/") ? base + "/desktop-shell/reminders.json" : "";
        }
        blockLoading: true
        atomicWrites: true
        printErrors: false
    }
}
