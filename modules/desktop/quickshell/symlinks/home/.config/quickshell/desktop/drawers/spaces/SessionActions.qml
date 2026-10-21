pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ColumnLayout {
    id: root
    objectName: "session-actions"
    required property bool active
    property var service: SessionService
    readonly property bool popupOpen: shutdownMenu.visible || sleepMenu.visible || lockingMenu.visible || restartMenu.visible
    readonly property alias shutdownPopup: shutdownMenu
    readonly property alias sleepPopup: sleepMenu
    readonly property alias lockingPopup: lockingMenu
    readonly property alias restartPopup: restartMenu
    function closePopup(): void { shutdownMenu.close(); sleepMenu.close(); lockingMenu.close(); restartMenu.close(); }
    function togglePopup(menu): void {
        const opening = !menu.visible;
        closePopup();
        if (opening) menu.open();
    }
    onActiveChanged: if (!active) closePopup()
    spacing: 6

    component SessionControl: Item {
        id: control
        required property string action
        required property string label
        required property string iconName
        property bool restoring: false
        property bool hasOptions: false
        property bool optionsEnabled: true
        property bool menuOpen: false
        property string optionsName: ""
        readonly property alias menuButton: options
        signal restoreRequested()
        signal optionsClicked()
        Layout.fillWidth: true; Layout.preferredWidth: 1
        Layout.minimumWidth: buttons.width
        implicitHeight: 42

        Item {
            id: buttons
            anchors.centerIn: parent
            width: control.hasOptions ? 64 : 42; height: 42
            HoverHandler { id: buttonsHover }
            ButtonBackground {
                anchors.fill: parent
                highlighted: buttonsHover.hovered || primary.visualFocus || options.visualFocus || control.menuOpen || control.restoring
                pressed: primary.down || options.down
                Rectangle {
                    anchors.left: parent.left; anchors.bottom: parent.bottom
                    width: parent.width * primary.progress; height: 3; radius: 1; color: Theme.danger
                }
            }
            HoldButton {
                id: primary
                objectName: "session-action-" + control.action
                anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
                width: 42
                holdDuration: 2000; armed: root.active && !control.restoring
                toolTipEnabled: false
                enabled: root.active && !root.service.busy && (control.restoring || !!root.service.state.capabilities[control.action])
                text: control.label; Accessible.name: text
                iconName: control.iconName
                background: Item {}
                contentItem: Item {
                    Icon {
                        objectName: primary.objectName + "Icon"
                        anchors.centerIn: parent; width: 20; height: 20
                        name: control.iconName
                        color: control.restoring ? Theme.accent : Theme.text
                    }
                }
                onConfirmed: root.service.execute(control.action)
                onClicked: if (control.restoring) control.restoreRequested()
                PassiveToolTip {
                    target: primary; above: true
                    text: control.restoring ? control.label : control.label + "\n" + qsTr("Hold for 2 seconds to confirm.")
                }
            }
            Button {
                id: options
                objectName: control.optionsName
                visible: control.hasOptions
                anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
                width: 20; padding: 3; hoverEnabled: true
                enabled: root.active && !root.service.busy && control.optionsEnabled
                Accessible.name: qsTr("%1 options").arg(control.label)
                background: Item {}
                contentItem: Icon { name: "chevron-up" }
                onClicked: control.optionsClicked()
                PassiveToolTip { target: options; above: true; text: qsTr("%1 options").arg(control.label) }
            }
        }
    }
    component PauseOption: ShellButton {
        id: option
        Layout.fillWidth: true
        idleColor: "transparent"
        enabled: root.active && !root.service.busy && !!root.service.pausesAvailable
        contentItem: RowLayout {
            spacing: 8
            Icon { name: option.iconName; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
            ShellText { Layout.fillWidth: true; text: option.text; wrapMode: Text.WordWrap }
        }
    }

    RowLayout {
        Layout.fillWidth: true; spacing: 8
        SessionControl {
            id: logoutControl
            action: "logout"; label: restoring ? qsTr("Enable automatic locking") : qsTr("Go to gaming mode")
            restoring: !!root.service.lockingPaused
            iconName: restoring ? "lock-open" : "log-out"
            hasOptions: true; optionsEnabled: !!root.service.pausesAvailable
            optionsName: "sessionLockOptions"; menuOpen: lockingMenu.visible
            onRestoreRequested: root.service.setLockingPaused(false)
            onOptionsClicked: root.togglePopup(lockingMenu)
        }
        SessionControl {
            id: sleepControl
            action: "suspend"; label: restoring ? qsTr("Enable automatic sleep") : qsTr("Sleep")
            restoring: !!root.service.sleepPaused
            iconName: restoring ? "coffee" : "moon"
            hasOptions: true; optionsEnabled: !!root.service.pausesAvailable
            optionsName: "sessionSleepOptions"; menuOpen: sleepMenu.visible
            onRestoreRequested: root.service.setSleepPaused(false)
            onOptionsClicked: root.togglePopup(sleepMenu)
        }
        SessionControl {
            id: restartControl
            action: "reboot"; label: qsTr("Restart computer"); iconName: "rotate-ccw"
            hasOptions: true; optionsEnabled: !!root.service.state.capabilities.reload
            optionsName: "sessionRestartOptions"; menuOpen: restartMenu.visible
            onOptionsClicked: root.togglePopup(restartMenu)
        }
        SessionControl {
            id: shutdownControl
            action: "poweroff"; label: qsTr("Power off"); iconName: "power"
            hasOptions: true; optionsEnabled: !!root.service.state.capabilities.poweroff
            optionsName: "sessionShutdownOptions"; menuOpen: shutdownMenu.visible
            onOptionsClicked: root.togglePopup(shutdownMenu)
        }
    }
    InfoPopover {
        id: lockingMenu
        objectName: "sessionLockPopup"
        button: logoutControl.menuButton; active: root.active
        y: -height - 8; width: Math.min(280, Math.max(0, (Overlay.overlay?.width ?? 296) - 16))
        padding: 10
        PauseOption {
            objectName: "sessionPauseLocking"
            iconName: "lock-open"
            text: root.service.lockingPaused ? qsTr("Enable automatic locking") : qsTr("Disable automatic locking")
            onClicked: { root.service.setLockingPaused(!root.service.lockingPaused); root.closePopup(); }
        }
    }
    InfoPopover {
        id: sleepMenu
        objectName: "sessionSleepPopup"
        button: sleepControl.menuButton; active: root.active
        y: -height - 8; width: Math.min(280, Math.max(0, (Overlay.overlay?.width ?? 296) - 16))
        padding: 10
        PauseOption {
            objectName: "sessionPauseSleep"
            iconName: "coffee"
            text: root.service.sleepPaused ? qsTr("Enable automatic sleep") : qsTr("Disable automatic sleep")
            onClicked: { root.service.setSleepPaused(!root.service.sleepPaused); root.closePopup(); }
        }
    }
    InfoPopover {
        id: restartMenu
        objectName: "sessionRestartPopup"
        button: restartControl.menuButton; active: root.active
        y: -height - 8; width: Math.min(280, Math.max(0, (Overlay.overlay?.width ?? 296) - 16))
        padding: 10
        HoldButton {
            objectName: "sessionReload"
            Layout.fillWidth: true
            text: qsTr("Reload"); iconName: "refresh-cw"; idleColor: "transparent"
            hint: qsTr("Close applications and restart the desktop session")
            holdDuration: 2000; armed: root.active && restartMenu.visible
            enabled: root.active && !root.service.busy && !!root.service.state.capabilities.reload
            onConfirmed: { root.service.execute("reload"); root.closePopup(); }
        }
    }
    InfoPopover {
        id: shutdownMenu
        objectName: "sessionShutdownPopup"
        button: shutdownControl.menuButton; active: root.active
        y: -height - 8
        width: Math.min(280, Math.max(0, (Overlay.overlay?.width ?? 296) - 16))
        padding: 10
        ShellText { text: qsTr("Shut down in"); color: Theme.muted }
        GridLayout {
            Layout.fillWidth: true; columns: 2
            columnSpacing: 4; rowSpacing: 4
            Repeater {
                model: [
                    {minutes: 15, label: qsTr("15 min")}, {minutes: 30, label: qsTr("30 min")},
                    {minutes: 60, label: qsTr("1 hour")}, {minutes: 90, label: qsTr("90 min")},
                    {minutes: 120, label: qsTr("2 hours")}, {minutes: 180, label: qsTr("3 hours")},
                    {minutes: 240, label: qsTr("4 hours")}, {minutes: 300, label: qsTr("5 hours")}
                ]
                HoldButton {
                    id: delay
                    required property var modelData
                    objectName: "sessionDelay:" + modelData.minutes
                    Layout.fillWidth: true; Layout.preferredWidth: 1
                    idleColor: "transparent"; toolTipEnabled: false
                    text: modelData.label; iconName: "power"
                    holdDuration: 2000; armed: root.active && shutdownMenu.visible
                    enabled: root.active && !root.service.busy && !!root.service.state.capabilities.poweroff
                    contentItem: RowLayout {
                        spacing: 8
                        Icon { name: delay.iconName; Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
                        ShellText {
                            objectName: delay.objectName + "Label"
                            Layout.fillWidth: true; text: delay.text
                            wrapMode: Text.WordWrap
                        }
                    }
                    onConfirmed: { root.service.execute("schedule-poweroff", modelData.minutes); shutdownMenu.close(); }
                }
            }
        }
        ShellText {
            Layout.fillWidth: true; visible: text !== ""
            text: root.service.state.scheduledShutdown; wrapMode: Text.Wrap
            color: Theme.muted; font.pixelSize: Theme.smallFontSize
        }
        ShellButton {
            objectName: "sessionCancelShutdown"
            Layout.fillWidth: true; visible: !!root.service.state.scheduledShutdown
            enabled: root.active && !root.service.busy
            text: qsTr("Cancel scheduled shutdown"); idleColor: "transparent"
            onClicked: { root.service.execute("cancel-poweroff"); shutdownMenu.close(); }
        }
    }
    ShellText {
        objectName: "sessionError"
        Layout.fillWidth: true; visible: text !== ""
        text: root.service.error; color: Theme.danger; wrapMode: Text.Wrap
    }
}
