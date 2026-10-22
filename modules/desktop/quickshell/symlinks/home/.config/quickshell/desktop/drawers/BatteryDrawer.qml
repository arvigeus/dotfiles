pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.UPower
import "../ui"
import "power"
import "power/Format.js" as Format

DrawerPage {
    id: root
    property var service: PowerService
    property var session: PowerSession
    property var upower: UPower
    readonly property var batteries: upower.devices.values.filter(device => device.isLaptopBattery && device.isPresent)
    readonly property var peripherals: upower.devices.values.filter(device => device.isPresent && !device.powerSupply
        && device.type > UPowerDeviceType.LinePower)
    // UPower's display device combines all system batteries and their charging order.
    readonly property var summary: batteries.length ? upower.displayDevice : null
    readonly property real percentage: summary ? summary.percentage * 100 : 0
    readonly property bool onBattery: upower.onBattery
    readonly property var care: service.state.hardware.find(row => row.limit !== null) ?? null
    readonly property bool chargePending: !!session.state.once
    readonly property bool canAct: active && service.loaded && !service.changing
    Component.onCompleted: service.observe(root, active, false)
    Component.onDestruction: service.observe(root, false, false)
    onActiveChanged: service.observe(root, active, false)
    headerActions: IconButton {
        objectName: "batteryRefresh"; iconName: "refresh-cw"; text: qsTr("Refresh battery care")
        enabled: !root.service.reading
        onClicked: root.service.refresh()
    }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    component Heading: ShellText { Layout.fillWidth: true; font.weight: Font.DemiBold; textFormat: Text.PlainText }
    component PackMetric: MetricChip {
        Layout.minimumWidth: 0
        padding: root.width < 340 ? 2 : 6
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 8
        DrawerColumn {
            objectName: "batteryScroll"; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
            Note { visible: root.service.error !== ""; text: root.service.error; color: Theme.danger }
            Note { visible: root.session.error !== ""; text: root.session.error; color: Theme.danger }
            Heading { objectName: "batteriesHeading"; text: qsTr("Batteries") }
            PowerCard {
                objectName: "batteryCard"
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1
                        Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                        spacing: 0
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            IconButton {
                                id: powerSource
                                objectName: "batteryPowerSource"
                                visible: root.width >= 340
                                iconName: root.summary?.state === UPowerDeviceState.Charging ? "battery-charging" : "battery-medium"
                                iconColor: root.onBattery ? Theme.text : Theme.success
                                text: root.summary ? Format.batteryState(root.summary.state) : qsTr("Power source")
                                hint: text + "\n" + (root.onBattery ? qsTr("Running on battery") : qsTr("External power connected"))
                                Accessible.role: Accessible.StaticText; activeFocusOnTab: false
                                contentItem: Icon { name: powerSource.iconName; color: powerSource.iconColor }
                                background: Item {}
                            }
                            ShellText {
                                objectName: "batteryPercentage"
                                text: root.summary ? Format.compact(root.percentage, "%") : qsTr("No system battery")
                                font.pixelSize: root.summary ? root.width < 340 ? 28 : 32 : Theme.titleFontSize
                                Layout.fillWidth: true; wrapMode: Text.Wrap
                            }
                        }
                        ShellText {
                            visible: root.batteries.length > 0
                            text: root.batteries.length === 1 ? root.batteries[0].model || qsTr("System battery")
                                : qsTr("%1 system batteries · combined charge").arg(root.batteries.length)
                            color: Theme.muted; font.pixelSize: Theme.smallFontSize
                            Layout.leftMargin: root.width >= 340 ? 42 : 0
                            Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                        MetricChip {
                            objectName: "batteryEstimate"
                            visible: !!root.summary && (root.summary.state === UPowerDeviceState.Charging
                                || (root.summary.state === UPowerDeviceState.Discharging && root.onBattery))
                            iconName: "alarm-clock"
                            label: root.summary?.state === UPowerDeviceState.Charging ? qsTr("Time to full") : qsTr("Time remaining")
                            value: Format.seconds(root.summary) > 0 ? Format.duration(Format.seconds(root.summary)) : "…"
                            detail: Format.estimate(root.summary)
                        }
                    }
                    ColumnLayout {
                        visible: root.batteries.length > 0
                        Layout.preferredWidth: root.width < 340 ? 148 : 184
                        Layout.minimumWidth: root.width < 340 ? 148 : 184
                        Layout.maximumWidth: root.width < 340 ? 148 : 184
                        Layout.fillWidth: false; Layout.alignment: Qt.AlignTop
                        spacing: 8
                        Repeater {
                            model: ScriptModel { values: root.batteries }
                            delegate: ColumnLayout {
                                id: pack
                                required property var modelData
                                readonly property var device: modelData
                                objectName: "batteryPack:" + device.nativePath
                                Layout.fillWidth: true; spacing: 4
                                RowLayout {
                                    visible: root.batteries.length > 1
                                    Layout.fillWidth: true; spacing: 6
                                    ShellText { text: pack.device.model || pack.device.nativePath; Layout.fillWidth: true; font.pixelSize: Theme.smallFontSize; elide: Text.ElideRight; textFormat: Text.PlainText }
                                    ShellText { text: Format.compact(pack.device.percentage * 100, "%"); color: Theme.muted; font.pixelSize: Theme.smallFontSize }
                                }
                                GridLayout {
                                    Layout.fillWidth: true; columns: 2; rowSpacing: 0; columnSpacing: 4
                                    PackMetric {
                                        objectName: "batteryHealth"
                                        iconName: "heart"; label: qsTr("Battery health")
                                        value: pack.device.healthSupported ? Format.compact(pack.device.healthPercentage, "%", 1) : "—"
                                        detail: pack.device.healthSupported && pack.device.healthPercentage < 80 ? qsTr("Battery wear reduces runtime even when power use is low.") : ""
                                    }
                                    PackMetric {
                                        iconName: "battery-full"; label: qsTr("Stored energy"); value: Format.compact(pack.device.energy, " Wh", 1)
                                        detail: qsTr("Full capacity: %1").arg(Format.value(pack.device.energyCapacity, " Wh", 1))
                                    }
                                    PackMetric {
                                        iconName: "zap"
                                        label: pack.device.state === UPowerDeviceState.Charging ? qsTr("Charging power")
                                            : pack.device.state === UPowerDeviceState.Discharging ? qsTr("Discharging power") : qsTr("Battery power")
                                        value: Format.compact(Math.abs(pack.device.changeRate), " W", 1)
                                        detail: qsTr("Power flowing through the battery; this excludes power supplied directly by the adapter.")
                                    }
                                }
                            }
                        }
                    }
                }
                ChargeGauge {
                    objectName: "batteryGauge"; Layout.fillWidth: true
                    visible: !!root.summary
                    percentage: root.percentage
                    controller: root.care; canAct: root.canAct
                    onLimitRequested: value => root.service.chargeLimit(root.care, value)
                }
                Note {
                    visible: !!root.summary
                    text: root.onBattery ? qsTr("Running on battery")
                        : root.summary?.state === UPowerDeviceState.Charging ? qsTr("Plugged in · charging")
                        : root.summary?.state === UPowerDeviceState.Discharging ? qsTr("Plugged in · battery discharging")
                        : root.care && root.care.limit < 100 && root.percentage >= root.care.limit - 1
                        ? qsTr("Plugged in · charge limit reached") : qsTr("Plugged in · %1").arg(Format.batteryState(root.summary?.state))
                }
            }
            Heading { objectName: "deviceBatteriesHeading"; text: qsTr("Device batteries"); Layout.topMargin: 8 }
            Note { visible: !root.peripherals.length; text: qsTr("No device batteries reported.") }
            Repeater {
                model: ScriptModel { values: root.peripherals }
                delegate: PowerCard {
                    id: peripheral
                    required property var modelData
                    readonly property var device: modelData
                    objectName: "deviceBattery:" + device.nativePath
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        Icon { name: "battery-medium"; color: Theme.muted; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                        ShellText { text: peripheral.device.model || UPowerDeviceType.toString(peripheral.device.type); Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
                        ShellText { text: Format.compact(peripheral.device.percentage * 100, "%"); color: Theme.muted; font.pixelSize: Theme.smallFontSize }
                        Icon { visible: peripheral.device.state === UPowerDeviceState.Charging; name: "battery-charging"; color: Theme.success; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                    }
                }
            }
            Repeater { model: root.service.state.hardwareErrors; delegate: Note { required property string modelData; text: modelData; color: Theme.danger } }
        }
        DrawerActionButton {
            objectName: "batteryChargeOnce"; Layout.fillWidth: true
            text: root.chargePending ? qsTr("Restore charge limit") : qsTr("Charge to 100% once"); iconName: "battery-charging"
            visible: root.chargePending || (!!root.summary && !!root.care && root.care.maximum >= 100 && root.care.limit < 100)
            enabled: root.canAct && root.session.ready && (root.chargePending || !root.onBattery)
            onClicked: root.session.send(root.chargePending ? {op: "restore-charge"}
                : {op: "charge-once", key: root.care.key, identity: root.care.identity, limit: root.care.limit})
        }
    }
}
