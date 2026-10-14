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

    ColumnLayout {
        id: body
        width: root.availableWidth
        spacing: Theme.gap
    }
}
