pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import "../../ui"

Scope {
    id: root
    property var service: NotificationCenter
    readonly property var windows: popupWindows.instances
    Variants {
        id: popupWindows
        model: Quickshell.screens
        PanelWindow {
            id: window
            objectName: "notificationPopups:" + modelData.name
            required property ShellScreen modelData
            screen: modelData
            anchors { top: true; right: true }
            margins { top: Theme.pillTopPadding + Theme.pillHeight + Theme.gap; right: Theme.barInset }
            implicitWidth: Math.min(390, modelData.width - Theme.barInset * 2)
            implicitHeight: Math.min(stack.implicitHeight, Math.max(100, modelData.height - Theme.pillTopPadding - Theme.pillHeight - Theme.gap - Theme.barInset))
            visible: {
                for (let index = 0; index < root.service.popups.count; index++)
                    if (accepts(root.service.popups.get(index).screenName)) return true;
                return false;
            }
            function accepts(name: string): bool {
                return name === modelData.name || !Quickshell.screens.some(output => output.name === name) && modelData === Quickshell.screens[0];
            }
            color: "transparent"; exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "desktop-notifications"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {
                regions: regions.instances
            }
            // Only the cards accept input; gaps pass clicks through to the desktop.
            Variants {
                id: regions; model: { cards.count; return stack.children.filter(child => child !== cards && child.visible); }
                Region { required property var modelData; item: modelData; radius: Theme.radius }
            }
            DrawerColumn {
                anchors.fill: parent
                ColumnLayout {
                    id: stack; Layout.fillWidth: true; spacing: Theme.spacingMedium
                    Repeater {
                        id: cards; model: root.service.popups
                        NotificationCard {
                            id: card
                            objectName: "notificationPopup:" + key
                            required property string key
                            required property string screenName
                            visible: window.accepts(screenName)
                            Layout.fillWidth: true
                            compact: true
                            onDismissed: { root.service.markSeen(key); root.service.hidePopup(key); }
                            onActionRequested: identifier => root.service.invoke(key, identifier)
                            HoverHandler { onHoveredChanged: root.service.hoverPopup(card.key, hovered) }
                            property bool entered: false
                            opacity: entered ? 1 : 0
                            Component.onCompleted: entered = true
                            Behavior on opacity { NumberAnimation { duration: 160 } }
                            transform: Translate {
                                x: card.entered ? 0 : 16
                                Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                            }
                        }
                    }
                }
            }
        }
    }
}
