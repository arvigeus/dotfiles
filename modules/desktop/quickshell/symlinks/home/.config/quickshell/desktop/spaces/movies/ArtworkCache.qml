import QtQuick
import Quickshell

Item {
    id: root

    property string spaceId: "movies"
    property int consumers: 0
    property var resolved: ({})
    property var pending: ({})
    property int generation: 0

    function acquire() {
        consumers++;
    }

    function release() {
        consumers = Math.max(0, consumers - 1);
        if (!consumers) {
            generation++;
            resolved = ({});
            pending = ({});
        }
    }

    function fetch(url, callback, refresh) {
        const key = String(url);
        const ticket = {
            "callback": callback
        };
        if (refresh)
            delete resolved[key];

        if (resolved[key] && Date.now() - resolved[key].time < 3.6e+06) {
            const saved = resolved[key];
            const file = saved.file;
            delete resolved[key];
            resolved[key] = saved;
            Qt.callLater(() => {
                if (ticket.callback)
                    ticket.callback(file, "");
            });
            return ticket;
        }
        if (pending[key]) {
            pending[key].push(ticket);
            return ticket;
        }
        pending[key] = [ticket];
        const epoch = generation;
        worker.item.request("fetch", {
            "url": key,
            "refresh": !!refresh
        }, (file, error) => {
            if (epoch !== generation)
                return;

            const callbacks = pending[key] || [];
            delete pending[key];
            if (!error) {
                if (Object.keys(resolved).length >= 2000)
                    delete resolved[Object.keys(resolved)[0]];

                resolved[key] = {
                    "file": file,
                    "time": Date.now()
                };
            }
            for (const listener of callbacks)
                if (listener.callback) {
                    listener.callback(file, error);
                }
        });
        return ticket;
    }

    visible: false

    Loader {
        id: worker

        active: root.consumers > 0

        sourceComponent: Component {
            Worker {
                backend: "image_cache.py"
                serviceName: "Artwork"
                spaceId: root.spaceId
                startOnDemand: true
            }
        }
    }
}
