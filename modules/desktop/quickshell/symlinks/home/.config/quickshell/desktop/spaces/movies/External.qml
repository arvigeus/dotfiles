pragma Singleton
import "../../ui"
import QtQuick

QtObject {
    function launch(command, host) {
        if (!command || !command.length)
            return;

        Apps.launch(command);
        if (host)
            host.hide();
    }
}
