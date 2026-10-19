pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../ui"
import "network"
import "clipboard"

DrawerPage {
    id: root
    Connections {
        target: ClipboardService
        function onCopied(): void { root.closeRequested(); }
    }
    Component.onCompleted: searchField.submit()
    onActiveChanged: {
        if (active) searchField.submit();
    }
    escapeHandler: null

    headerActions: RowLayout {
        spacing: 4
        NetworkIconButton {
            objectName: "clipboardPause"
            iconName: ClipboardService.paused ? "play" : "pause"
            text: ClipboardService.paused ? qsTr("Resume collection") : qsTr("Pause collection")
            highlighted: ClipboardService.paused
            onClicked: ClipboardService.setPaused(!ClipboardService.paused)
        }
        HoldButton {
            id: clearButton
            objectName: "clipboardClear"
            text: qsTr("Hold to clear clipboard history")
            Accessible.name: text
            implicitWidth: Theme.controlHeight
            implicitHeight: Theme.controlHeight
            horizontalPadding: 8
            verticalPadding: 8
            idleColor: "transparent"
            enabled: ClipboardService.entries.length > 0 && !ClipboardService.loading
            armed: root.active
            contentItem: Icon {
                name: "trash"
                color: clearButton.hovered || clearButton.visualFocus ? Theme.accent : Theme.muted
            }
            onConfirmed: ClipboardService.clear()
        }
    }

    component Note: ShellText {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingMedium

        SearchInput {
            id: searchField
            objectName: "clipboardSearch"
            Layout.fillWidth: true
            placeholderText: qsTr("Search clipboard history")
            debounceInterval: 300
            clearAccessibleName: qsTr("Clear clipboard search")
            onSearchRequested: query => ClipboardService.search(query)
        }
        Note { objectName: "clipboardError"; visible: ClipboardService.error !== ""; text: ClipboardService.error; color: Theme.danger }
        Note {
            objectName: "clipboardPausedNotice"
            visible: ClipboardService.paused
            text: qsTr("Collection is paused. New clipboard items will not be saved.")
            color: Theme.warning
        }
        Note {
            objectName: "clipboardUnavailable"
            visible: !ClipboardService.available && !ClipboardService.loading
            text: qsTr("Clipboard history is unavailable. Install cliphist and wl-clipboard, then restart the shell.")
            color: Theme.muted
        }
        Note {
            objectName: "clipboardEmpty"
            visible: ClipboardService.available && !ClipboardService.loading && ClipboardService.entries.length === 0 && !searchField.text
            text: qsTr("No clipboard history yet. Copy text or an image to add it here.")
        }
        Note {
            objectName: "clipboardNoMatches"
            visible: ClipboardService.available && !ClipboardService.loading && ClipboardService.entries.length === 0 && !!searchField.text
            text: qsTr("No clipboard items match this search.")
        }
        ScrollListView {
            objectName: "clipboardScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8
            model: ClipboardService.entries
            delegate: Rectangle {
                id: card
                required property var modelData
                objectName: "clipboardEntry:" + modelData.id
                width: ListView.view.width
                height: Math.max(58, row.implicitHeight + 12)
                radius: Theme.radius
                color: Theme.surface
                border.color: Theme.border
                Component.onCompleted: if (modelData.image) ClipboardService.loadThumbnail(modelData.id)

                RowLayout {
                    id: row
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 4
                    Button {
                        id: copyItem
                        objectName: "clipboardSelect:" + card.modelData.id
                        Layout.fillWidth: true
                        implicitHeight: Math.max(46, contentItem.implicitHeight + 4)
                        padding: 2
                        hoverEnabled: true
                        Accessible.name: card.modelData.image ? qsTr("Copy image") : qsTr("Copy: %1").arg(card.modelData.preview)
                        onClicked: ClipboardService.copy(card.modelData.id)
                        background: Rectangle {
                            radius: Theme.controlRadius
                            color: copyItem.hovered ? Qt.tint(Theme.surface, Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.12)) : "transparent"
                        }
                        contentItem: RowLayout {
                            spacing: 8
                            Item {
                                visible: card.modelData.image
                                Layout.preferredWidth: 88
                                Layout.preferredHeight: 64
                                Rectangle { anchors.fill: parent; radius: Theme.controlRadius; color: Theme.background }
                                Image {
                                    anchors.fill: parent
                                    source: ClipboardService.thumbnails[card.modelData.id] || ""
                                    fillMode: Image.PreserveAspectFit
                                    asynchronous: true
                                    cache: false
                                    visible: status === Image.Ready
                                }
                                Icon {
                                    anchors.centerIn: parent
                                    name: "camera"
                                    width: 22; height: 22
                                    color: Theme.muted
                                    visible: !ClipboardService.thumbnails[card.modelData.id]
                                }
                            }
                            Icon {
                                visible: !card.modelData.image
                                name: "clipboard"
                                width: 18; height: 18
                                color: Theme.muted
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                ShellText {
                                    Layout.fillWidth: true
                                    text: card.modelData.image ? qsTr("Image") : card.modelData.preview
                                    font.pixelSize: Theme.fontSize
                                    elide: Text.ElideRight
                                    maximumLineCount: 3
                                    wrapMode: Text.Wrap
                                    textFormat: Text.PlainText
                                    color: Theme.text
                                }
                                ShellText {
                                    visible: card.modelData.image
                                    Layout.fillWidth: true
                                    text: card.modelData.preview
                                    color: Theme.muted
                                    font.pixelSize: Theme.smallFontSize
                                    elide: Text.ElideRight
                                    textFormat: Text.PlainText
                                }
                            }
                        }
                    }
                    NetworkIconButton {
                        objectName: "clipboardDelete:" + card.modelData.id
                        iconName: "x"
                        text: qsTr("Remove item")
                        onClicked: ClipboardService.remove(card.modelData.id)
                    }
                }
            }
        }
    }

}
