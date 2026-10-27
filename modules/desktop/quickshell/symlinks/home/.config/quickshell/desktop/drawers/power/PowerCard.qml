import "../../ui"
import QtQuick
import QtQuick.Layouts

Card {
    id: root

    default property alias content: body.data
    property string title: ""

    Layout.fillWidth: true
    implicitHeight: body.implicitHeight + 24

    ColumnLayout {
        id: body

        x: 12
        y: 12
        width: Math.max(0, root.width - 24)
        spacing: 10

        ShellText {
            visible: root.title !== ""
            text: root.title
            font.weight: Font.DemiBold
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
        }
    }
}
