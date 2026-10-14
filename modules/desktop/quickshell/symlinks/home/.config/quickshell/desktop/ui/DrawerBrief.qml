import QtQuick
import QtQuick.Layouts

// Reviewable prose for provisional drawers; replace with controls as each
// feature is implemented. This component owns no feature state or services.
ColumnLayout {
    id: root
    property string text: ""
    Layout.fillWidth: true
    spacing: Theme.spacingMedium

    ShellText {
        text: qsTr("Content draft")
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        Layout.fillWidth: true
    }
    ShellText {
        objectName: "drawerBrief"
        text: root.text
        wrapMode: Text.WordWrap
        lineHeight: 1.25
        Layout.fillWidth: true
    }
}
