import QtQuick
import "../movies"

Worker {
    objectName: "radioService"
    backendDirectory: "spaces/radio"
    backend: "backend.py"
    spaceId: "radio"
    serviceName: "Radio"
}
