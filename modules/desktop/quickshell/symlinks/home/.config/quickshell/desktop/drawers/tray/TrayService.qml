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

    // Electron items publish a generic ID and no title; the tooltip title names the app.
    function nameFor(item: var): string {
        return item?.title || item?.tooltipTitle || item?.id || qsTr("Unknown application");
    }

    function canonical(value: string): string {
        return value.trim().toLowerCase().replace(/\.desktop$/, "");
    }

    // A reverse-DNS desktop ID also answers to its last segment.
    function alias(name: string): string {
        return /^[a-z0-9_-]+(?:\.[a-z0-9_-]+){2,}$/.test(name) ? name.slice(name.lastIndexOf(".") + 1) : "";
    }

    // Whole names only, never substrings. An alias must equal the other side's full
    // name: two desktop IDs sharing just their last segment are different apps.
    function matches(item: var, record: var): bool {
        const app = [item.id || "", item.title || item.tooltipTitle || ""].map(value => canonical(value)).filter(Boolean);
        const sender = [record.desktopEntry || "", record.app || ""].map(value => canonical(value)).filter(Boolean);
        return app.some(name => sender.some(other => name === other || name === alias(other) || alias(name) === other));
    }

    function unseenFor(item: var): var {
        return (notifications?.state?.items ?? []).filter(record => record.seen === false && matches(item, record));
    }

    function needsAttention(item: var): bool {
        return item.status === Status.NeedsAttention || unseenFor(item).length > 0;
    }

    function acknowledge(item: var): void {
        for (const record of unseenFor(item))
            notifications.markSeen(record.id);
    }
}
