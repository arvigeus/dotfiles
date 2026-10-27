pragma Singleton
import "../../ui"
import QtQuick

QtObject {
    function open(url, moduleId, command, host) {
        const target = String(url || "");
        if (!/^https?:\/\//i.test(target))
            return;

        Apps.launch(["xdg-open", target]);
        if (host)
            host.hide();
    }
}
