import "../movies"
import QtQuick

Worker {
    objectName: "gamesService"
    backend: "backend.py"
    backendDirectory: "spaces/games"
    serviceName: "Games"
    spaceId: "games"
}
