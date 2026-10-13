pragma ComponentBehavior: Bound
// Developer preview: run qs --no-duplicate --path preview.qml from this directory.
import QtQuick
import QtQuick.Layouts
import Quickshell
import "ui"

ShellRoot {
    Connections {
        target: Quickshell
        function onLastWindowClosed() { Qt.quit(); }
    }

    FloatingWindow {
        title: "Desktop style preview"
        implicitWidth: 640
        implicitHeight: content.implicitHeight + Theme.paddingLarge * 2
        color: Theme.background

        Shortcut {
            sequence: "Escape"
            onActivated: Qt.quit()
        }

        Shortcut {
            sequence: "Ctrl+T"
            onActivated: Theme.setMode(Theme.mode === "dark" ? "light" : "dark")
        }

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: Theme.paddingLarge
            spacing: Theme.gap

            ShellText {
                text: "Desktop style · " + Theme.mode
                font.pixelSize: Theme.titleFontSize
                font.weight: Font.DemiBold
            }
            ShellText {
                text: "English · Български · Tiếng Việt"
            }
            ShellText {
                text: "0123456789  ~/Documents"
                font.family: Theme.monospaceFamily
                color: Theme.muted
            }

            RowLayout {
                spacing: Theme.spacingMedium
                Repeater {
                    model: [Theme.background, Theme.surface, Theme.raised, Theme.border,
                        Theme.text, Theme.muted, Theme.accent, Theme.danger, Theme.warning, Theme.success]
                    delegate: Rectangle {
                        required property color modelData
                        implicitWidth: 40
                        implicitHeight: 32
                        radius: Theme.controlRadius
                        color: modelData
                        border.color: Theme.border
                        border.width: 1
                    }
                }
            }

            Surface {
                Layout.fillWidth: true
                implicitHeight: surfaceText.implicitHeight + Theme.padding * 2
                ShellText {
                    id: surfaceText
                    anchors.fill: parent
                    anchors.margins: Theme.padding
                    wrapMode: Text.WordWrap
                    text: "A shared surface with readable text, a quiet border, and rounded corners."
                }
            }
            Surface {
                Layout.fillWidth: true
                implicitHeight: Theme.pillHeight
                radius: Theme.pillRadius
                color: Theme.raised
                RowLayout {
                    anchors.centerIn: parent
                    spacing: Theme.gap
                    Icon { name: "monitor" }
                    ShellText { text: "Raised surface" }
                }
            }
            Surface {
                Layout.fillWidth: true
                implicitHeight: Theme.pillHeight
                color: Theme.accentSurface
                RowLayout {
                    anchors.centerIn: parent
                    spacing: Theme.gap
                    Icon { name: "settings"; color: Theme.accent }
                    ShellText { text: "Accent surface" }
                }
            }

            RowLayout {
                spacing: Theme.padding
                Repeater {
                    model: ["search", "settings", "monitor", "chevron-left", "chevron-right", "x"]
                    delegate: Icon {
                        required property string modelData
                        name: modelData
                    }
                }
                ShellText { text: "Interface icons"; color: Theme.muted }
            }
            RowLayout {
                spacing: Theme.padding
                AppIcon { icon: "firefox" }
                AppIcon { icon: "org.kde.dolphin" }
                AppIcon { icon: "desktop-preview-missing-icon" }
                ShellText { text: "Application icons · missing icons stay blank"; color: Theme.muted }
            }
            ShellText {
                Layout.fillWidth: true
                text: "Ctrl+T switches the saved theme mode. Escape closes the preview."
                font.pixelSize: Theme.smallFontSize
                color: Theme.muted
                wrapMode: Text.WordWrap
            }
        }
    }
}
