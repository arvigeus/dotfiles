import "../../ui"
import QtQuick

Worker {
    backend: "subtitle_backend.py"
    serviceName: "Subtitles"
    startOnDemand: true
    timeout: 150000
}
