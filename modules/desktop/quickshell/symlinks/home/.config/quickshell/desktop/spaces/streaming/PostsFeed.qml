import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui" as Desktop
import "../movies"

ListView {
    id: root
    required property var controller
    signal paginationCheckRequested
    objectName: "streamingPostsFeed"
    clip: true
    spacing: 20
    onContentYChanged: paginationCheckRequested()
    onContentHeightChanged: paginationCheckRequested()
    onHeightChanged: paginationCheckRequested()
    Desktop.WheelScroll {
        view: root
        wheelStep: 360
    }
    ScrollBar.vertical: MovieScrollBar {}
    delegate: Item {
        id: card
        required property string payload
        readonly property var post: JSON.parse(payload)
        width: root.width
        height: body.implicitHeight + 32
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width, 960)
            height: parent.height
            radius: MovieStyle.radius
            color: MovieStyle.surface
            border.color: MovieStyle.border
            ColumnLayout {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 16
                spacing: 14
                RowLayout {
                    Layout.fillWidth: true
                    Rectangle {
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        radius: 21
                        color: MovieStyle.raised
                        MovieText {
                            objectName: "streamingPostAvatarFallback:" + card.post.id
                            anchors.centerIn: parent
                            text: card.post.creator.slice(0, 1).toUpperCase()
                            font.bold: true
                            font.pixelSize: 20
                            visible: avatar.loadStatus !== Image.Ready
                        }
                        CachedImage {
                            id: avatar
                            objectName: "streamingPostAvatar:" + card.post.id
                            anchors.fill: parent
                            remoteSource: card.post.avatar || ""
                            sourceSize.width: 84
                            fillMode: Image.PreserveAspectCrop
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        MovieText {
                            Layout.fillWidth: true
                            text: card.post.creator
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        MovieText {
                            text: card.post.published
                            color: MovieStyle.muted
                            font.pixelSize: 12
                        }
                    }
                    MovieButton {
                        objectName: "streamingPostSubscribe:" + card.post.id
                        text: root.controller.followedChannel(card.post) ? "Unsubscribe" : "Subscribe"
                        enabled: !root.controller.commandPending
                        onClicked: root.controller.toggleSubscription(card.post)
                    }
                }
                TextEdit {
                    Layout.fillWidth: true
                    Layout.preferredHeight: contentHeight
                    text: card.post.text
                    readOnly: true
                    selectByMouse: true
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    color: MovieStyle.text
                    selectionColor: MovieStyle.accent
                    font.family: MovieStyle.fontFamily
                    font.pixelSize: MovieStyle.fontSize + 1
                }
                Flickable {
                    id: images
                    visible: card.post.images.length > 0
                    Layout.fillWidth: true
                    Layout.preferredHeight: visible ? 300 : 0
                    clip: true
                    contentWidth: imageRow.implicitWidth
                    contentHeight: height
                    Desktop.WheelScroll {
                        view: images
                        orientation: Qt.Horizontal
                        verticalToHorizontal: true
                    }
                    Row {
                        id: imageRow
                        spacing: 12
                        height: images.height
                        Repeater {
                            model: card.post.images
                            Rectangle {
                                required property string modelData
                                width: Math.min(images.width, 480)
                                height: images.height
                                color: "#66000000"
                                radius: 6
                                CachedImage {
                                    anchors.fill: parent
                                    remoteSource: modelData
                                    sourceSize.width: 960
                                    fillMode: Image.PreserveAspectFit
                                }
                            }
                        }
                    }
                    ScrollBar.horizontal: MovieScrollBar {}
                }
                Repeater {
                    model: card.post.poll
                    Rectangle {
                        required property string modelData
                        Layout.fillWidth: true
                        implicitHeight: option.implicitHeight + 20
                        color: MovieStyle.background
                        radius: 6
                        border.color: MovieStyle.border
                        MovieText {
                            id: option
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 10
                            text: modelData
                            wrapMode: Text.Wrap
                        }
                    }
                }
                MovieText {
                    visible: !!card.post.votes
                    text: card.post.votes
                    color: MovieStyle.muted
                }
                Repeater {
                    model: card.post.videos
                    MovieButton {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData.title
                        iconName: "play"
                        onClicked: root.controller.handleOpen({
                            url: modelData.url
                        })
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    MovieText {
                        text: card.post.likes ? card.post.likes + " likes" : ""
                        color: MovieStyle.muted
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    MovieButton {
                        text: "Open post on YouTube"
                        iconName: "globe"
                        onClicked: root.controller.openPost(card.post.id)
                    }
                }
            }
        }
    }
    MovieText {
        anchors.centerIn: parent
        width: Math.min(parent.width - 32, 560)
        visible: !root.controller.loading && root.count === 0
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        color: MovieStyle.muted
        text: root.controller.channels.length ? "No public posts found for these creators." : "Follow creators to see their public posts here."
    }
}
