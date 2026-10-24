import QtQuick
import "../movies"

Worker {
    objectName: "gamesService"
    backend: "backend.py"
    backendDirectory: "spaces/games"
    serviceName: "Games"
    spaceId: "games"
}
