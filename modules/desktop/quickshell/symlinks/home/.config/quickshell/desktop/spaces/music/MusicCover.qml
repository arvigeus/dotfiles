import QtQuick
import "../movies"

Rectangle {
    id: root
    property var record: null
    property url previewSource: ""
    property var service
    property bool fetchEnabled: false
    property bool initialized: false
    property int generation: 0
    readonly property bool imageReady: cover.status === Image.Ready
    readonly property string identity: JSON.stringify([record?.source,record?.account,record?.albumId || record?.id,record?.localPath,record?.cover,record?.coverVersion,String(previewSource)])
    color: "#211b24"
    radius: 4
    clip: true
    implicitWidth: 56
    implicitHeight: 56
    Accessible.name: "Cover art"
    MovieIcon { anchors.centerIn: parent; width: 24; height: 24; name: "music"; opacity: .35; visible: cover.status !== Image.Ready }
    Image { id: cover; anchors.fill: parent; asynchronous: true; fillMode: Image.PreserveAspectCrop; sourceSize.width: 128; sourceSize.height: 128 }
    function resolve() {
        const token = ++generation;
        if (!fetchEnabled) return;
        if (String(previewSource)) { cover.source=previewSource; return; }
        if (!record || !service) return;
        cover.source = "";
        service.request("cover",{item:record},(file,error) => {
            if (token === generation && fetchEnabled) cover.source = error ? "" : file || "";
        });
    }
    onIdentityChanged: if (initialized) resolve()
    onFetchEnabledChanged: if (initialized) resolve()
    Component.onCompleted: { initialized = true; resolve(); }
    Component.onDestruction: ++generation
}
