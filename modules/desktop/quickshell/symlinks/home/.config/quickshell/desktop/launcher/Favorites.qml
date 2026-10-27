import QtQml
import QtCore

QtObject {
    id: root

    // Runtime-owned local preference. No seed/managed copy can overwrite it.
    property url location: StandardPaths.writableLocation(StandardPaths.ConfigLocation) + "/quickshell/desktop/launcher.ini"
    property var ids: []
    readonly property Settings preferences: Settings {
        location: root.location
        category: "Launcher"
    }

    Component.onCompleted: {
        const saved = preferences.value("favoriteIds", []);
        const values = typeof saved === "string" ? [saved] : saved && typeof saved.length === "number" ? Array.from(saved) : [];
        ids = [...new Set(values.filter(id => typeof id === "string" && id.length > 0))];
    }

    function toggle(id: string): void {
        if (!id.length)
            return;
        ids = ids.includes(id) ? ids.filter(value => value !== id) : ids.concat([id]);
        // Explicit writes bypass Settings' delayed property cache, so a reload
        // immediately after clicking a star reads the change from disk.
        preferences.setValue("favoriteIds", ids);
        preferences.sync();
    }
}
