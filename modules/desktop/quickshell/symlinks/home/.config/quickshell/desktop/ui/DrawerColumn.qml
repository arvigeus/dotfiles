import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Optional scrolling layout for forms. DrawerPage itself imposes no layout.
ScrollView {
    id: root
    default property alias content: body.data
    clip: true
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical: ScrollBar {
        id: verticalScroll
        parent: root
        x: root.width - width
        y: root.topPadding
        height: root.availableHeight
        z: 1
        padding: 2
        hoverEnabled: true
        contentItem: Rectangle {
            implicitWidth: 4
            implicitHeight: 40
            radius: 2
            color: Theme.muted
            opacity: verticalScroll.size < 1 && (verticalScroll.active || verticalScroll.hovered) ? 0.7 : 0
        }
        background: Item {}
    }

    ColumnLayout {
        id: body
        width: root.availableWidth
        spacing: Theme.gap
    }
}
