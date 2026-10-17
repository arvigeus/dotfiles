pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../ui"
import "audio"
import "weather"
import "weather/Conditions.js" as Conditions

DrawerPage {
    id: root
    objectName: "clockWeatherDrawer"
    property var service: localService
    property var locationSettings: LocationSettings
    readonly property var snapshot: service.state
    readonly property var weather: snapshot.weather
    readonly property var current: weather?.current ?? null
    readonly property int hourCount: width < 340 ? 4 : 6
    initialFocus: locations
    escapeHandler: locations.popup.visible ? (() => locations.popup.close())
        : reminders.popupOpen ? (() => reminders.closePopup()) : null
    WeatherService { id: localService; active: root.active && root.service === localService }
    onActiveChanged: if (!active) locations.popup.close()

    Connections {
        target: root.locationSettings
        function onChanged(): void { root.service.refresh(); }
    }
    headerActions: AudioIconButton {
        objectName: "weatherRefresh"; iconName: "refresh-cw"; text: qsTr("Refresh weather")
        enabled: root.active && !!root.snapshot.location && !root.service.loading
        onClicked: root.service.fetchWeather(true)
    }
    component Note: ShellText { color: Theme.muted; font.pixelSize: Theme.smallFontSize }
    component Heading: ShellText { font.weight: Font.DemiBold }

    DrawerColumn {
        objectName: "weatherContent"
        anchors.fill: parent
        Note {
            visible: !root.snapshot.locations.length
            Layout.fillWidth: true; wrapMode: Text.Wrap
            text: qsTr("Add places to ~/.config/quickshell/desktop/weather.json.")
        }
        Surface {
            Layout.fillWidth: true; visible: !!root.snapshot.location
            implicitHeight: overview.implicitHeight + 32
            color: Theme.surface; border.width: 0; radius: Theme.controlRadius
            ColumnLayout {
                id: overview
                anchors.fill: parent; anchors.margins: 16; spacing: 10
                RowLayout {
                    id: clockRow
                    Layout.fillWidth: true; spacing: 8
                    ShellText { id: clockText; objectName: "locationTime"; text: root.snapshot.clock; font.pixelSize: root.width < 340 ? 36 : 46; font.weight: Font.Light }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 2
                        ShellText {
                            font.pixelSize: root.width < 340 ? Theme.smallFontSize : Theme.fontSize
                            text: root.snapshot.date ? Qt.formatDate(new Date(root.snapshot.date + "T12:00:00"), "ddd, d MMM") : ""
                            Layout.fillWidth: true; elide: Text.ElideRight
                        }
                        Note { text: [root.snapshot.location?.name, root.snapshot.zone].filter(Boolean).join(" · "); Layout.fillWidth: true; elide: Text.ElideRight }
                    }
                    AudioIconButton {
                        objectName: "weatherSetCurrent"; iconName: "map-pin"
                        readonly property bool isCurrent: !!root.snapshot.location && root.snapshot.location.id === root.snapshot.currentLocation
                        text: isCurrent ? qsTr("Apply current location and timezone") : qsTr("Use %1 as current location and timezone").arg(root.snapshot.location?.name ?? "")
                        iconColor: isCurrent ? Theme.accent : Theme.muted
                        background: Item {}
                        enabled: root.active && !!root.snapshot.location && !root.locationSettings.busy
                        onClicked: root.locationSettings.setCurrent(root.snapshot.location.id)
                    }
                    ComboBox {
                        id: locations
                        objectName: "weatherLocation"
                        implicitWidth: 28; implicitHeight: 34; Layout.preferredWidth: 28
                        model: root.snapshot.locations; textRole: "name"; valueRole: "id"
                        currentIndex: root.snapshot.locations.findIndex(row => row.id === root.service.selectedId)
                        enabled: count > 0
                        Accessible.name: qsTr("Choose location")
                        onActivated: root.service.select(currentValue)
                        padding: 4; hoverEnabled: true
                        contentItem: Item {}
                        indicator: Icon {
                            anchors.centerIn: parent; name: "chevron-down"
                            color: locations.hovered || locations.visualFocus ? Theme.accent : Theme.muted
                        }
                        background: Item {}
                        delegate: ItemDelegate {
                            id: option
                            required property var modelData
                            required property int index
                            width: locations.popup.availableWidth; implicitHeight: 54; padding: 10
                            highlighted: locations.highlightedIndex === index
                            contentItem: RowLayout {
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    ShellText { text: option.modelData.name; Layout.fillWidth: true; elide: Text.ElideRight }
                                    Note { text: option.modelData.detail || ""; visible: text !== ""; Layout.fillWidth: true; elide: Text.ElideRight }
                                }
                                ShellText {
                                    objectName: "weatherLocationTime:" + option.modelData.id
                                    text: option.modelData.clock ?? ""; font.family: Theme.monospaceFamily
                                    Accessible.name: text + " " + (option.modelData.zone ?? "")
                                }
                                Icon { name: "check"; opacity: option.modelData.id === root.service.selectedId ? 1 : 0; color: Theme.accent }
                            }
                            background: ButtonBackground { highlighted: option.highlighted || option.hovered; pressed: option.down }
                        }
                        popup: Popup {
                            onAboutToShow: reminders.closePopup()
                            x: locations.width - width; y: locations.height + 4
                            width: Math.min(360, root.width); padding: 4; margins: 8
                            implicitHeight: Math.min(contentItem.implicitHeight + 8, 340)
                            background: Surface { color: Theme.background; radius: Theme.controlRadius }
                            contentItem: ScrollListView {
                                clip: true; implicitHeight: contentHeight
                                model: locations.popup.visible ? locations.delegateModel : null
                                currentIndex: locations.highlightedIndex
                                ScrollBar.vertical: ScrollBar {}
                            }
                        }
                    }

                }
                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
                GridLayout {
                    visible: !!root.current; Layout.fillWidth: true
                    columns: root.width < 340 ? 1 : 2; columnSpacing: 12; rowSpacing: 10
                    RowLayout {
                        Layout.fillWidth: true; spacing: 12
                        Icon { name: Conditions.icon(root.current?.code, root.current?.isDay); implicitWidth: 40; implicitHeight: 40; color: Theme.warning }
                        ShellText { objectName: "weatherTemperature"; text: Conditions.temperature(root.current?.temperature); font.pixelSize: 36 }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 2
                            ShellText { text: Conditions.description(root.current?.code); Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Note { text: qsTr("Feels %1 · °C").arg(Conditions.temperature(root.current?.feelsLike)); Layout.fillWidth: true; wrapMode: Text.Wrap }
                        }
                    }
                    GridLayout {
                        Layout.alignment: Qt.AlignRight; Layout.fillWidth: root.width < 340
                        columns: root.width < 340 ? 4 : 2; columnSpacing: 6; rowSpacing: 6
                        Icon { name: "wind"; color: Theme.muted; implicitWidth: 16; implicitHeight: 16 }
                        Note { text: root.current?.wind == null ? "—" : Math.round(root.current.wind) + " km/h"; Layout.fillWidth: root.width < 340 }
                        Icon { name: "droplet"; color: Theme.muted; implicitWidth: 16; implicitHeight: 16 }
                        Note { text: qsTr("%1 humidity").arg(Conditions.percent(root.current?.humidity)) }
                    }
                }
                Note {
                    objectName: "weatherOutlook"
                    visible: !!root.weather?.outlook; text: root.weather?.outlook ?? ""
                    Layout.fillWidth: true; wrapMode: Text.Wrap
                }
                Note { visible: !root.current; text: root.service.loading ? qsTr("Loading weather…") : qsTr("Weather unavailable") }
            }
        }
        ShellText {
            objectName: "weatherError"
            visible: text !== ""; text: root.service.error || root.locationSettings.error
            color: Theme.warning; font.pixelSize: Theme.smallFontSize; wrapMode: Text.Wrap; Layout.fillWidth: true
        }
        Heading { visible: !!root.weather; text: qsTr("Next hours") }
        RowLayout {
            visible: !!root.weather; Layout.fillWidth: true; spacing: 4
            Repeater {
                model: (root.weather?.hourly ?? []).slice(0, root.hourCount)
                delegate: Button {
                    id: hour
                    required property var modelData
                    Layout.fillWidth: true; Layout.preferredWidth: 1; implicitHeight: 112
                    hoverEnabled: true
                    Accessible.name: hour.modelData.label + ", " + Conditions.description(hour.modelData.code) + ", " + Conditions.temperature(hour.modelData.temperature) + ", " + qsTr("%1 chance of rain").arg(Conditions.percent(hour.modelData.rain))
                    background: Surface { color: Theme.surface; border.width: 0; radius: Theme.controlRadius }
                    contentItem: ColumnLayout {
                        spacing: 7
                        Note { text: hour.modelData.label; Layout.alignment: Qt.AlignHCenter }
                        Icon { name: Conditions.icon(hour.modelData.code, hour.modelData.isDay); Layout.alignment: Qt.AlignHCenter }
                        ShellText { text: Conditions.temperature(hour.modelData.temperature); Layout.alignment: Qt.AlignHCenter; font.weight: Font.DemiBold }
                        Note { text: Conditions.percent(hour.modelData.rain); color: Theme.warning; Layout.alignment: Qt.AlignHCenter }
                    }
                    PassiveToolTip { target: hour; text: Conditions.description(hour.modelData.code) + " · " + qsTr("%1 chance of rain").arg(Conditions.percent(hour.modelData.rain)) }
                }
            }
        }
        Heading { visible: !!root.weather; text: qsTr("Forecast") }
        Surface {
            visible: !!root.weather; Layout.fillWidth: true
            implicitHeight: daily.implicitHeight + 16
            color: Theme.surface; border.width: 0; radius: Theme.controlRadius
            ColumnLayout {
                id: daily
                anchors.fill: parent; anchors.margins: 8; spacing: 0
                Repeater {
                    model: root.weather?.daily ?? []
                    delegate: Button {
                        id: day
                        required property var modelData
                        objectName: "weatherDay:" + modelData.date
                        Layout.fillWidth: true; Layout.minimumHeight: 32; padding: 0; hoverEnabled: true
                        text: modelData.outlook || Conditions.description(modelData.code)
                        Accessible.name: Qt.formatDate(new Date(modelData.date + "T12:00:00"), "dddd, d MMM") + ", " + text
                        background: Item {}
                        contentItem: RowLayout {
                            spacing: 8
                            ShellText {
                                Layout.fillWidth: true
                                text: day.modelData.today ? qsTr("Today") : Qt.formatDate(new Date(day.modelData.date + "T12:00:00"), "ddd")
                            }
                            Icon { name: Conditions.icon(day.modelData.code, true) }
                            Note { text: Conditions.percent(day.modelData.rain); Layout.preferredWidth: 40; horizontalAlignment: Text.AlignRight; color: Theme.warning }
                            ShellText { text: Conditions.temperature(day.modelData.high); Layout.preferredWidth: 36; horizontalAlignment: Text.AlignRight }
                            Note { text: Conditions.temperature(day.modelData.low); Layout.preferredWidth: 36; horizontalAlignment: Text.AlignRight }
                        }
                        PassiveToolTip { target: day }
                    }
                }
            }
        }
        RowLayout {
            visible: !!root.snapshot.location; Layout.fillWidth: true
            Note {
                objectName: "weatherUpdated"; Layout.fillWidth: true; wrapMode: Text.Wrap
                text: root.snapshot.updated ? (root.snapshot.stale ? qsTr("Outdated · %1").arg(root.snapshot.updated) : qsTr("Updated %1").arg(root.snapshot.updated)) : ""
                color: root.snapshot.stale ? Theme.warning : Theme.muted
            }
            Note {
                text: "Open-Meteo ↗"
                TapHandler { onTapped: Qt.openUrlExternally("https://open-meteo.com/") }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }
        }
        ReminderControls {
            id: reminders
            objectName: "weatherReminders"
            Layout.fillWidth: true; active: root.active
            onPopupOpened: locations.popup.close()
        }
    }
}
