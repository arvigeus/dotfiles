import QtQuick

// Explicit theme colors: the platform style's BusyIndicator can be black on a
// dark surface. Rotation animates a cached ring without repainting each frame.
Item {
    id: root
    property bool running: true
    property color foreground: Theme.text
    property color track: Theme.border
    implicitWidth: 24
    implicitHeight: 24
    onForegroundChanged: ring.requestPaint()
    onTrackChanged: ring.requestPaint()
    Canvas {
        id: ring
        anchors.fill: parent
        // Retained/asynchronously loaded pages can first expose a zero-size
        // canvas. Paint once it has a surface and whenever that surface returns.
        onAvailableChanged: if (available) requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onVisibleChanged: if (visible) requestPaint()
        onPaint: {
            const ctx = getContext("2d");
            ctx.reset();
            const radius = Math.max(0, Math.min(width, height) / 2 - 2);
            ctx.lineWidth = 2;
            ctx.strokeStyle = root.track;
            ctx.beginPath(); ctx.arc(width / 2, height / 2, radius, 0, Math.PI * 2); ctx.stroke();
            ctx.strokeStyle = root.foreground;
            ctx.lineCap = "round";
            ctx.beginPath(); ctx.arc(width / 2, height / 2, radius, -Math.PI / 2, Math.PI * 0.6); ctx.stroke();
        }
        RotationAnimator on rotation { from: 0; to: 360; duration: 900; loops: Animation.Infinite; running: root.running && root.visible }
    }
}
