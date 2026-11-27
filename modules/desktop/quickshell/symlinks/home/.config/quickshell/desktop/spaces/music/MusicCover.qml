import QtQuick
import "../movies"

Rectangle {
    id: root
    property var record: null
    property url previewSource: ""
    property var service
    property bool fetchEnabled: false
    property bool initialized: false
    property var pendingRequest: null
    // The identity the current image belongs to; rows scrolling back reuse it.
    property string shownIdentity: ""
    readonly property bool imageReady: cover.status === Image.Ready
    readonly property string resolvedSource: imageReady ? String(cover.source) : ""
    readonly property string identity: JSON.stringify([record?.source, record?.account, record?.albumId || record?.id, record?.localPath, record?.cover, record?.coverVersion, String(previewSource)])
    color: "#211b24"
    radius: 4
    clip: true
    implicitWidth: 56
    implicitHeight: 56
    Accessible.name: "Cover art"
    MovieIcon {
        anchors.centerIn: parent
        width: 24
        height: 24
        name: "music"
        opacity: .35
        visible: cover.status !== Image.Ready
    }
    Image {
        id: cover
        anchors.fill: parent
        asynchronous: true
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: 128
        sourceSize.height: 128
    }
    function invalidateRequest() {
        if (pendingRequest) {
            pendingRequest.valid = false;
            pendingRequest = null;
        }
    }
    function resolve() {
        if (!fetchEnabled || pendingRequest || shownIdentity === identity)
            return;
        if (String(previewSource)) {
            cover.source = previewSource;
            shownIdentity = identity;
            return;
        }
        if (!record || !service)
            return;
        const request = {
            valid: true
        };
        pendingRequest = request;
        const requested = identity;
        service.request("cover", {
            item: record
        }, (file, error) => {
            if (!request.valid)
                return;
            pendingRequest = null;
            cover.source = error ? "" : file || "";
            // Failures retry the next time the cover becomes visible.
            shownIdentity = error ? "" : requested;
        });
    }
    onIdentityChanged: if (initialized) {
        invalidateRequest();
        cover.source = "";
        shownIdentity = "";
        Qt.callLater(resolve);
    }
    onFetchEnabledChanged: if (initialized)
        Qt.callLater(resolve)
    Component.onCompleted: {
        initialized = true;
        Qt.callLater(resolve);
    }
    Component.onDestruction: invalidateRequest()
}
