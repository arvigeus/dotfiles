pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell

InteractionWindow {
    id: root

    property string title: ""
    property bool leftEdge: false
    readonly property int drawerWidth: Theme.drawerWidth
    property real slideProgress: 0
    property Item contentInitialFocus: null
    default property alias drawerContent: body.data
    initialFocus: contentInitialFocus ?? closeButton
    // Keep this true while open too: opened/keepVisible must not both become
    // false during handoff to closing, which would destroy/recreate lazy content.
    keepVisible: slideProgress > 0
        && (interactionState.activeSurface === null || interactionState.activeSurface === root)
        && Quickshell.screens.includes(presentationScreen)
    backdropOpacity: slideProgress

    function resetPresentation(): void {
        slide.stop();
        slideProgress = 0;
        presentationScreen = null;
    }

    onOpenedChanged: {
        if (opened)
            presentationScreen = interactionState.screen;
        slide.to = opened ? 1 : 0;
        slide.restart();
    }

    NumberAnimation {
        id: slide
        target: root
        property: "slideProgress"
        duration: 200
        easing.type: Easing.OutCubic
        onFinished: if (!root.opened) root.presentationScreen = null
    }

    Connections {
        target: root.interactionState
        function onActiveSurfaceChanged(): void {
            // A replacement opens immediately. Drop the old presentation so
            // two drawers/scrims cannot overlap or briefly obscure the new one.
            if (root.interactionState.activeSurface && root.interactionState.activeSurface !== root) {
                root.resetPresentation();
            }
        }
    }

    Connections {
        target: Quickshell
        function onScreensChanged(): void {
            if (!Quickshell.screens.includes(root.presentationScreen))
                root.resetPresentation();
        }
    }

    Surface {
        id: card
        objectName: "drawerCard"
        x: root.leftEdge ? -width * (1 - root.slideProgress)
            : root.width - width * root.slideProgress
        width: Math.min(root.drawerWidth, root.width)
        height: root.height
        radius: 0
        color: Theme.background
        enabled: root.opened

        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.padding
            spacing: Theme.padding

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                ShellText {
                    text: root.title
                    font.pixelSize: Theme.titleFontSize
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Button {
                    id: closeButton
                    objectName: "drawerClose"
                    text: qsTr("Close %1").arg(root.title)
                    Layout.preferredWidth: Theme.controlHeight
                    Layout.preferredHeight: Theme.controlHeight
                    padding: (Theme.controlHeight - Theme.iconSize) / 2
                    hoverEnabled: true
                    onClicked: root.dismiss()
                    contentItem: Icon {
                        name: "x"
                        color: closeButton.down ? Theme.muted
                            : closeButton.hovered || closeButton.visualFocus ? Theme.accent : Theme.text
                    }
                    background: Rectangle {
                        color: "transparent"
                        radius: Theme.controlRadius
                        // Ghost buttons keep keyboard focus visible without a fill.
                        border.width: closeButton.visualFocus ? 1 : 0
                        border.color: Theme.accent
                    }
                    PassiveToolTip { target: closeButton }
                }
            }

            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }

            Item {
                id: body
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
            }
        }
    }
}
