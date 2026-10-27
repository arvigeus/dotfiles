import QtQuick

// Reserve the largest value; the visible bubble fits its current text.
Item {
    id: root
    property string text: ""
    property string reserveText: "99+"
    property bool highlighted: false
    readonly property int horizontalPadding: 3

    implicitWidth: Math.max(implicitHeight, Math.ceil(metrics.advanceWidth(reserveText)) + horizontalPadding * 2)
    implicitHeight: 14
    Accessible.role: Accessible.StaticText
    Accessible.name: text

    FontMetrics {
        id: metrics
        font: label.font
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(root.width, Math.max(root.height, Math.ceil(metrics.advanceWidth(root.text)) + root.horizontalPadding * 2))
        height: root.height
        visible: root.text !== ""
        radius: height / 2
        color: root.highlighted ? Theme.accent : Theme.raised
        border.width: 1
        border.color: Theme.surface

        ShellText {
            id: label
            anchors.fill: parent
            anchors.leftMargin: root.horizontalPadding
            anchors.rightMargin: root.horizontalPadding
            text: root.text
            color: root.highlighted ? Theme.accentText : Theme.text
            font.pixelSize: Theme.smallFontSize - 2
            font.weight: Font.DemiBold
            font.features: ({
                    "tnum": 1
                })
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }
}
