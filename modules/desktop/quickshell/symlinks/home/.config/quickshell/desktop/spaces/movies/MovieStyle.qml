pragma Singleton
import QtQuick
import "../../ui" as Desktop

QtObject {
    readonly property color background: "#09090b"
    readonly property color surface: "#141117"
    readonly property color raised: "#261b25"
    readonly property color border: "#49313e"
    readonly property color text: "#ffffff"
    readonly property color muted: "#c2bcc9"
    readonly property color accent: "#e50914"
    readonly property color accentText: "#ffffff"
    readonly property color accentSurface: "#40e50914"
    readonly property color danger: "#ff6571"
    readonly property int controlHeight: 38
    readonly property int controlRadius: 6
    readonly property int radius: 12
    readonly property string fontFamily: Desktop.Theme.fontFamily
    readonly property int fontSize: Desktop.Theme.fontSize
}
