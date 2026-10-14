pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    readonly property FileView modeFile: FileView {
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config")
            + "/quickshell/desktop/theme-mode"
        blockLoading: true
        // Optional synchronization with external edits or other shell instances.
        // watchChanges: true
        // onFileChanged: reload()
        onSaved: reload()
    }
    readonly property string mode: modeFile.text().trim() === "light" ? "light" : "dark"

    function setMode(value: string): void {
        if (value !== "dark" && value !== "light") {
            console.warn("Unknown theme mode:", value);
            return;
        }
        modeFile.setText(value + "\n");
    }

    readonly property var darkPalette: ({
        background: "#1b2021", surface: "#272d2e", raised: "#343b3c",
        border: "#454c4e", text: "#e4dadd", muted: "#aba5a9",
        accent: "#ff465c", accentText: "#ffffff", danger: "#ff8090",
        warning: "#e6bb6c", success: "#6ecc97"
    })
    readonly property var lightPalette: ({
        background: "#e4dde0", surface: "#d8cfd3", raised: "#cbc0c6",
        border: "#ab9ca4", text: "#30272d", muted: "#71636c",
        accent: "#c92240", accentText: "#ffffff", danger: "#bc2342",
        warning: "#946400", success: "#167348"
    })
    readonly property var palette: mode === "light" ? lightPalette : darkPalette
    readonly property color background: palette.background
    readonly property color surface: palette.surface
    readonly property color raised: palette.raised
    readonly property color border: palette.border
    readonly property color text: palette.text
    readonly property color muted: palette.muted
    readonly property color accent: palette.accent
    readonly property color accentText: palette.accentText
    readonly property color danger: palette.danger
    readonly property color warning: palette.warning
    readonly property color success: palette.success
    readonly property color accentSurface: Qt.tint(surface, Qt.rgba(accent.r, accent.g, accent.b, 0.16))

    readonly property string fontFamily: "Noto Sans"
    readonly property string monospaceFamily: "Noto Sans Mono"
    // Logical pixels; Qt applies each output's device pixel ratio.
    readonly property int fontSize: 15
    readonly property int smallFontSize: 12
    readonly property int titleFontSize: 20
    readonly property int iconSize: 20

    readonly property int spacingSmall: 4
    readonly property int spacingMedium: 8
    readonly property int gap: 12
    readonly property int padding: 16
    readonly property int paddingLarge: 24
    readonly property int radius: 10
    readonly property int controlRadius: 5
    readonly property int controlHeight: 34
    readonly property int pillRadius: 9
    readonly property int pillHeight: 44
    // Includes the tiled window's 10 px outer gap in the visual balance.
    readonly property int pillTopPadding: 10
    readonly property int barInset: 14
    readonly property int drawerWidth: 480
}
