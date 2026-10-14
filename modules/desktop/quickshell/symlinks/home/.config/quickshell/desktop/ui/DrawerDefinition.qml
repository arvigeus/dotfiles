import QtQuick

// Metadata only: source is a URL so registering a drawer cannot instantiate its
// controls or backends. Keys are stable entry points, independent of file names.
QtObject {
    enum Edge { Left, Right }

    required property string key
    required property string title
    required property url source
    property int edge: DrawerDefinition.Right
    property string shortcut: ""
}
