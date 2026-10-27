pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import Quickshell
import "../ui"
import "../ui/Models.js" as Models
import "displays"
import "displays/Layout.js" as DisplayLayout
import "../spaces/pictures"

DrawerPage {
    id: root
    property var wallpaperService: WallpaperService
    property var service: DisplayService
    property var displayTests: DisplayTestService
    property var comfortService: ComfortService
    property Popup openOptions: null
    escapeHandler: openOptions ? (() => openOptions.close()) : null
    readonly property var displays: service.state.displays
    readonly property bool canEdit: active && service.state.available && !service.busy && !service.closing
    readonly property var rotations: [qsTr("Normal"), qsTr("90° counterclockwise"), qsTr("180°"), qsTr("90° clockwise"), qsTr("Flipped"), qsTr("Flipped, 90° counterclockwise"), qsTr("Flipped, 180°"), qsTr("Flipped, 90° clockwise")]
    ListModel {
        id: displaysModel
        dynamicRoles: true
    }
    function syncModels(): void {
        Models.sync(displaysModel, displays, "name");
    }
    function startTest(kind: string, record): void {
        if (displayTests.start(kind, record))
            closeRequested();
    }
    function openEditor(): void {
        Apps.launch(["display-tools"]);
        root.closeRequested();
    }
    function outputLabel(name: string): string {
        if (/^(eDP|LVDS|DSI)-/.test(name))
            return qsTr("Built-in display");
        if (name.startsWith("DP-"))
            return qsTr("DisplayPort · %1").arg(name);
        if (name.startsWith("HDMI-"))
            return qsTr("HDMI · %1").arg(name);
        return name;
    }
    function rateLabel(mode: string): string {
        const rate = Number(mode.split("@")[1]?.replace("Hz", "") ?? 0);
        return rate.toLocaleString(Qt.locale(), "f", Number.isInteger(rate) ? 0 : 2) + " Hz";
    }
    Connections {
        target: root.service
        function onStateChanged(): void {
            root.syncModels();
        }
    }
    onActiveChanged: {
        if (!active && openOptions)
            openOptions.close();
        service.observe(root, active);
        comfortService.observe(root, active);
    }
    Component.onCompleted: {
        syncModels();
        service.observe(root, active);
        comfortService.observe(root, active);
    }
    Component.onDestruction: {
        service.observe(root, false);
        comfortService.observe(root, false);
    }
    headerActions: RowLayout {
        spacing: 4
        IconButton {
            id: randomWallpaperButton
            objectName: "displayRandomWallpaper"
            iconName: "image"
            text: qsTr("Random Wallhaven wallpaper")
            hint: qsTr("Apply a random SFW wallpaper to every display and the lock screen.")
            enabled: !root.wallpaperService.busy
            onClicked: root.wallpaperService.randomWallhaven()
            contentItem: Item {
                readonly property color tint: randomWallpaperButton.hovered || randomWallpaperButton.visualFocus ? Theme.accent : randomWallpaperButton.iconColor
                Icon {
                    objectName: "displayRandomWallpaperIcon"
                    anchors.fill: parent
                    name: "image"
                    color: parent.tint
                }
                Rectangle {
                    objectName: "displayWallpaperShuffleBadge"
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: -4
                    anchors.bottomMargin: -3
                    width: 14
                    height: 14
                    radius: 3
                    color: Theme.background
                    Icon {
                        anchors.fill: parent
                        anchors.margins: 1
                        name: "shuffle"
                        color: parent.parent.tint
                    }
                }
            }
        }
        IconButton {
            objectName: "displaySettings"
            iconName: "pencil"
            text: qsTr("Configure display arrangement")
            hint: qsTr("Open Display arrangement to position monitors and save this monitor set.")
            enabled: !root.service.busy
            onClicked: root.openEditor()
        }
    }
    component Note: ShellText {
        Layout.fillWidth: true
        color: Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    component Heading: ShellText {
        Layout.fillWidth: true
        font.weight: Font.DemiBold
        textFormat: Text.PlainText
    }
    component DisplayCard: Card {
        id: card
        required property var record
        readonly property bool editable: root.canEdit && record.enabled
        readonly property var brightness: root.service.brightnessFor(record.name)
        objectName: "displayCard:" + record.name
        Layout.fillWidth: true
        implicitHeight: content.implicitHeight + 24
        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Heading {
                    text: root.outputLabel(card.record.name)
                    elide: Text.ElideRight
                }
                Switch {
                    id: outputEnabled
                    objectName: "displayEnabled:" + card.record.name
                    checked: card.record.enabled
                    enabled: root.canEdit && (!checked || root.displays.filter(row => row.enabled && row.mirror === "none").length > 1 || card.record.mirror !== "none")
                    implicitWidth: 38
                    Layout.preferredWidth: 38
                    implicitHeight: Theme.controlHeight
                    padding: 0
                    hoverEnabled: true
                    Accessible.name: qsTr("Enable %1").arg(card.record.label)
                    onToggled: {
                        const requested = checked;
                        checked = Qt.binding(() => card.record.enabled);
                        root.service.change(card.record, {
                            enabled: requested
                        });
                    }
                    indicator: Rectangle {
                        x: outputEnabled.width - width
                        y: (outputEnabled.height - height) / 2
                        implicitWidth: 38
                        implicitHeight: 22
                        radius: height / 2
                        color: outputEnabled.checked ? Theme.accent : Theme.border
                        opacity: outputEnabled.enabled ? 1 : 0.45
                        Rectangle {
                            x: outputEnabled.checked ? parent.width - width - 3 : 3
                            y: 3
                            width: 16
                            height: 16
                            radius: 8
                            color: outputEnabled.checked ? Theme.accentText : Theme.text
                        }
                    }
                    contentItem: Item {}
                    background: ButtonBackground {
                        idleColor: "transparent"
                        highlighted: outputEnabled.visualFocus
                        pressed: outputEnabled.down
                    }
                    PassiveToolTip {
                        target: outputEnabled
                        text: card.record.name + (outputEnabled.enabled ? "" : "\n" + qsTr("At least one independent display must stay enabled."))
                    }
                }
            }
            ShellText {
                text: card.record.label
                Layout.fillWidth: true
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }
            Note {
                objectName: "displaySummary:" + card.record.name
                text: !card.record.enabled ? qsTr("Display disabled") : [card.record.mode.split("@")[0].replace("x", " × "), root.rateLabel(card.record.mode), Math.round(card.record.scale * 100) + "%", card.record.transform === 0 ? "" : root.rotations[card.record.transform], card.record.mirror === "none" ? "" : qsTr("Mirroring %1").arg(card.record.mirror)].filter(Boolean).join(" · ")
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                BrightnessControl {
                    objectName: "displayBrightness:" + card.record.name
                    Layout.fillWidth: true
                    record: card.brightness
                    canAdjust: card.editable
                    label: qsTr("Brightness for %1").arg(card.record.label)
                    onEdited: value => root.service.setBrightness(card.record.name, value)
                }
                IconButton {
                    id: optionsButton
                    readonly property alias menu: options
                    objectName: "displayOptions:" + card.record.name
                    iconName: "settings"
                    text: qsTr("Options for %1").arg(card.record.label)
                    enabled: options.visible || card.editable
                    onClicked: {
                        if (options.visible)
                            options.close();
                        else
                            options.open();
                    }
                    InfoPopover {
                        id: options
                        objectName: "displayPopup:" + card.record.name
                        button: optionsButton
                        active: root.active
                        width: Math.min(360, (Overlay.overlay?.width ?? root.width) - 16)
                        onAboutToShow: root.openOptions = options
                        onClosed: {
                            if (root.openOptions === options)
                                root.openOptions = null;
                        }
                        Component.onDestruction: {
                            if (root.openOptions === options)
                                root.openOptions = null;
                        }
                        Heading {
                            text: card.record.label
                        }
                        Note {
                            text: qsTr("Resolution")
                        }
                        ShellChoice {
                            objectName: "displayResolution:" + card.record.name
                            Layout.fillWidth: true
                            enabled: card.editable
                            model: [...new Set(card.record.modes.map(mode => mode.split("@")[0]))]
                            currentIndex: model.indexOf(card.record.mode.split("@")[0])
                            Accessible.name: qsTr("Resolution for %1").arg(card.record.label)
                            onActivated: root.service.change(card.record, {
                                mode: DisplayLayout.modeForResolution(card.record, model[index])
                            })
                        }
                        Note {
                            text: qsTr("Refresh rate")
                        }
                        ShellChoice {
                            objectName: "displayRefresh:" + card.record.name
                            Layout.fillWidth: true
                            enabled: card.editable
                            property var modes: card.record.modes.filter(mode => mode.split("@")[0] === card.record.mode.split("@")[0])
                            model: modes.map(mode => root.rateLabel(mode))
                            currentIndex: modes.indexOf(card.record.mode)
                            Accessible.name: qsTr("Refresh rate for %1").arg(card.record.label)
                            onActivated: root.service.change(card.record, {
                                mode: modes[index]
                            })
                        }
                        Note {
                            text: qsTr("Scale")
                        }
                        ShellChoice {
                            objectName: "displayScale:" + card.record.name
                            Layout.fillWidth: true
                            enabled: card.editable
                            property var values: DisplayLayout.scales(card.record)
                            model: values.map(value => Math.round(value * 100) + "%")
                            currentIndex: values.indexOf(card.record.scale)
                            Accessible.name: qsTr("Scale for %1").arg(card.record.label)
                            onActivated: root.service.change(card.record, {
                                scale: values[index]
                            })
                        }
                        Note {
                            text: qsTr("Orientation")
                        }
                        ShellChoice {
                            objectName: "displayRotation:" + card.record.name
                            Layout.fillWidth: true
                            enabled: card.editable
                            model: root.rotations
                            currentIndex: card.record.transform
                            Accessible.name: qsTr("Orientation for %1").arg(card.record.label)
                            onActivated: root.service.change(card.record, {
                                transform: index
                            })
                        }
                        Note {
                            text: qsTr("Mirroring")
                        }
                        ShellChoice {
                            objectName: "displayMirror:" + card.record.name
                            Layout.fillWidth: true
                            enabled: card.editable
                            property var targets: [
                                {
                                    name: "none",
                                    label: qsTr("Independent display")
                                }
                            ].concat(root.displays.filter(row => row.enabled && row.name !== card.record.name && row.mirror === "none"))
                            model: targets.map(row => row.name === "none" ? row.label : qsTr("Mirror %1").arg(row.label))
                            currentIndex: targets.findIndex(row => row.name === card.record.mirror)
                            Accessible.name: qsTr("Mirroring for %1").arg(card.record.label)
                            onActivated: root.service.change(card.record, {
                                mirror: targets[index].name
                            })
                        }
                        ShellButton {
                            objectName: "displayRecommended:" + card.record.name
                            text: qsTr("Use recommended resolution")
                            Layout.fillWidth: true
                            enabled: card.editable
                            onClicked: root.service.change(card.record, {
                                mode: "preferred"
                            })
                        }
                        ShellButton {
                            objectName: "displayAwake:" + card.record.name
                            text: qsTr("Keep awake")
                            Layout.fillWidth: true
                            enabled: card.editable && !root.comfortService.busy
                            checkable: true
                            checked: root.comfortService.awakeFor(card.record.name)
                            onClicked: root.comfortService.setAwake(card.record, !root.comfortService.awakeFor(card.record.name))
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            ShellButton {
                                objectName: "displayPatterns:" + card.record.name
                                text: qsTr("Test patterns")
                                Layout.fillWidth: true
                                enabled: card.editable
                                onClicked: root.startTest("patterns", card.record)
                            }
                            ShellButton {
                                objectName: "displayMotion:" + card.record.name
                                text: qsTr("Motion test")
                                Layout.fillWidth: true
                                enabled: card.editable
                                onClicked: root.startTest("motion", card.record)
                            }
                        }
                    }
                }
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        RowLayout {
            visible: root.service.error !== ""
            Layout.fillWidth: true
            Note {
                objectName: "displayError"
                text: root.service.error
                color: Theme.danger
            }
            IconButton {
                iconName: "refresh-cw"
                text: qsTr("Refresh displays")
                onClicked: root.service.refresh()
            }
            IconButton {
                iconName: "x"
                text: qsTr("Dismiss display error")
                onClicked: root.service.error = ""
            }
        }
        RowLayout {
            visible: !root.service.loaded
            BusySpinner {
                implicitWidth: 16
                implicitHeight: 16
            }
            Note {
                text: qsTr("Loading connected displays…")
            }
        }
        Note {
            visible: root.displayTests.error !== ""
            text: root.displayTests.error
            color: Theme.danger
        }
        DrawerColumn {
            objectName: "displayScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Heading {
                text: qsTr("Displays")
            }
            Note {
                visible: root.service.loaded && !displaysModel.count
                text: qsTr("No connected displays available.")
            }
            Repeater {
                model: displaysModel
                delegate: DisplayCard {}
            }
            ComfortControls {
                service: root.comfortService
                active: root.active
            }
            Note {
                visible: root.wallpaperService.busy
                text: qsTr("Changing wallpaper…")
            }
            Note {
                visible: !!root.wallpaperService.error
                text: root.wallpaperService.error
                color: Theme.danger
            }
            Note {
                visible: !!root.wallpaperService.message
                text: root.wallpaperService.message
            }
        }
        Button {
            id: identifyButton
            objectName: "displayIdentifyButton"
            Layout.fillWidth: true
            implicitHeight: 48
            padding: 10
            hoverEnabled: true
            enabled: root.active && (root.displayTests.mode === "identify" || (root.canEdit && root.displays.some(record => record.enabled)))
            text: root.displayTests.mode === "identify" ? qsTr("Hide display labels") : qsTr("Identify displays")
            onClicked: {
                if (root.displayTests.mode === "identify")
                    root.displayTests.stop();
                else
                    root.displayTests.identify(root.displays);
            }
            contentItem: Item {
                RowLayout {
                    anchors.centerIn: parent
                    width: Math.min(parent.width, implicitWidth)
                    spacing: 12
                    Icon {
                        name: "monitor"
                        Layout.preferredWidth: 22
                        Layout.preferredHeight: 22
                    }
                    ShellText {
                        text: identifyButton.text
                        Layout.fillWidth: true
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignHCenter
                        font.weight: Font.Medium
                    }
                }
            }
            background: ButtonBackground {
                idleColor: Theme.surface
                highlighted: identifyButton.hovered || identifyButton.visualFocus
                pressed: identifyButton.down
            }
            PassiveToolTip {
                target: identifyButton
                text: qsTr("Show each enabled display’s name and connector for five seconds.")
            }
        }
    }
}
