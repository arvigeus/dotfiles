pragma Singleton
import QtQuick
import Quickshell.Io

QtObject {
    id: root
    property bool active: false
    property bool started: false
    property string month: Qt.formatDate(new Date(), "yyyy-MM")
    property var base: ({state: "loading", events: [], tasks: [], calendars: [], stale: false, updated: 0, eventsReady: false, tasksReady: false, account_id: ""})
    property var state: base
    property var months: ({})
    property string sourceId: ""
    property var transactions: []
    property var settling: []
    property var failedDrafts: []
    readonly property var failedDraft: failedDrafts.find(request => request.account_id === (base.account_id || "")) ?? null
    property string error: ""
    property int generation: 0
    property int nextId: 0
    property string pending: ""
    property bool statusPending: false
    property bool reading: false
    property bool fetching: false
    property bool writing: false
    readonly property bool refreshing: reading || fetching
    readonly property bool busy: refreshing || writing || transactions.length > 0
    readonly property string backend: decodeURIComponent(Qt.resolvedUrl("backend.py").toString().replace(/^file:\/\//, ""))
    signal submitted(var request)
    signal saved()
    signal writeFailed(var request)

    function clone(value: var): var { return JSON.parse(JSON.stringify(value)); }
    function range(key = month): var {
        const date = new Date(key + "-01T12:00:00");
        return {start: key + "-01", end: Qt.formatDate(new Date(date.getFullYear(), date.getMonth() + 1, 1), "yyyy-MM-dd")};
    }
    function taskKey(row: var): string {
        return (row.href || row._localId || row.uid || row.summary) + "#" + (row.recurrence_id || (row.exception ? row.due || row.start_date : ""));
    }
    function sortRows(data: var): var {
        data.tasks.sort((a, b) => (a.due === "") - (b.due === "") || (a.due || "").localeCompare(b.due || "") || a.summary.localeCompare(b.summary));
        data.events.sort((a, b) => a.start.localeCompare(b.start));
        data.task_count = data.tasks.filter(row => !row.completed).length;
        return data;
    }
    function replaceResource(data: var, request: var, rows: var, href: string): var {
        const field = request.kind === "VTODO" ? "tasks" : "events";
        return sortRows(Object.assign({}, data, {
            tasks: field === "tasks" ? data.tasks.filter(row => row.href !== href && row._localId !== request.entry._localId).concat(rows) : data.tasks.slice(),
            events: field === "events" ? data.events.filter(row => row.href !== href && row._localId !== request.entry._localId).concat(rows) : data.events.slice()
        }));
    }
    function optimisticRows(request: var): var {
        if (request.op === "delete") return [];
        const entry = request.entry;
        const field = request.kind === "VTODO" ? "tasks" : "events";
        const current = (base[field] || []).find(row => row.href && row.href === entry.href && !row.exception) || {};
        const collection = base.calendars.find(row => row.slug === entry.collection);
        const item = Object.assign({}, current, entry, {_pending: true});
        if (request.kind === "VTODO") {
            item.uid = item.uid || entry._localId; item.list_slug = entry.collection;
            item.list = collection?.name || item.list || "";
            item.due = item.due || ""; item.start_date = item.start_date || "";
            item.completed = request.op === "complete" ? request.completed : item.status === "COMPLETED" || item.percent === 100;
            item.status = item.completed ? "COMPLETED" : request.op === "complete" ? "NEEDS-ACTION" : item.status || "NEEDS-ACTION";
            item.percent = request.op === "complete" ? (item.completed ? 100 : 0) : item.percent || 0;
            item.recurring = !!item.recurrence_rule; item.editable = true; item.actionable = true;
            return [item];
        }
        item.calendar_slug = entry.collection; item.calendar = collection?.name || item.calendar || "";
        item.date = entry.start_date; item.last_date = entry.end_date;
        const end = new Date(entry.end_date + "T12:00:00");
        end.setDate(end.getDate() + 1);
        item.start = entry.start_date + "T" + (entry.all_day ? "00:00:00" : entry.start_time + ":00");
        item.end = entry.all_day ? Qt.formatDate(end, "yyyy-MM-dd") + "T00:00:00" : entry.end_date + "T" + entry.end_time + ":00";
        item.editable = true;
        return [item];
    }
    function render(): void {
        let data = base;
        for (const request of settling.concat(transactions)) {
            if (request.account_id !== (base.account_id || "")) continue;
            data = replaceResource(data, request, request.optimistic, request.entry.href || "");
        }
        state = data;
    }
    function remember(): void {
        const values = Object.assign({}, months, {[month]: base});
        const keys = Object.keys(values);
        while (keys.length > 12) delete values[keys.shift()];
        months = values;
    }
    function isPending(entry: var): bool {
        return !!entry?._pending || transactions.some(request => entry?.href ? request.entry.href === entry.href : entry?._localId && request.entry._localId === entry._localId);
    }
    function dismissDraft(entry: var): void {
        failedDrafts = failedDrafts.filter(request => entry?.href ? request.entry.href !== entry.href : request.entry._localId !== entry?._localId);
    }
    function start(): void {
        if (started) return;
        started = true; refresh();
    }
    function refresh(force = false): void {
        if (!active && !started) return;
        if (force) { error = ""; pending = "fetch"; }
        else statusPending = true;
        pump();
    }
    function mutate(op: string, kind: string, entry: var, completed = false): void {
        if (isPending(entry) || entry?._needsSync) return;
        if (entry?._accountId && entry._accountId !== (base.account_id || "")) {
            error = qsTr("The account changed. Reopen this item before saving."); return;
        }
        const value = clone(entry);
        value._accountId = base.account_id || "";
        value._localId = value._localId || "local-" + (++nextId);
        const request = Object.assign({op, kind, entry: value, completed, account_id: base.account_id || ""}, range());
        request.optimistic = optimisticRows(request);
        generation++; error = ""; dismissDraft(value);
        transactions = transactions.concat([request]);
        render(); submitted(request); pump();
    }
    function accept(data: var, key: string, fresh = false): void {
        const source = data.account_id || "";
        if (source !== sourceId) {
            sourceId = source; months = {}; settling = [];
            base = {state: "loading", events: [], tasks: [], calendars: [], updated: 0, eventsReady: false, tasksReady: false, account_id: source};
            render();
        }
        if (fresh && !data.stale) settling = settling.filter(request => request.account_id !== source ||
            (request.kind === "VEVENT" && key !== request.start.slice(0, 7) && !data.events.some(row => row.href === request.entry.href)));
        months = Object.assign({}, months, {[key]: data});
        if (key !== month) return;
        base = data; render();
        if (data.due && (!fetching || fetcher.month !== key || fetcher.generation !== generation)) pending = "fetch";
    }
    function receiveRead(text: string, process: var): void {
        try {
            const result = JSON.parse(text);
            process.received = true;
            if (process.generation !== generation) { if (process.month === month) statusPending = true; return; }
            if (!result.ok) {
                if (process.month === month && !base.tasksReady && !base.eventsReady) error = result.error;
                return;
            }
            if (result.data.superseded) { statusPending = true; return; }
            if (process === fetcher && process.request.account_id && result.data.account_id !== (base.account_id || "")) {
                statusPending = true; return;
            }
            // Never apply a disk snapshot on top of pending local changes.
            if (transactions.length) { statusPending = true; return; }
            accept(result.data, process.month, process === fetcher);
        } catch (_) {
            if (!base.tasksReady && !base.eventsReady) error = qsTr("Could not read calendar data.");
        }
    }
    function readExited(process: var): void {
        if (process.received || process.month !== month || process.generation !== generation) return;
        const message = qsTr("Calendar worker stopped unexpectedly.");
        if (!base.tasksReady && !base.eventsReady) error = message;
        else { base = Object.assign({}, base, {stale: true, error: message}); render(); }
    }
    function finishWrite(result: var): void {
        const request = writer.request;
        const remaining = transactions.filter(item => item !== request);
        if (!result.ok) {
            const reason = result.error || qsTr("Calendar worker stopped unexpectedly.");
            const message = request.op === "complete"
                ? (request.completed ? qsTr("Could not complete task: %1") : qsTr("Could not reopen task: %1")).arg(reason)
                : (request.op === "delete" ? qsTr("Could not delete item: %1") : qsTr("Could not save item: %1")).arg(reason);
            error = [message, request.entry.summary].filter(Boolean).join(" · ");
            if (request.op === "save") failedDrafts = failedDrafts.concat([request]);
            pending = "fetch";
            transactions = remaining; render(); writeFailed(request);
            return;
        }
        const patch = result.data;
        if (patch.account_id && patch.account_id !== (base.account_id || "")) {
            transactions = remaining; render(); statusPending = true; return;
        }
        // Older workers may only acknowledge the write; keep its optimistic row
        // until a quiet reconciliation can establish the current resource/ETag.
        const reconcile = patch.reconcile || !Array.isArray(patch.tasks) || !Array.isArray(patch.events);
        const rows = reconcile ? request.optimistic.map(row => Object.assign({}, row, {
            href: patch.href || row.href, _pending: false, _needsSync: true, editable: false, actionable: false
        })) : patch[request.kind === "VTODO" ? "tasks" : "events"];
        const values = Object.assign({}, months);
        for (const key of Object.keys(values)) {
            if ((values[key].account_id || "") === request.account_id)
                values[key] = replaceResource(values[key], request, rows, patch.href || request.entry.href || "");
        }
        months = values;
        base = replaceResource(base, request, rows, patch.href || request.entry.href || "");
        transactions = remaining;
        if (reconcile) {
            settling = settling.concat([Object.assign({}, request, {entry: Object.assign({}, request.entry, {href: patch.href || request.entry.href}), optimistic: rows})]);
            pending = "fetch";
        }
        remember(); render();
        saved();
    }
    function pump(): void {
        if (!writing && transactions.length) {
            writing = true; writer.request = transactions[0]; writer.received = false;
            writer.stdinEnabled = true; writer.running = true;
        }
        if (statusPending && !reading && !transactions.length) {
            statusPending = false; reading = true;
            reader.request = Object.assign({op: "status"}, range()); reader.month = month; reader.generation = generation;
            reader.received = false; reader.stdinEnabled = true; reader.running = true;
        }
        if (pending && !fetching && !transactions.length && (active || started)) {
            pending = ""; fetching = true;
            fetcher.request = Object.assign({op: "fetch", account_id: base.account_id || ""}, range()); fetcher.month = month; fetcher.generation = generation;
            fetcher.received = false; fetcher.stdinEnabled = true; fetcher.running = true;
        }
    }
    onActiveChanged: if (active) refresh()
    onMonthChanged: {
        const previous = base;
        base = months[month] ? Object.assign({}, months[month], {
            tasks: previous.tasks, calendars: previous.calendars, tasksReady: previous.tasksReady,
            tasksUpdated: previous.tasksUpdated || previous.updated
        }) : Object.assign({}, previous, {eventsReady: false});
        render(); refresh();
    }
    readonly property Timer timer: Timer {
        interval: root.active ? 60000 : 900000; repeat: true; running: root.active || root.started
        onTriggered: root.refresh()
    }
    readonly property Process reader: Process {
        property var request: ({})
        property string month: ""
        property int generation: 0
        property bool received: false
        command: ["python3", "-B", root.backend]
        onStarted: { write(JSON.stringify(request) + "\n"); stdinEnabled = false; }
        stdout: StdioCollector { onStreamFinished: root.receiveRead(text, reader) }
        stderr: StdioCollector {}
        onExited: { root.readExited(reader); root.reading = false; Qt.callLater(root.pump); }
    }
    readonly property Process fetcher: Process {
        property var request: ({})
        property string month: ""
        property int generation: 0
        property bool received: false
        command: ["python3", "-B", root.backend]
        onStarted: { write(JSON.stringify(request) + "\n"); stdinEnabled = false; }
        stdout: StdioCollector { onStreamFinished: root.receiveRead(text, fetcher) }
        stderr: StdioCollector {}
        onExited: {
            root.readExited(fetcher); root.fetching = false;
            if (month !== root.month) root.statusPending = true;
            Qt.callLater(root.pump);
        }
    }
    readonly property Process writer: Process {
        property var request: ({})
        property bool received: false
        command: ["python3", "-B", root.backend]
        onStarted: { write(JSON.stringify(request) + "\n"); stdinEnabled = false; }
        stdout: StdioCollector {
            onStreamFinished: {
                let result;
                try { result = JSON.parse(text); }
                catch (_) { result = {ok: false, error: qsTr("Could not read the write response.")}; }
                writer.received = true; root.finishWrite(result);
            }
        }
        stderr: StdioCollector {}
        onExited: {
            if (!received) root.finishWrite({ok: false});
            root.writing = false; Qt.callLater(root.pump);
        }
    }
}
