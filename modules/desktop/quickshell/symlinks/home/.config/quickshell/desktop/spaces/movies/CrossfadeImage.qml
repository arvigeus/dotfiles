import QtQuick
import QtQuick.Window
import "../../ui"

Item {
    id: root
    property url source
    property int fillMode: Image.PreserveAspectCrop
    property int horizontalAlignment: Image.AlignHCenter
    property int imageWidth: 2560
    property int duration: 320
    // Only identity-sensitive artwork opts into a bounded old-image grace period.
    property string ownerKey: ""
    property int staleAfter: 0
    property bool fadeInOnTop: false
    property bool resetOnSourceChange: false
    property bool frontIsA: false
    property url displayedSource: ""
    readonly property real imageOpacity: Math.max(a.opacity,b.opacity)
    readonly property bool loading: a.loadStatus === Image.Loading || b.loadStatus === Image.Loading || retry.running
    readonly property bool transitioning: fade.running
    property string failedSource: ""
    property int retryCount: 0
    readonly property bool hasImage: !!displayedSource.toString()
    property var incoming: null
    property var expiredBuffer: null
    onOwnerKeyChanged: if (staleAfter > 0) staleGuard.restart()
    function expireDisplayed() {
        if (!displayedSource.toString() || displayedSource.toString() === source.toString()) return;
        // A ready replacement is already crossfading; let that transition finish.
        if (fade.running && incoming && incoming.loadStatus === Image.Ready && incoming.remoteSource.toString() === source.toString()) return;
        const old = frontIsA ? a : b;
        // Keep the pixels until the backdrop's opacity transition finishes, so
        // the poster can crossfade underneath instead of fading up from black.
        expiredBuffer = old;
        displayedSource = "";
        releaseExpired.restart();
    }
    Timer {
        id: staleGuard
        interval: Math.max(1, root.staleAfter)
        onTriggered: root.expireDisplayed()
    }
    Timer {
        id: releaseExpired
        interval: Math.max(320, root.duration)
        onTriggered: {
            const old = root.expiredBuffer;
            root.expiredBuffer = null;
            if (old && old !== root.incoming && (!root.displayedSource.toString() || old !== (root.frontIsA ? a : b))) {
                old.opacity = 0;
                old.remoteSource = "";
            }
        }
    }
    function clear() {
        fade.stop();
        retry.stop();
        releaseExpired.stop();
        expiredBuffer = null;
        incoming = null;
        a.opacity = 0; b.opacity = 0;
        a.remoteSource = ""; b.remoteSource = "";
        frontIsA = false;
        displayedSource = "";
        failedSource = "";
        retryCount = 0;
    }
    onSourceChanged: {
        // A later metadata URL must not extend the same selection's deadline.
        if (staleAfter > 0 && !staleGuard.running) staleGuard.restart();
        failedSource = "";
        retryCount = 0;
        retry.stop();
        if (resetOnSourceChange) {
            clear();
        } else if (fade.running && incoming && incoming.remoteSource.toString() !== source.toString()) {
            // A newer request supersedes the image currently fading in.
            fade.stop();
            const outgoing = frontIsA ? a : b;
            outgoing.opacity = 1;
            incoming.opacity = 0;
            incoming.remoteSource = "";
            incoming = null;
        }
        prepare();
    }
    function prepare() {
        if (fade.running || source.toString() === displayedSource.toString() || (failedSource && failedSource === source.toString())) return;
        incoming = frontIsA ? b : a;
        incoming.opacity = 0;
        incoming.cache = retryCount === 0;
        incoming.remoteSource = source;
        if (!source.toString()) {
            // A missing URL may still arrive with metadata. Let the same grace
            // timer reveal the poster, rather than fading to an empty buffer.
            if (staleAfter > 0 && displayedSource.toString()) return;
            fade.start(); return;
        }
        if (incoming && incoming.loadStatus === Image.Ready) ready(incoming);
    }
    function ready(item) {
        if (item !== incoming || fade.running) return;
        if (item.loadStatus === Image.Error) {
            failedSource = item.remoteSource.toString();
            item.remoteSource = "";
            if (retryCount < 1 && source.toString()) { retryCount++; retry.restart(); }
            if (displayedSource.toString()) { incoming = null; return; }
            fade.start();
            return;
        }
        if (item.loadStatus !== Image.Ready) return;
        if (item.remoteSource.toString() !== source.toString()) { prepare(); return; }
        if (!displayedSource.toString()) {
            const outgoing = frontIsA ? a : b;
            if (outgoing !== item) { outgoing.opacity = 0; outgoing.remoteSource = ""; }
            item.opacity = 1;
            frontIsA = item === a;
            incoming = null;
            // Observers may request the next resolution as soon as this one is
            // displayed. Publish it only after the buffer state is consistent.
            displayedSource = item.remoteSource;
        } else fade.start();
    }
    Timer {
        id: retry
        interval: 1800
        onTriggered: {
            if (!root.source.toString() || root.source.toString() !== root.failedSource) return;
            root.failedSource = "";
            root.prepare();
        }
    }
    // Error handling can clear a buffer. Defer it until loadStatus has finished
    // evaluating. Owned timers also cancel pending handlers when Movies closes.
    Timer { id: readyA; interval: 0; onTriggered: root.ready(a) }
    Timer { id: readyB; interval: 0; onTriggered: root.ready(b) }
    CachedImage { id: a; objectName: "imageA"; anchors.fill: parent; asynchronous: true; opacity: 0; fillMode: root.fillMode; horizontalAlignment: root.horizontalAlignment; sourceSize.width: Math.min(root.imageWidth, Math.max(1, Math.ceil(root.width * Screen.devicePixelRatio))); onLoadStatusChanged: readyA.restart() }
    CachedImage { id: b; objectName: "imageB"; anchors.fill: parent; asynchronous: true; opacity: 0; fillMode: root.fillMode; horizontalAlignment: root.horizontalAlignment; sourceSize.width: Math.min(root.imageWidth, Math.max(1, Math.ceil(root.width * Screen.devicePixelRatio))); onLoadStatusChanged: readyB.restart() }
    ParallelAnimation {
        id: fade
        NumberAnimation { target: root.incoming; property: "opacity"; to: root.incoming && root.incoming.remoteSource.toString() ? 1 : 0; duration: root.duration; easing.type: Easing.InOutQuad }
        NumberAnimation { target: root.frontIsA ? a : b; property: "opacity"; to: root.fadeInOnTop ? 1 : 0; duration: root.duration; easing.type: Easing.InOutQuad }
        onFinished: {
            const completed = root.incoming;
            const outgoing = root.frontIsA ? a : b;
            root.frontIsA = completed === a;
            outgoing.opacity = 0;
            outgoing.remoteSource = "";
            root.incoming = null;
            root.displayedSource = completed.remoteSource;
            root.prepare();
        }
    }
}
