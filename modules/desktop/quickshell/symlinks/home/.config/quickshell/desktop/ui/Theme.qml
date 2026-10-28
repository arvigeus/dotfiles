pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    property bool started: false
    // A failed save stays visible until a later save succeeds; synchronization
    // results only replace their own message.
    property string saveError: ""
    property string syncError: ""
    readonly property string error: [saveError, syncError].filter(Boolean).join("\n")
    property string paletteError: ""
    property bool pending: false
    readonly property bool busy: sync.running || pending
    property var definition: readPalette()

    // Keep these rules identical to theme.py::load.
    function parsePalette(text: string): var {
        const value = JSON.parse(text);
        if (Object.keys(value).sort().join() !== "font,fontSize,monospaceFont,palettes" || typeof value.fontSize !== "number" || value.fontSize < 6 || value.fontSize > 24 || !Number.isFinite(value.fontSize))
            throw new Error("Invalid theme fields or font size");
        for (const key of ["font", "monospaceFont"])
            if (typeof value[key] !== "string" || !/^[\w .+()-]{1,100}$/.test(value[key]))
                throw new Error("Invalid font family");
        if (Object.keys(value.palettes).sort().join() !== "dark,light")
            throw new Error("Expected dark and light palettes");
        const keys = "accent,accentText,background,border,danger,muted,raised,success,surface,text,visited,warning";
        for (const mode of ["dark", "light"]) {
            const palette = value.palettes[mode];
            if (Object.keys(palette).sort().join() !== keys)
                throw new Error("Invalid color tokens");
            for (const color of Object.values(palette))
                if (typeof color !== "string" || !/^#[0-9a-fA-F]{6}$/.test(color))
                    throw new Error("Colors must use #RRGGBB");
        }
        return value;
    }
    function readPalette() {
        try {
            const value = parsePalette(paletteFile.text());
            paletteError = "";
            return value;
        } catch (e) {
            paletteError = qsTr("Could not load the appearance palette: ") + e.message;
            return definition;
        }
    }
    function start(): void {
        started = true;
        synchronize();
    }
    function synchronize(): void {
        if (started && !paletteError) {
            pending = true;
            syncTimer.restart();
        }
    }
    onModeChanged: synchronize()
    onDefinitionChanged: synchronize()
    FileView {
        id: paletteFile
        path: "/etc/desktop-palette.json"
        blockLoading: true
        watchChanges: true
        onFileChanged: reload()
        onTextChanged: root.definition = root.readPalette()
    }
    FileView {
        id: modeFile
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/desktop/theme-mode"
        blockLoading: true
        watchChanges: true
        atomicWrites: true
        printErrors: false
        onFileChanged: reload()
        onSaved: {
            root.saveError = "";
            reload();
        }
        onSaveFailed: {
            root.saveError = qsTr("Could not save appearance mode.");
            // The rejected text remains in memory; show the persisted mode.
            // Quickshell 0.3.2 defers a reload issued during the failed write.
            Qt.callLater(reload);
        }
    }
    readonly property string mode: modeFile.text().trim() === "light" ? "light" : "dark"

    function setMode(value: string): void {
        if (value !== "dark" && value !== "light") {
            console.warn("Unknown theme mode:", value);
            return;
        }
        modeFile.setText(value + "\n");
    }

    readonly property var palette: definition.palettes[mode]
    readonly property color background: palette.background
    readonly property color surface: palette.surface
    readonly property color raised: palette.raised
    readonly property color border: palette.border
    readonly property color text: palette.text
    readonly property color muted: palette.muted
    readonly property color accent: palette.accent
    function selectionText(palette) {
        function luminance(color) {
            let result = 0;
            const weights = [0.2126, 0.7152, 0.0722];
            for (let i = 0; i < 3; i++) {
                const value = parseInt(color.slice(i * 2 + 1, i * 2 + 3), 16) / 255;
                result += (value <= 0.04045 ? value / 12.92 : Math.pow((value + 0.055) / 1.055, 2.4)) * weights[i];
            }
            return result;
        }
        function contrast(color) {
            const values = [luminance(color), luminance(palette.accent)].sort((a, b) => a - b);
            return (values[1] + 0.05) / (values[0] + 0.05);
        }
        for (const value of [palette.accentText, palette.text])
            if (contrast(value) >= 4.5)
                return value;
        return contrast("#000000") >= contrast("#ffffff") ? "#000000" : "#ffffff";
    }
    readonly property color accentText: selectionText(palette)
    readonly property color danger: palette.danger
    readonly property color warning: palette.warning
    readonly property color success: palette.success
    readonly property color accentSurface: Qt.tint(surface, Qt.rgba(accent.r, accent.g, accent.b, 0.16))

    readonly property string fontFamily: definition.font
    readonly property string monospaceFamily: definition.monospaceFont
    // Logical pixels; Qt applies each output's device pixel ratio.
    readonly property int fontSize: Math.round(definition.fontSize * 96 / 72)
    readonly property int smallFontSize: Math.round(fontSize * 12 / 15)
    readonly property int titleFontSize: Math.round(fontSize * 20 / 15)
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

    Timer {
        id: syncTimer
        interval: 120
        onTriggered: {
            if (sync.running)
                return;
            root.pending = false;
            sync.running = true;
        }
    }
    Process {
        id: sync
        // Startup and reloads reapply files without re-announcing an unchanged
        // appearance to every running application.
        command: ["python3", Quickshell.shellPath("ui/theme.py"), "--if-changed"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.syncError = JSON.parse(text).warnings.join("\n");
                } catch (_) { /* Failed commands report stderr below. */ }
            }
        }
        stderr: StdioCollector {
            id: syncErrors
        }
        onExited: (code, status) => {
            if (code !== 0)
                root.syncError = qsTr("Could not apply appearance: ") + syncErrors.text.trim();
            if (root.pending)
                syncTimer.restart();
        }
    }
}
