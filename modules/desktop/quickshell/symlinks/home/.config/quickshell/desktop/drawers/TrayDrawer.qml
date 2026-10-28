pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import Quickshell
import Quickshell.Services.SystemTray
import "../ui"
import "tray"

DrawerPage {
    id: root

    property var tray: SystemTray
    readonly property var items: tray.items.values
    property var menuItem: null
    property Item menuButton: null
    escapeHandler: nativeMenu.visible ? () => root.closeMenu() : null

    function hasItem(item: var): bool {
        return active && !!item && items.includes(item);
    }

    function statusFor(item: var): string {
        if (item && TrayService.needsAttention(item))
            return qsTr("Needs attention");
        return item?.status === Status.Passive ? qsTr("Idle") : qsTr("Running");
    }

    function closeMenu(): void {
        if (nativeMenu.visible)
            nativeMenu.close();
        menuItem = null;
        menuButton = null;
    }

    function showMenu(item: var, button: Item): void {
        if (!hasItem(item) || !item.hasMenu || !item.menu)
            return;
        closeMenu();
        menuItem = item;
        menuButton = button;
        nativeMenu.open();
    }

    function activate(item: var, button: Item, secondary: bool): void {
        if (!hasItem(item))
            return;
        if (!secondary && item.onlyMenu) {
            showMenu(item, button);
            return;
        }
        closeMenu();
        if (!secondary)
            TrayService.acknowledge(item);
        closeRequested();
        if (secondary)
            item.secondaryActivate();
        else
            item.activate();
    }

    onActiveChanged: if (!active)
        closeMenu()
    onItemsChanged: if (menuItem && !items.includes(menuItem))
        closeMenu()
    Component.onDestruction: if (nativeMenu.visible)
        nativeMenu.close()

    Connections {
        target: root.menuItem
        function onHasMenuChanged(): void {
            if (!root.menuItem?.hasMenu)
                root.closeMenu();
        }
    }

    // Native app menus preserve submenus, toggles, radio items and shortcuts.
    // Close before retargeting: Quickshell 0.3.2 keeps an open anchor open and its
    // old menu referenced when menu changes underneath it.
    QsMenuAnchor {
        id: nativeMenu
        objectName: "trayNativeMenu"
        menu: root.menuItem?.menu ?? null
        anchor.item: root.menuButton
        anchor.edges: Edges.Bottom | Edges.Right
        anchor.gravity: Edges.Bottom | Edges.Left
        onClosed: {
            if (root.active && root.menuButton?.enabled)
                root.menuButton.forceActiveFocus();
            root.menuItem = null;
            root.menuButton = null;
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.gap

        ShellText {
            objectName: "trayEmpty"
            Layout.fillWidth: true
            visible: root.items.length === 0
            text: qsTr("No applications in the system tray.")
            color: Theme.muted
            wrapMode: Text.Wrap
        }

        ScrollListView {
            id: list
            objectName: "trayScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.spacingMedium
            // The native model inserts/removes rows; a JS array would rebuild every
            // row, dropping focus, hover and the open menu's anchor.
            model: root.tray.items
            keyNavigationEnabled: true
            activeFocusOnTab: true

            Keys.onReturnPressed: if (currentItem)
                currentItem.activateItem()
            Keys.onEnterPressed: if (currentItem)
                currentItem.activateItem()
            Keys.onSpacePressed: if (currentItem)
                currentItem.activateItem()
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
                    if (currentItem)
                        currentItem.openMenu();
                    event.accepted = true;
                }
            }

            // A focus scope keeps a tabbed control focused when the view makes its row current.
            delegate: FocusScope {
                id: card
                required property var modelData
                required property int index
                readonly property bool attention: TrayService.needsAttention(modelData)
                readonly property bool highlighted: rowHover.hovered || select.visualFocus || menu.visualFocus || (list.activeFocus && list.currentIndex === index)
                objectName: "trayItem:" + modelData.id
                width: ListView.view.width
                implicitHeight: 64
                height: implicitHeight

                function activateItem(): void {
                    root.activate(modelData, select, false);
                }
                function openMenu(): void {
                    root.showMenu(modelData, menu);
                }

                HoverHandler {
                    id: rowHover
                    enabled: root.active
                }
                ButtonBackground {
                    objectName: "trayBackground:" + card.modelData.id
                    anchors.fill: parent
                    idleColor: Theme.surface
                    idleBorderColor: Theme.border
                    highlighted: card.highlighted
                    pressed: select.down || menu.down
                    border.color: card.attention ? Theme.warning : card.highlighted ? Theme.accent : idleBorderColor
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingSmall
                    spacing: Theme.spacingSmall

                    Button {
                        id: select
                        objectName: "trayActivate:" + card.modelData.id
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        padding: Theme.spacingMedium
                        hoverEnabled: true
                        enabled: root.active
                        text: TrayService.nameFor(card.modelData)
                        Accessible.name: text
                        Accessible.description: root.statusFor(card.modelData)
                        onActiveFocusChanged: if (activeFocus)
                            list.currentIndex = card.index
                        onClicked: card.activateItem()
                        Keys.onReturnPressed: card.activateItem()
                        Keys.onEnterPressed: card.activateItem()
                        Keys.onPressed: event => {
                            if (event.key === Qt.Key_Menu || (event.key === Qt.Key_F10 && (event.modifiers & Qt.ShiftModifier))) {
                                card.openMenu();
                                event.accepted = true;
                            }
                        }
                        background: Item {}
                        contentItem: RowLayout {
                            spacing: Theme.gap
                            Item {
                                Layout.preferredWidth: 28
                                Layout.preferredHeight: 28
                                Image {
                                    id: artwork
                                    objectName: "trayIcon:" + card.modelData.id
                                    anchors.fill: parent
                                    source: card.modelData.icon
                                    sourceSize.width: Math.ceil(width * Screen.devicePixelRatio)
                                    sourceSize.height: Math.ceil(height * Screen.devicePixelRatio)
                                    fillMode: Image.PreserveAspectFit
                                    visible: status === Image.Ready
                                }
                                Icon {
                                    anchors.fill: parent
                                    name: "square"
                                    color: Theme.muted
                                    visible: artwork.status !== Image.Ready
                                }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                ShellText {
                                    Layout.fillWidth: true
                                    text: select.text
                                    elide: Text.ElideRight
                                }
                                ShellText {
                                    objectName: "trayStatus:" + card.modelData.id
                                    Layout.fillWidth: true
                                    text: root.statusFor(card.modelData)
                                    color: card.attention ? Theme.warning : Theme.muted
                                    font.pixelSize: Theme.smallFontSize
                                    elide: Text.ElideRight
                                }
                            }
                        }
                        PassiveToolTip {
                            target: select
                            text: [select.text, card.modelData.tooltipTitle, card.modelData.tooltipDescription].filter((value, index, values) => !!value && values.indexOf(value) === index).join("\n")
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.RightButton | Qt.MiddleButton
                            onClicked: event => {
                                if (event.button === Qt.RightButton)
                                    card.openMenu();
                                else
                                    root.activate(card.modelData, select, true);
                            }
                            onWheel: event => {
                                if (!root.hasItem(card.modelData)) {
                                    event.accepted = false;
                                    return;
                                }
                                const delta = event.angleDelta;
                                if (delta.y)
                                    card.modelData.scroll(delta.y, false);
                                if (delta.x)
                                    card.modelData.scroll(delta.x, true);
                                event.accepted = !!(delta.x || delta.y);
                            }
                        }
                    }

                    Button {
                        id: menu
                        objectName: "trayMenu:" + card.modelData.id
                        Layout.preferredWidth: Theme.controlHeight
                        Layout.preferredHeight: Theme.controlHeight
                        padding: 8
                        hoverEnabled: true
                        text: qsTr("Menu for %1").arg(TrayService.nameFor(card.modelData))
                        Accessible.name: text
                        enabled: root.active && card.modelData.hasMenu
                        opacity: enabled ? 1 : 0.4
                        contentItem: Icon {
                            name: "list"
                            color: menu.hovered || menu.visualFocus ? Theme.accent : Theme.muted
                        }
                        background: Item {}
                        PassiveToolTip {
                            target: menu
                        }
                        onClicked: card.openMenu()
                    }
                }
            }
        }
    }
}
