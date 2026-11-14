pragma Singleton
import "../../ui"
import QtQuick

QtObject {
    function open(url, moduleId, command, host) {
        const target = String(url || "");
        if (!/^https?:\/\//i.test(target))
            return;

        Apps.openUrl(target, moduleId, command);
        if (host)
            host.hide();
    }
}
