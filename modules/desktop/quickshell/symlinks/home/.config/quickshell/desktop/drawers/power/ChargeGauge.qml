import QtQuick
import QtQuick.Controls
import "../../ui"

Item {
    id: root
    property real percentage: 0
    property var controller: null
    property bool canAct: false
    property int draft: 0
    signal limitRequested(int value)
    implicitHeight: controller ? 54 : 24
    readonly property alias slider: limit
    readonly property real markerPosition: controller ? (limit.pressed ? draft : controller.limit) / 100 : 0

    Rectangle {
        id: track
        objectName: "batteryLevelTrack"
        x: 4
        width: Math.max(0, root.width - 8)
        y: root.controller ? 32 : 7
        height: 10
        radius: 4
        color: Theme.raised
        Rectangle {
            objectName: "batteryLevelFill"
            width: parent.width * Math.max(0, Math.min(100, root.percentage)) / 100
            height: parent.height
            radius: 4
            color: root.percentage <= 15 ? Theme.warning : Theme.accent
        }
    }
    Slider {
        id: limit
        objectName: "chargeLimitSlider"
        x: track.x
        width: track.width
        y: track.y - 13
        height: 36
        from: root.controller?.minimum ?? 20
        to: root.controller?.maximum ?? 100
        stepSize: root.controller?.step ?? 1
        snapMode: Slider.SnapAlways
        leftPadding: width * from / 100
        rightPadding: width * (1 - to / 100)
        enabled: !!root.controller && root.canAct
        hoverEnabled: true
        Accessible.name: qsTr("Battery charge limit")
        Accessible.description: qsTr("The line marks the charge limit on a 0–100% battery gauge. Drag or use arrow keys to change it.")
        Binding {
            target: limit
            property: "value"
            value: root.controller?.limit ?? 100
            when: !limit.pressed
            restoreMode: Binding.RestoreNone
        }
        onMoved: {
            root.draft = Math.round(value);
            if (!pressed && root.controller && root.draft !== root.controller.limit)
                root.limitRequested(root.draft);
        }
        onPressedChanged: {
            if (pressed)
                root.draft = Math.round(value);
            else if (root.controller && root.canAct && root.draft !== root.controller.limit)
                root.limitRequested(root.draft);
        }
        background: Item {}
        handle: Rectangle {
            objectName: "chargeLimitMarker"
            visible: !!root.controller
            x: limit.leftPadding + limit.position * limit.availableWidth - width / 2
            y: (limit.height - height) / 2
            width: 4
            height: 20
            radius: 2
            color: limit.pressed || limit.visualFocus ? Theme.accent : Theme.text
        }
    }
    Button {
        id: label
        objectName: "chargeLimitApplied"
        visible: !!root.controller
        x: Math.max(0, Math.min(root.width - width, track.x + track.width * root.markerPosition - width / 2))
        y: 0
        height: 21
        width: contentItem.implicitWidth + 8
        padding: 4
        hoverEnabled: true
        activeFocusOnTab: false
        text: qsTr("%1% limit").arg(root.controller ? limit.pressed ? root.draft : root.controller.limit : "")
        contentItem: ShellText {
            text: label.text
            color: limit.hovered || limit.visualFocus ? Theme.text : Theme.muted
            font.pixelSize: Theme.smallFontSize
        }
        background: Item {}
        PassiveToolTip {
            target: label
            text: qsTr("Charge limit. Drag the line to change it. A lower limit reduces time spent fully charged; it does not discharge the battery.")
        }
    }
}
