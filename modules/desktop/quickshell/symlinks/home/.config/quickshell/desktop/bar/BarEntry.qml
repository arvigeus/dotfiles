import QtQuick
import "../ui"

// Presentation state only. Future providers can bind these properties without
// loading a drawer. Feature discovery remains scoped to the drawer's active flag.
QtObject {
    required property string key
    required property string title
    property string iconName: ""
    property color iconColor: Theme.text
    property string label: ""
    property string secondaryIconName: ""
    property string badge: ""
    property string description: ""
    property bool attention: false
    property bool available: true
}
