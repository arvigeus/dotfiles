import QtQuick
import Quickshell
import Quickshell.Wayland
import "../../ui"

PanelWindow {
    id: root
    required property ShellScreen output
    property bool external: false
    screen: output
    visible: !external
    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Background
    WlrLayershell.namespace: "desktop-wallpaper"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    color: Theme.background
    Image {
        anchors.fill: parent
        source: WallpaperService.image
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        sourceSize.width: Math.ceil(root.width * root.output.devicePixelRatio)
        sourceSize.height: Math.ceil(root.height * root.output.devicePixelRatio)
    }
}
