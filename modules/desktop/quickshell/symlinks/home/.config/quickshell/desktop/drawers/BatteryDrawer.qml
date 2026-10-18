pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../ui"
import "network"
import "network/Models.js" as Models
import "power"
import "power/Format.js" as Format

DrawerPage {
    id: root
    property var service: PowerService
    property var session: PowerSession
    readonly property var battery: service.state.battery
    readonly property var summary: battery.summary
    readonly property var care: service.state.hardware.find(row => row.limit !== null) ?? null
    readonly property bool chargePending: !!session.state.once
    readonly property bool canAct: active && service.loaded && !service.changing && !service.closing
    ListModel { id: packsModel; dynamicRoles: true }
    ListModel { id: devicesModel; dynamicRoles: true }
    function sync(): void {
        Models.sync(packsModel, battery.batteries, "key", false);
        Models.sync(devicesModel, battery.peripherals ?? [], "key", false);
    }
    Connections { target: root.service; function onStateChanged(): void { root.sync(); } }
    Component.onCompleted: { sync(); service.observe(root, active, false); }
    Component.onDestruction: service.observe(root, false, false)
    onActiveChanged: service.observe(root, active, false)
    headerActions: NetworkIconButton {
        objectName: "batteryRefresh"; iconName: "refresh-cw"; text: qsTr("Refresh battery")
        enabled: !root.service.busy && !root.service.closing
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
            Note { visible: !root.service.loaded; text: qsTr("Reading batteries…") }
            Note { visible: root.service.statusError !== ""; text: root.service.statusError; color: Theme.danger }
            Note { objectName: "batteryActionError"; visible: root.service.actionError !== ""; text: root.service.actionError; color: Theme.danger }
            Note { visible: root.session.error !== ""; text: root.session.error; color: Theme.danger }
            Note { visible: root.battery.error !== ""; text: root.battery.error; color: Theme.danger }
            Heading { objectName: "batteriesHeading"; text: qsTr("Batteries") }
            PowerCard {
                objectName: "batteryCard"
                visible: root.service.loaded
                RowLayout {
                    Layout.fillWidth: true; spacing: 12
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.preferredWidth: 1
                        Layout.minimumWidth: 0; Layout.alignment: Qt.AlignTop
                        spacing: 0
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            NetworkIconButton {
                                id: powerSource
                                objectName: "batteryPowerSource"
                                visible: root.width >= 340
                                iconName: root.summary?.state === 1 ? "battery-charging" : "battery-medium"
                                iconColor: root.battery.onBattery === false ? Theme.success : Theme.text
                                text: root.summary ? Format.batteryState(root.summary.state) : qsTr("Power source")
                                hint: text + "\n" + (root.battery.onBattery === null ? qsTr("Power source unavailable") : root.battery.onBattery ? qsTr("Running on battery") : qsTr("External power connected"))
                                Accessible.role: Accessible.StaticText; activeFocusOnTab: false
                                contentItem: Icon { name: powerSource.iconName; color: powerSource.iconColor }
                                background: Item {}
                            }
                            ShellText {
                                objectName: "batteryPercentage"
                                text: root.summary ? Format.compact(root.summary.percentage, "%") : root.battery.available ? qsTr("No system battery") : qsTr("Unavailable")
                                font.pixelSize: root.summary ? root.width < 340 ? 28 : 32 : Theme.titleFontSize
                                Layout.fillWidth: true; wrapMode: Text.Wrap
                            }
                        }
                        ShellText {
                            visible: !!root.summary && root.battery.batteries.length > 0
                            text: root.battery.batteries.length === 1 ? root.battery.batteries[0].label
                                : qsTr("%1 system batteries · combined charge").arg(root.battery.batteries.length)
                            color: Theme.muted; font.pixelSize: Theme.smallFontSize
                            Layout.leftMargin: root.width >= 340 ? 42 : 0
                            Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText
                        }
                        MetricChip {
                            objectName: "batteryEstimate"
                            visible: !!root.summary && (root.summary.state === 1
                                || (root.summary.state === 2 && root.battery.onBattery !== false))
                            iconName: "alarm-clock"; label: root.summary?.state === 1 ? qsTr("Time to full") : qsTr("Time remaining")
                            value: root.summary?.seconds > 0 ? Format.duration(root.summary.seconds) : "…"
                            detail: Format.estimate(root.summary)
                        }
                    }
                    ColumnLayout {
                        visible: root.battery.batteries.length > 0
                        Layout.preferredWidth: root.width < 340 ? 148 : 184
                        Layout.minimumWidth: root.width < 340 ? 148 : 184
                        Layout.maximumWidth: root.width < 340 ? 148 : 184
                        Layout.fillWidth: false; Layout.alignment: Qt.AlignTop
                        spacing: 8
                        Repeater {
                            model: packsModel
                            delegate: ColumnLayout {
                                id: pack
                                required property var record
                                objectName: "batteryPack:" + record.key
                                Layout.fillWidth: true; spacing: 4
                                RowLayout {
                                    visible: root.battery.batteries.length > 1
                                    Layout.fillWidth: true; spacing: 6
                                    ShellText { text: pack.record.label; Layout.fillWidth: true; font.pixelSize: Theme.smallFontSize; elide: Text.ElideRight; textFormat: Text.PlainText }
                                    ShellText { text: Format.compact(pack.record.percentage, "%"); color: Theme.muted; font.pixelSize: Theme.smallFontSize }
                                }
                                GridLayout {
                                    Layout.fillWidth: true; columns: 2; rowSpacing: 0; columnSpacing: 4
                                    PackMetric {
                                        iconName: "heart"; label: qsTr("Battery health"); value: Format.compact(pack.record.health, "%", 1)
                                        detail: qsTr("Full capacity: %1\nDesign capacity: %2").arg(Format.value(pack.record.full, " Wh", 1)).arg(Format.value(pack.record.design, " Wh", 1))
                                            + (pack.record.health !== null && pack.record.health < 80 ? "\n" + qsTr("Battery wear reduces runtime even when power use is low.") : "")
                                    }
                                    PackMetric { iconName: "repeat"; label: qsTr("Charge cycles"); value: Format.compact(pack.record.cycles) }
                                    PackMetric {
                                        iconName: "battery-full"; label: qsTr("Stored energy"); value: Format.compact(pack.record.energy, " Wh", 1)
                                        detail: qsTr("Full capacity: %1").arg(Format.value(pack.record.full, " Wh", 1))
                                    }
                                    PackMetric {
                                        iconName: "zap"; label: pack.record.state === 1 ? qsTr("Charging power") : pack.record.state === 2 ? qsTr("Discharging power") : qsTr("Battery power")
                                        value: Format.compact(pack.record.rate, " W", 1)
                                        detail: qsTr("Power flowing through the battery; this excludes power supplied directly by the adapter.")
                                    }
                                }
                            }
                        }
                    }
                }
                ChargeGauge {
                    objectName: "batteryGauge"; Layout.fillWidth: true
                    visible: !!root.summary && root.summary.percentage !== null
                    percentage: root.summary?.percentage ?? 0
                    controller: root.care; canAct: root.canAct
                    onLimitRequested: value => root.service.chargeLimit(root.care, value)
                }
                Note {
                    visible: !!root.summary
                    text: root.battery.onBattery === true ? qsTr("Running on battery")
                        : root.battery.onBattery === false ? root.summary?.state === 1 ? qsTr("Plugged in · charging")
                        : root.summary?.state === 2 ? qsTr("Plugged in · battery discharging")
                        : root.care && root.care.limit < 100 && root.summary?.percentage >= root.care.limit - 1
                        ? qsTr("Plugged in · charge limit reached") : qsTr("Plugged in · %1").arg(Format.batteryState(root.summary?.state))
                        : qsTr("Power source unavailable")
                }
            }
            Heading { objectName: "deviceBatteriesHeading"; text: qsTr("Device batteries"); Layout.topMargin: 8 }
            Note { visible: root.service.loaded && devicesModel.count === 0; text: qsTr("No device batteries reported.") }
            Repeater {
                model: devicesModel
                delegate: PowerCard {
                    id: device
                    required property var record
                    objectName: "deviceBattery:" + record.key
                    RowLayout {
                        Layout.fillWidth: true; spacing: 8
                        Icon { name: "battery-medium"; color: Theme.muted; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                        ShellText { text: device.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
                        ShellText {
                            text: device.record.level !== 1 ? ({3: qsTr("Low"), 4: qsTr("Critical"), 6: qsTr("Normal"), 7: qsTr("High"), 8: qsTr("Full")})[device.record.level] || qsTr("Unknown") : Format.compact(device.record.percentage, "%")
                            color: Theme.muted; font.pixelSize: Theme.smallFontSize
                        }
                        Icon { visible: device.record.state === 1; name: "battery-charging"; color: Theme.success; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                    }
                }
            }
            Repeater { model: root.service.state.hardwareErrors; delegate: Note { required property string modelData; text: modelData; color: Theme.danger } }
        }
        ShellButton {
            objectName: "batteryChargeOnce"; Layout.fillWidth: true
            text: root.chargePending ? qsTr("Restore charge limit") : qsTr("Charge to 100% once"); iconName: "battery-charging"
            visible: root.chargePending || (!!root.summary && !!root.care && root.care.maximum >= 100 && root.care.limit < 100)
            enabled: root.canAct && root.session.ready && !root.session.busy && (root.chargePending || root.battery.onBattery === false)
            onClicked: root.session.send(root.chargePending ? {op: "restore-charge"}
                : {op: "charge-once", key: root.care.key, identity: root.care.identity, limit: root.care.limit})
        }
    }
}
