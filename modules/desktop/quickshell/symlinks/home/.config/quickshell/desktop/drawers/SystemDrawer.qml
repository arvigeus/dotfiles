pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../ui"
import "network"
import "power"
import "system"

DrawerPage {
    id: root
    property var service: backend
    property Popup informationPopup: null
    readonly property alias bootPopover: bootDetails
    readonly property alias servicesPopover: serviceDetails
    readonly property string requestedSection: informationPopup ? "info" : bootDetails.visible ? "boot"
        : serviceDetails.visible ? "services" : ""
    SystemService { id: backend; active: root.active && root.service === backend; section: root.requestedSection }
    readonly property var state: service.state
    escapeHandler: !!informationPopup || bootDetails.visible || serviceDetails.visible
        ? (() => { closePopovers(); return true; }) : null
    onActiveChanged: if (!active) closePopovers()
    function closePopovers(): void { informationPopup?.close(); bootDetails.close(); serviceDetails.close(); }
    function uptime(value): string {
        if (value === null) return qsTr("Unavailable");
        const minutes = Math.floor(value / 60), hours = Math.floor(minutes / 60), days = Math.floor(hours / 24);
        return days ? qsTr("%1 d %2 h").arg(days).arg(hours % 24) : hours ? qsTr("%1 h %2 min").arg(hours).arg(minutes % 60) : qsTr("%1 min").arg(minutes);
    }
    function logs(scope = "system", unit = ""): void { service.openTerminal("logs", scope, unit); }
    headerActions: NetworkIconButton {
        id: information
        objectName: "systemInfo"; iconName: "info"; text: qsTr("System information")
        enabled: root.active; checked: systemInfo.visible
        onClicked: { if (systemInfo.visible) systemInfo.close(); else systemInfo.open(); }
        InfoPopover {
            id: systemInfo
            objectName: "systemInfoPopup"; button: information; active: root.active
            width: Math.min(root.width, Math.max(0, (Overlay.overlay?.width ?? root.width + 16) - 16))
            onAboutToShow: { root.closePopovers(); root.informationPopup = systemInfo; }
            onDismissed: if (root.informationPopup === systemInfo) root.informationPopup = null
            LoadStatus {}
            PowerCard {
                visible: root.service.loaded
                objectName: "systemInfoCard"
                title: root.state.os
                Reading { label: qsTr("Kernel"); value: root.state.kernel }
                Reading { label: qsTr("Uptime"); value: root.uptime(root.state.uptime) }
                Note {
                    visible: root.state.reboot || root.state.kernelChanged; color: Theme.warning
                    text: root.state.reboot ? qsTr("A restart is required to finish updates.") : qsTr("Running kernel modules are missing. A newer kernel may be installed; consider restarting.")
                }
            }
        }
    }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    component LoadStatus: ColumnLayout {
        Layout.fillWidth: true
        visible: !root.service.loaded || root.service.error !== ""
        Note { visible: root.service.busy; text: qsTr("Reading system information…") }
        Note { visible: root.service.error !== ""; text: root.service.error; color: Theme.danger }
    }
    component Reading: RowLayout {
        property string label
        property string value
        Layout.fillWidth: true; spacing: 12
        Note { text: parent.label }
        ShellText { text: parent.value; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true; horizontalAlignment: Text.AlignRight }
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 12
        ColumnLayout {
            Layout.fillWidth: true; spacing: 8
            DrawerActionButton {
                objectName: "systemUpdate"; text: qsTr("Update system"); iconName: "download"
                Layout.fillWidth: true; Layout.minimumWidth: 0
                enabled: root.active
                onClicked: { root.closePopovers(); root.service.openTerminal("update"); }
            }
            DrawerActionButton {
                id: bootButton
                objectName: "systemBoot"; text: qsTr("Boot times"); iconName: "gauge"
                Layout.fillWidth: true; Layout.minimumWidth: 0; highlighted: bootDetails.visible
                enabled: root.active
                onClicked: {
                    if (bootDetails.visible) bootDetails.close();
                    else { root.closePopovers(); bootDetails.open(); }
                }
                InfoPopover {
                    id: bootDetails
                    objectName: "systemBootPopover"
                    button: bootButton; active: root.active
                    width: Math.min(root.width, Math.max(0, (Overlay.overlay?.width ?? root.width + 16) - 16))
                    LoadStatus {}
                    PowerCard {
                        visible: root.service.loaded
                        title: root.state.boot.total ? qsTr("Startup · %1").arg(root.state.boot.total) : qsTr("Startup")
                        Note { visible: !!root.state.errors.boot; text: root.state.errors.boot || "" }
                        Repeater {
                            model: root.state.boot.phases
                            Reading { required property var modelData; label: modelData.label; value: modelData.duration }
                        }
                    }
                    PowerCard {
                        visible: root.service.loaded
                        title: qsTr("Slowest startup units")
                        Note { visible: !!root.state.errors.slow; text: root.state.errors.slow || "" }
                        Note { visible: !root.state.errors.slow && !root.state.slow.length; text: qsTr("No startup timings reported.") }
                        Repeater {
                            model: root.state.slow
                            Reading { required property var modelData; label: modelData.unit; value: modelData.duration }
                        }
                        Note { text: qsTr("Units start in parallel; these times do not add up to the boot total.") }
                    }
                }
            }
            DrawerActionButton {
                id: servicesButton
                objectName: "systemServices"; text: qsTr("Services"); iconName: "settings"
                Layout.fillWidth: true; Layout.minimumWidth: 0; highlighted: serviceDetails.visible
                enabled: root.active
                onClicked: {
                    if (serviceDetails.visible) serviceDetails.close();
                    else { root.closePopovers(); serviceDetails.open(); }
                }
                InfoPopover {
                    id: serviceDetails
                    objectName: "systemServicesPopover"
                    button: servicesButton; active: root.active
                    width: Math.min(root.width, Math.max(0, (Overlay.overlay?.width ?? root.width + 16) - 16))
                    LoadStatus {}
                    Repeater {
                        model: root.service.loaded ? root.state.scopes : []
                        PowerCard {
                            visible: root.service.loaded
                            id: scopeCard
                            required property var modelData
                            title: modelData.scope === "user" ? qsTr("User services") : qsTr("System services")
                            Note { visible: !!root.state.errors[scopeCard.modelData.scope]; text: root.state.errors[scopeCard.modelData.scope] || "" }
                            Note { visible: !root.state.errors[scopeCard.modelData.scope] && !scopeCard.modelData.failed.length; text: qsTr("No failed units."); color: Theme.success }
                            Repeater {
                                model: scopeCard.modelData.failed
                                RowLayout {
                                    required property var modelData
                                    Layout.fillWidth: true
                                    ColumnLayout {
                                        Layout.fillWidth: true; Layout.minimumWidth: 0; spacing: 2
                                        Note { text: parent.parent.modelData.unit; color: Theme.danger }
                                        Note { text: parent.parent.modelData.description }
                                    }
                                    NetworkIconButton {
                                        iconName: "list"; text: qsTr("Open unit logs"); enabled: root.state.terminalAvailable
                                        onClicked: root.logs(scopeCard.modelData.scope, parent.modelData.unit)
                                    }
                                }
                            }
                            ShellButton {
                                text: qsTr("Warning logs"); iconName: "list"; Layout.fillWidth: true
                                enabled: root.state.terminalAvailable; onClicked: root.logs(scopeCard.modelData.scope)
                            }
                        }
                    }
                    PowerCard {
                        visible: root.service.loaded
                        title: qsTr("Upcoming timers")
                        Note { visible: !!root.state.errors.systemTimers; text: root.state.errors.systemTimers || "" }
                        Note { visible: !!root.state.errors.userTimers; text: root.state.errors.userTimers || "" }
                        Note { visible: !root.state.timers.length; text: qsTr("No scheduled timers reported.") }
                        Repeater {
                            model: root.state.timers
                            ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true; spacing: 2
                                Note { text: parent.modelData.unit; color: Theme.text }
                                Note { text: (parent.modelData.scope === "user" ? qsTr("User") : qsTr("System")) + " · " + Qt.formatDateTime(new Date(parent.modelData.next), "ddd d MMM HH:mm") }
                            }
                        }
                    }
                }
            }
            DrawerActionButton {
                id: repairSigning
                objectName: "systemRepairSigning"; text: qsTr("Repair signing keys"); iconName: "lock-keyhole"
                Layout.fillWidth: true; Layout.minimumWidth: 0
                enabled: root.active
                PassiveToolTip {
                    target: repairSigning
                    text: qsTr("Reload installed signing keys and rebuild trust, keeping custom keys and local signatures.")
                }
                onClicked: { root.closePopovers(); root.service.openTerminal("repair-signing"); }
            }
            DrawerActionButton {
                id: checkPackages
                objectName: "systemCheckPackages"; text: qsTr("Check package health"); iconName: "heart"
                Layout.fillWidth: true; Layout.minimumWidth: 0
                enabled: root.active
                PassiveToolTip {
                    target: checkPackages
                    text: qsTr("Check for missing package files and dependency problems. Review the report in a terminal, with an option to reinstall affected repository packages.")
                }
                onClicked: { root.closePopovers(); root.service.openTerminal("check-packages"); }
            }
        }
        Item { Layout.fillHeight: true }
    }
}
