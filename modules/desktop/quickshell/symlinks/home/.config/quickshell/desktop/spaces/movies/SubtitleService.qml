import QtQuick
import "../../ui"

Worker {
    backend: "subtitle_backend.py"
    serviceName: "Subtitles"
    startOnDemand: true
    timeout: 150000
}
