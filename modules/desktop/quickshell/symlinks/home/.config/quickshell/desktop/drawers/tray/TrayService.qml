pragma Singleton
import QtQuick
import Quickshell.Services.SystemTray
import "../notifications"

QtObject {
    id: root
    property var tray: SystemTray
    property var notifications: NotificationCenter
    readonly property var items: tray?.items?.values ?? []
    readonly property int count: items?.length ?? 0
    readonly property var attentionItems: (items ?? []).filter(item => needsAttention(item))
    readonly property bool attention: (attentionItems?.length ?? 0) > 0

    function identifiers(value: string): var {
        const name = value.trim().toLowerCase().replace(/\.desktop$/, "");
        if (!name) return [];
        // Match desktop IDs as well as display names, without substring guesses.
        return /^[a-z0-9_-]+(?:\.[a-z0-9_-]+){2,}$/.test(name)
            ? [name, name.slice(name.lastIndexOf(".") + 1)] : [name];
    }

    function matches(item: var, record: var): bool {
        const app = identifiers(item.id || "").concat(identifiers(item.title || ""));
        const sender = identifiers(record.desktopEntry || "").concat(identifiers(record.app || ""));
        return app.some(name => sender.includes(name));
    }

    function unseenFor(item: var): var {
        return (notifications?.state?.items ?? []).filter(record => record.seen === false && matches(item, record));
    }

    function needsAttention(item: var): bool {
        return item.status === Status.NeedsAttention || unseenFor(item).length > 0;
    }

    function acknowledge(item: var): void {
        for (const record of unseenFor(item)) notifications.markSeen(record.id);
    }
}
