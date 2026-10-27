pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Services.Notifications

Singleton {
    id: root
    property bool started: false
    property bool initialized: false
    property string error: ""
    property var state: ({
            items: [],
            paused: false
        })
    property var live: ({})
    property var snapshots: ({})
    property int sequence: 0
    property var updates: []
    property bool drawerOpen: false
    readonly property string historyPath: {
        const base = Quickshell.env("XDG_STATE_HOME") || "";
        return (base.startsWith("/") ? base : Quickshell.env("HOME") + "/.local/state") + "/quickshell/desktop/notifications.json";
    }
    readonly property int unseenCount: state.items.filter(row => row.seen === false).length
    onDrawerOpenChanged: if (drawerOpen) {
        while (popups.count)
            hidePopup(popups.get(0).key);
        markSeen();
    }
    readonly property ListModel popups: ListModel {
        dynamicRoles: true
    }

    function start(): void {
        if (started)
            return;
        started = true;
        // History and quiet state load before the server accepts notifications.
        const text = store.text();
        if (text.trim()) {
            try {
                state = normalized(JSON.parse(text));
            } catch (_) {
                error = qsTr("Could not read notification history.");
            }
        }
        initialized = true;
        if (drawerOpen)
            markSeen();
    }
    // Saved history keeps bounded plain text; actions and images belong to the live connection.
    function normalized(value: var): var {
        const rows = [], ids = {};
        for (const item of Array.isArray(value?.items) ? value.items.slice(0, 100) : []) {
            if (typeof item?.id !== "string" || !item.id || ids[item.id])
                continue;
            ids[item.id] = true;
            const text = (key, limit) => String(item[key] ?? "").slice(0, limit);
            const number = (key, fallback) => typeof item[key] === "number" && Number.isFinite(item[key]) ? item[key] : fallback;
            const icon = text("appIcon", 2000);
            rows.push({
                id: text("id", 150),
                app: text("app", 250),
                desktopEntry: text("desktopEntry", 250),
                summary: text("summary", 2000),
                body: text("body", 16384),
                appIcon: !icon.includes("://") || icon.startsWith("file:///") ? icon : "",
                timestamp: number("timestamp", Date.now() / 1000),
                urgency: number("urgency", 1),
                progress: number("progress", -1),
                processId: number("processId", 0),
                liveId: number("liveId", 0),
                actions: [],
                image: "",
                seen: item.seen !== false
            });
        }
        return {
            items: rows,
            paused: value?.paused === true
        };
    }
    function plain(value: string): string {
        return value.replace(/<[^>]*>/g, "").replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (_, entity) => {
            if (entity[0] === "#") {
                const code = entity[1].toLowerCase() === "x" ? parseInt(entity.slice(2), 16) : parseInt(entity.slice(1), 10);
                return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : "";
            }
            return {
                amp: "&",
                lt: "<",
                gt: ">",
                quot: '"',
                apos: "'",
                nbsp: " "
            }[entity.toLowerCase()];
        });
    }
    function imageSource(value: string): string {
        return value.startsWith("image://") || value.startsWith("file:///") || value.startsWith("/") ? value : "";
    }
    function save(): void {
        if (initialized)
            saveTimer.restart();
    }
    function updateItem(record: var, retain: bool): void {
        snapshots = Object.assign({}, snapshots, {
            [record.id]: record
        });
        const items = state.items.filter(row => row.id !== record.id);
        if (retain)
            items.unshift(record);
        const removed = items.splice(100);
        state = Object.assign({}, state, {
            items
        });
        for (const row of removed) {
            hidePopup(row.id);
            const notification = live[row.id];
            if (notification)
                notification.expire();
            const values = Object.assign({}, snapshots);
            delete values[row.id];
            snapshots = values;
        }
        save();
    }
    function changed(key: string): void {
        if (!updates.includes(key))
            updates = updates.concat([key]);
        updateTimer.restart();
    }
    function receive(notification: var, replacement = false): void {
        notification.tracked = true;
        let key = Object.keys(live).find(key => live[key] === notification);
        const fresh = !key;
        if (!key && notification.lastGeneration)
            key = state.items.find(row => row.liveId === notification.id && row.processId === Quickshell.processId)?.id;
        key = key || "notification-" + Date.now() + "-" + (++sequence);
        live = Object.assign({}, live, {
            [key]: notification
        });
        const previous = state.items.find(row => row.id === key);
        const value = Number(notification.hints.value);
        const record = {
            id: key,
            liveId: notification.id,
            processId: Quickshell.processId,
            seen: drawerOpen || (notification.lastGeneration && !replacement && previous ? previous.seen !== false : false),
            app: notification.appName || qsTr("Notification"),
            desktopEntry: notification.desktopEntry || "",
            summary: notification.summary || qsTr("Notification"),
            body: plain(notification.body).slice(0, 16384),
            timestamp: notification.lastGeneration && !replacement ? state.items.find(row => row.id === key)?.timestamp || Date.now() / 1000 : Date.now() / 1000,
            urgency: notification.urgency,
            appIcon: notification.appIcon || "",
            image: imageSource(notification.image),
            progress: notification.hints.value !== undefined && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : -1,
            actions: notification.actions.map(action => ({
                        identifier: action.identifier,
                        text: action.text || qsTr("Open")
                    }))
        };
        if (fresh) {
            notification.closed.connect(reason => root.closed(key, reason));
            for (const signal of [notification.summaryChanged, notification.bodyChanged, notification.actionsChanged, notification.hintsChanged, notification.appNameChanged, notification.appIconChanged, notification.imageChanged, notification.urgencyChanged, notification.expireTimeoutChanged, notification.transientChanged, notification.desktopEntryChanged])
                signal.connect(() => root.changed(key));
        }
        updateItem(record, !notification.transient);
        if (notification.lastGeneration && !replacement || state.paused || drawerOpen) {
            // New/reloaded notifications enter the server ID map after this callback.
            if (notification.transient)
                Qt.callLater(() => {
                    if (root.live[key]?.transient)
                        root.live[key].expire();
                });
            return;
        }
        // The installed Quickshell API exposes the protocol timeout in milliseconds.
        const timeout = notification.expireTimeout;
        const duration = timeout > 0 ? timeout : timeout === 0 || notification.urgency === NotificationUrgency.Critical ? 0 : 6000;
        const index = popupIndex(key);
        if (index >= 0) {
            const hovered = popups.get(index).hovered;
            popups.setProperty(index, "record", record);
            popups.setProperty(index, "remaining", duration);
            popups.setProperty(index, "deadline", duration && !hovered ? Date.now() + duration : 0);
            if (index > 0)
                popups.move(index, 0, 1);
        } else {
            popups.insert(0, {
                key,
                record,
                screenName: Hyprland.focusedMonitor?.name || Quickshell.screens[0]?.name || "",
                deadline: duration ? Date.now() + duration : 0,
                remaining: duration,
                hovered: false
            });
        }
        while (popups.count > 3)
            hidePopup(popups.get(popups.count - 1).key);
        scheduleExpiry();
    }
    function closed(key: string, reason: int): void {
        const values = Object.assign({}, live);
        delete values[key];
        live = values;
        const record = state.items.find(row => row.id === key) || snapshots[key];
        hidePopup(key);
        if (reason === NotificationCloseReason.CloseRequested) {
            state = Object.assign({}, state, {
                items: state.items.filter(row => row.id !== key)
            });
        } else if (record) {
            const saved = Object.assign({}, record, {
                actions: [],
                image: ""
            });
            state = Object.assign({}, state, {
                items: state.items.map(row => row.id === key ? saved : row)
            });
        }
        const records = Object.assign({}, snapshots);
        delete records[key];
        snapshots = records;
        save();
    }
    function popupIndex(key: string): int {
        for (let index = 0; index < popups.count; index++)
            if (popups.get(index).key === key)
                return index;
        return -1;
    }
    function hidePopup(key: string): void {
        const index = popupIndex(key);
        if (index >= 0)
            popups.remove(index);
        scheduleExpiry();
        const notification = live[key];
        if (notification?.transient)
            notification.expire();
    }
    function hoverPopup(key: string, hovered: bool): void {
        const index = popupIndex(key);
        if (index < 0)
            return;
        const row = popups.get(index);
        if (row.hovered === hovered)
            return;
        if (hovered && row.deadline)
            popups.setProperty(index, "remaining", Math.max(1, row.deadline - Date.now()));
        popups.setProperty(index, "deadline", hovered || !row.remaining ? 0 : Date.now() + row.remaining);
        popups.setProperty(index, "hovered", hovered);
        scheduleExpiry();
    }
    function markSeen(key = ""): void {
        if (!state.items.some(row => row.seen === false && (!key || row.id === key)))
            return;
        state = Object.assign({}, state, {
            items: state.items.map(row => !key || row.id === key ? Object.assign({}, row, {
                    seen: true
                }) : row)
        });
        save();
    }
    function invoke(key: string, identifier: string): void {
        const notification = live[key];
        const action = notification?.actions.find(action => action.identifier === identifier);
        if (action) {
            markSeen(key);
            const resident = notification.resident;
            action.invoke();
            if (!resident)
                hidePopup(key);
        }
    }
    function dismiss(key: string): void {
        hidePopup(key);
        state = Object.assign({}, state, {
            items: state.items.filter(row => row.id !== key)
        });
        const notification = live[key];
        if (notification)
            notification.dismiss();
        save();
    }
    function request(op = "status", key = "", value = false): void {
        if (op === "remove")
            dismiss(String(key));
        else if (op === "clear") {
            const keys = Object.keys(live);
            state = Object.assign({}, state, {
                items: []
            });
            for (const id of keys)
                dismiss(id);
            popups.clear();
            save();
        } else if (op === "pause") {
            state = Object.assign({}, state, {
                paused: !!value
            });
            while (popups.count)
                hidePopup(popups.get(0).key);
            save();
        }
    }
    IpcHandler {
        target: "notifications"
        enabled: root.started
        function status(): string {
            return JSON.stringify({
                paused: root.state.paused,
                drawerOpen: root.drawerOpen,
                unseen: root.unseenCount,
                history: root.state.items.length,
                popups: root.popups.count
            });
        }
    }
    Loader {
        active: root.started && root.initialized
        sourceComponent: Component {
            NotificationServer {
                actionsSupported: true
                persistenceSupported: true
                imageSupported: true
                bodyMarkupSupported: false
                bodyHyperlinksSupported: false
                bodyImagesSupported: false
                onNotification: notification => root.receive(notification)
            }
        }
    }
    function scheduleExpiry(): void {
        expiry.stop();
        let deadline = Infinity;
        for (let index = 0; index < popups.count; index++) {
            const time = popups.get(index).deadline;
            if (time)
                deadline = Math.min(deadline, time);
        }
        if (Number.isFinite(deadline)) {
            expiry.interval = Math.max(1, Math.ceil(deadline - Date.now()));
            expiry.start();
        }
    }
    Timer {
        id: updateTimer
        interval: 0
        onTriggered: {
            const keys = root.updates;
            root.updates = [];
            for (const key of keys)
                if (root.live[key])
                    root.receive(root.live[key], true);
        }
    }
    Timer {
        id: expiry
        onTriggered: {
            const expired = [];
            for (let index = 0; index < root.popups.count; index++) {
                const row = root.popups.get(index);
                if (row.deadline && row.deadline <= Date.now())
                    expired.push(row.key);
            }
            for (const key of expired)
                root.hidePopup(key);
            root.scheduleExpiry();
        }
    }
    Timer {
        id: saveTimer
        interval: 150
        onTriggered: store.setText(JSON.stringify(root.normalized(root.state)))
    }
    FileView {
        id: store
        path: root.started ? root.historyPath : ""
        blockLoading: true
        atomicWrites: true
        printErrors: false
        onLoadFailed: error => {
            if (error !== FileViewError.FileNotFound)
                root.error = qsTr("Could not read notification history.");
        }
        onSaved: root.error = ""
        onSaveFailed: root.error = qsTr("Could not save notification history. Check the local state directory.")
    }
}
