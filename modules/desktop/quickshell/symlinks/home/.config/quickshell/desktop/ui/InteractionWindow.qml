pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland

PanelWindow {
    id: root

    required property InteractionState interactionState
    property Item initialFocus: null
    property var escapeHandler: null
    // Drawers can retain their presentation while closing. Input ownership still
    // follows opened, so an exiting surface cannot intercept application input.
    property bool keepVisible: false
    property ShellScreen presentationScreen: null
    property real backdropOpacity: 1
    readonly property bool opened: interactionState.activeSurface === root
    readonly property ShellScreen targetScreen: opened ? interactionState.screen
        : keepVisible ? presentationScreen : null

    screen: targetScreen
    visible: (opened || keepVisible) && targetScreen !== null
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: opened && visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    mask: opened ? null : noInput
    Region { id: noInput }

    function focusedOutput(): ShellScreen {
        return Quickshell.screens.find(output => output.name === Hyprland.focusedMonitor?.name) || null;
    }

    function toggle(): void { toggleOn(focusedOutput()); }
    function toggleOn(output: ShellScreen): void { interactionState.toggle(root, output); }
    function openOn(output: ShellScreen): void { interactionState.open(root, output); }
    function dismiss(): void { interactionState.dismiss(root); }

    // Wait for native activation before enabling text input/focusing a control.
    // Closing releases Exclusive keyboard focus; let the compositor restore
    // application focus instead of dispatching to a possibly stale saved window.
    function focusInitial(): void {
        if (focusContext.Window.active && opened && initialFocus)
            initialFocus.forceActiveFocus();
    }

    // Lazy content can finish after native activation, or change while the same
    // window stays active. Read the current target when the callback runs.
    onInitialFocusChanged: Qt.callLater(root.focusInitial)
    Item {
        id: focusContext
        Window.onActiveChanged: root.focusInitial()
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.opened && root.visible
        onActivated: { if (root.escapeHandler) root.escapeHandler(); else root.dismiss(); }
    }

    Rectangle { anchors.fill: parent; color: "#66000000"; opacity: root.backdropOpacity }
    MouseArea {
        objectName: "interactionBackdrop"
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        enabled: root.opened
        onClicked: root.dismiss()
    }
    // Content declared by consumers sits above the backdrop. Its surface must
    // consume blank clicks so only clicks outside that surface reach dismissal.
}
