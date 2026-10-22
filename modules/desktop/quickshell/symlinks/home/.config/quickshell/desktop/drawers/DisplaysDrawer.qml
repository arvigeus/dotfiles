pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQml.Models
import Quickshell
import "../ui"
import "../ui/Models.js" as Models
import "displays"

DrawerPage {
    id: root
    property var service: DisplayService
    property var displayTests: DisplayTestService
    property var comfortService: ComfortService
    property Popup openOptions: null
    escapeHandler: openOptions ? (() => openOptions.close()) : null
    readonly property var displays: service.state.displays
    readonly property bool canEdit: active && service.state.available && !service.busy && !service.closing
    readonly property var rotations: [qsTr("Normal"), qsTr("90° counterclockwise"), qsTr("180°"), qsTr("90° clockwise"), qsTr("Flipped"), qsTr("Flipped, 90° counterclockwise"), qsTr("Flipped, 180°"), qsTr("Flipped, 90° clockwise")]
    ListModel { id: displaysModel; dynamicRoles: true }
    function syncModels(): void { Models.sync(displaysModel, displays, "name"); }
    function startTest(kind: string, record): void {
        if (displayTests.start(kind, record)) closeRequested();
    }
    function openEditor(): void { Apps.launch(["wdisplays"]); root.closeRequested(); }
    function outputLabel(name: string): string {
        if (/^(eDP|LVDS|DSI)-/.test(name)) return qsTr("Built-in display");
        if (name.startsWith("DP-")) return qsTr("DisplayPort · %1").arg(name);
        if (name.startsWith("HDMI-")) return qsTr("HDMI · %1").arg(name);
        return name;
    }
    function rateLabel(mode: string): string {
        const rate = Number(mode.split("@")[1]?.replace("Hz", "") ?? 0);
        return rate.toLocaleString(Qt.locale(), "f", Number.isInteger(rate) ? 0 : 2) + " Hz";
    }
    function optionsFor(record): var {
        const heading = text => ({kind: "heading", key: "heading:" + text, text});
        const separator = key => ({kind: "separator", key: "separator:" + key});
        const option = (key, text, marked, values) => ({kind: "option", key, text, marked, values});
        return [{kind: "awake", key: "awake", text: qsTr("Keep awake"), marked: comfortService.awakeFor(record.name)},
                {kind: "action", key: "recommended", text: qsTr("Use recommended resolution"), action: "recommended"},
                separator("Refresh rate"), heading(qsTr("Refresh rate"))]
            .concat(record.modes.filter(mode => mode.split("@")[0] === record.mode.split("@")[0]).map(mode =>
                option("rate:" + mode, rateLabel(mode), record.mode === mode, {mode})))
            .concat([separator("Mirroring"), heading(qsTr("Mirroring")), option("extend", qsTr("Independent display"), record.mirror === "none", {mirror: "none"})])
            .concat(displays.filter(row => row.enabled && row.name !== record.name && row.mirror === "none").map(row =>
                option("mirror:" + row.name, qsTr("Mirror %1").arg(row.label), record.mirror === row.name, {mirror: row.name})))
            .concat([separator("Test display"), heading(qsTr("Test display")),
                {kind: "action", key: "test:patterns", text: qsTr("Test patterns"), action: "patterns"},
                {kind: "action", key: "test:motion", text: qsTr("Motion test"), action: "motion"}]);
    }
    Connections { target: root.service; function onStateChanged(): void { root.syncModels(); } }
    onActiveChanged: { if (!active && openOptions) openOptions.close(); service.observe(root, active); comfortService.observe(root, active); }
    Component.onCompleted: { syncModels(); service.observe(root, active); comfortService.observe(root, active); }
    Component.onDestruction: { service.observe(root, false); comfortService.observe(root, false); }
    headerActions: RowLayout {
        spacing: 4
        IconButton {
            objectName: "displaySave"; iconName: "hard-drive-download"; text: qsTr("Save current layout")
            hint: qsTr("Keep the current arrangement, including wdisplays changes, for these displays.")
            enabled: root.canEdit
            onClicked: root.service.save()
        }
        IconButton {
            objectName: "displaySettings"; iconName: "pencil"; text: qsTr("Arrange displays in wdisplays")
            enabled: !root.service.busy
            onClicked: root.openEditor()
        }
    }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    component Heading: ShellText { Layout.fillWidth: true; font.weight: Font.DemiBold; textFormat: Text.PlainText }
    component DisplayCard: Surface {
        id: card
        required property var record
        readonly property bool editable: root.canEdit && record.enabled
        readonly property var brightness: root.service.brightnessFor(record.name)
        objectName: "displayCard:" + record.name
        Layout.fillWidth: true; implicitHeight: content.implicitHeight + 24
        color: Theme.surface; border.width: 0; radius: Theme.controlRadius
        ColumnLayout {
            id: content
            anchors.fill: parent; anchors.margins: 12; spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Heading { text: root.outputLabel(card.record.name); elide: Text.ElideRight }
                Switch {
                    id: outputEnabled
                    objectName: "displayEnabled:" + card.record.name
                    checked: card.record.enabled
                    enabled: root.canEdit && (!checked || root.displays.filter(row => row.enabled && row.mirror === "none").length > 1 || card.record.mirror !== "none")
                    implicitWidth: 38; Layout.preferredWidth: 38
                    implicitHeight: Theme.controlHeight; padding: 0; hoverEnabled: true
                    Accessible.name: qsTr("Enable %1").arg(card.record.label)
                    onToggled: {
                        const requested = checked;
                        checked = Qt.binding(() => card.record.enabled);
                        root.service.change(card.record, {enabled: requested});
                    }
                    indicator: Rectangle {
                        x: outputEnabled.width - width; y: (outputEnabled.height - height) / 2
                        implicitWidth: 38; implicitHeight: 22; radius: height / 2
                        color: outputEnabled.checked ? Theme.accent : Theme.border; opacity: outputEnabled.enabled ? 1 : 0.45
                        Rectangle {
                            x: outputEnabled.checked ? parent.width - width - 3 : 3
                            y: 3; width: 16; height: 16; radius: 8
                            color: outputEnabled.checked ? Theme.accentText : Theme.text
                        }
                    }
                    contentItem: Item {}
                    background: ButtonBackground { idleColor: "transparent"; highlighted: outputEnabled.visualFocus; pressed: outputEnabled.down }
                    PassiveToolTip { target: outputEnabled; text: card.record.name + (outputEnabled.enabled ? "" : "\n" + qsTr("At least one independent display must stay enabled.")) }
                }
            }
            ShellText { text: card.record.label; Layout.fillWidth: true; elide: Text.ElideRight; textFormat: Text.PlainText }
            Note {
                objectName: "displaySummary:" + card.record.name
                text: !card.record.enabled ? qsTr("Display disabled") : [
                    card.record.mode.split("@")[0].replace("x", " × "), root.rateLabel(card.record.mode), Math.round(card.record.scale * 100) + "%",
                    card.record.transform === 0 ? "" : root.rotations[card.record.transform],
                    card.record.mirror === "none" ? "" : qsTr("Mirroring %1").arg(card.record.mirror)
                ].filter(Boolean).join(" · ")
            }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                BrightnessControl {
                    objectName: "displayBrightness:" + card.record.name
                    Layout.fillWidth: true; record: card.brightness; canAdjust: card.editable
                    label: qsTr("Brightness for %1").arg(card.record.label)
                    onEdited: value => root.service.setBrightness(card.record.name, value)
                }
                IconButton {
                    id: optionsButton
                    readonly property alias menu: options
                    objectName: "displayOptions:" + card.record.name
                    iconName: "settings"; text: qsTr("Options for %1").arg(card.record.label)
                    enabled: options.visible || card.editable
                    onClicked: { if (options.visible) options.close(); else options.open(); }
                    Popup {
                        id: options
                        objectName: "displayPopup:" + card.record.name
                        popupType: Popup.Item
                        parent: optionsButton
                        x: optionsButton.width - width; y: optionsButton.height
                        width: Math.min(320, root.width); padding: 6
                        // Use the window's available height, including the space
                        // above the drawer body, so short menus need no scrollbar.
                        margins: 8
                        height: Math.max(0, Math.min(itemsHeight + topPadding + bottomPadding, 560,
                            (Overlay.overlay?.height ?? root.height) - 16))
                        focus: true
                        // Exclude the cog so a second click toggles the popup closed.
                        closePolicy: Popup.CloseOnPressOutsideParent
                        background: Surface { color: Theme.background; radius: Theme.controlRadius }
                        ListModel { id: optionsModel; dynamicRoles: true }
                        readonly property real itemsHeight: root.optionsFor(card.record).reduce((total, entry) => total + entryHeight(entry.kind), 0)
                        function entryHeight(kind: string): int { return kind === "heading" ? 28 : kind === "separator" ? 13 : 36; }
                        function sync(): void { Models.sync(optionsModel, root.optionsFor(card.record), "key"); }
                        function activate(entry): void {
                            if (!card.editable) return;
                            if (entry.kind === "option") root.service.change(card.record, entry.values);
                            else if (entry.kind === "action") {
                                if (entry.action === "recommended") root.service.change(card.record, {mode: "preferred"});
                                else root.startTest(entry.action, card.record);
                            }
                            else if (entry.kind === "awake") root.comfortService.setAwake(card.record, !root.comfortService.awakeFor(card.record.name));
                            else return;
                            close();
                        }
                        function step(direction: int): void {
                            for (let offset = 1; offset <= optionsModel.count; offset++) {
                                const next = (list.currentIndex + direction * offset + optionsModel.count) % optionsModel.count;
                                if (!["option", "action", "awake"].includes(optionsModel.get(next).record.kind)) continue;
                                list.currentIndex = next;
                                list.positionViewAtIndex(next, ListView.Contain);
                                return;
                            }
                        }
                        onAboutToShow: {
                            sync(); root.openOptions = options;
                        }
                        onOpened: list.forceActiveFocus()
                        onClosed: {
                            if (root.openOptions === options) root.openOptions = null;
                        }
                        Component.onCompleted: sync()
                        Component.onDestruction: {
                            if (root.openOptions === options) {
                                root.openOptions = null;
                            }
                        }
                        Connections { target: card; function onRecordChanged(): void { options.sync(); } }
                        Connections { target: root; function onDisplaysChanged(): void { options.sync(); } }
                        Connections { target: root.comfortService; function onStateChanged(): void { options.sync(); } }
                        contentItem: FocusScope {
                            Keys.onEscapePressed: event => { options.close(); event.accepted = true; }
                            ColumnLayout {
                                anchors.fill: parent; spacing: 8
                                ScrollListView {
                                    id: list
                                    objectName: "displayOptionsList:" + card.record.name
                                    Layout.fillWidth: true; Layout.fillHeight: true
                                    clip: true; model: optionsModel; currentIndex: -1
                                    // Keep this finite menu instantiated so mixed row
                                    // heights do not leave the last entry partly clipped.
                                    cacheBuffer: options.itemsHeight
                                    Keys.onDownPressed: options.step(1)
                                    Keys.onUpPressed: options.step(-1)
                                    Keys.onReturnPressed: if (currentIndex >= 0) options.activate(optionsModel.get(currentIndex).record)
                                    Keys.onEnterPressed: if (currentIndex >= 0) options.activate(optionsModel.get(currentIndex).record)
                                    ScrollBar.vertical: ScrollBar { policy: list.contentHeight > list.height ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff }
                                    delegate: ShellMenuItem {
                                        id: entry
                                        required property var record
                                        required property int index
                                        width: list.width
                                        objectName: ["option", "action", "awake"].includes(record.kind) ? "displayOption:" + card.record.name + ":" + record.key : "displayMenu:" + card.record.name + ":" + record.key
                                        text: record.text ?? ""; marked: !!record.marked
                                        implicitHeight: options.entryHeight(record.kind)
                                        enabled: ["option", "action", "awake"].includes(record.kind) && card.editable && (record.kind !== "awake" || !root.comfortService.busy)
                                        highlighted: hovered || (list.activeFocus && ListView.isCurrentItem)
                                        opacity: ["option", "action", "awake"].includes(record.kind) && !enabled ? 0.5 : 1
                                        Accessible.checkable: ["option", "awake"].includes(record.kind)
                                        Accessible.checked: marked
                                        contentItem: RowLayout {
                                            visible: entry.record.kind !== "separator"
                                            spacing: 8
                                            Icon {
                                                visible: ["option", "action", "awake"].includes(entry.record.kind)
                                                name: entry.record.kind === "action" ? "monitor" : "check"
                                                opacity: entry.record.kind === "action" || entry.marked ? 1 : 0
                                                Layout.preferredWidth: 16; Layout.preferredHeight: 16
                                                color: entry.highlighted ? Theme.accent : Theme.text
                                            }
                                            ShellText {
                                                text: entry.text; Layout.fillWidth: true; elide: Text.ElideRight
                                                color: entry.record.kind === "heading" ? Theme.muted : Theme.text
                                                font.pixelSize: entry.record.kind === "heading" ? Theme.smallFontSize : Theme.fontSize
                                            }
                                        }
                                        background: ButtonBackground {
                                            idleColor: "transparent"; visible: ["option", "action", "awake"].includes(entry.record.kind)
                                            highlighted: entry.highlighted; pressed: entry.down
                                        }
                                        Rectangle {
                                            visible: entry.record.kind === "separator"
                                            anchors.left: parent.left; anchors.right: parent.right
                                            anchors.leftMargin: 6; anchors.rightMargin: 6
                                            anchors.verticalCenter: parent.verticalCenter
                                            height: 1; color: Theme.border
                                        }
                                        onTriggered: { list.currentIndex = index; options.activate(record); }
                                    }
                                }

                            }
                        }
                    }
                }
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 8
        RowLayout {
            visible: root.service.error !== ""; Layout.fillWidth: true
            Note { objectName: "displayError"; text: root.service.error; color: Theme.danger }
            IconButton { iconName: "refresh-cw"; text: qsTr("Refresh displays"); onClicked: root.service.refresh() }
            IconButton { iconName: "x"; text: qsTr("Dismiss display error"); onClicked: root.service.error = "" }
        }
        RowLayout {
            visible: !root.service.loaded
            BusySpinner { implicitWidth: 16; implicitHeight: 16 }
            Note { text: qsTr("Loading connected displays…") }
        }
        Note { visible: root.displayTests.error !== ""; text: root.displayTests.error; color: Theme.danger }
        DrawerColumn {
            objectName: "displayScroll"; Layout.fillWidth: true; Layout.fillHeight: true
            Heading { text: qsTr("Displays") }
            Note { visible: root.service.loaded && !displaysModel.count; text: qsTr("No connected displays available.") }
            Repeater { model: displaysModel; delegate: DisplayCard {} }
            ComfortControls { service: root.comfortService; active: root.active }
        }
        Button {
            id: identifyButton
            objectName: "displayIdentifyButton"
            Layout.fillWidth: true; implicitHeight: 48; padding: 10; hoverEnabled: true
            enabled: root.active && (root.displayTests.mode === "identify" || (root.canEdit && root.displays.some(record => record.enabled)))
            text: root.displayTests.mode === "identify" ? qsTr("Hide display labels") : qsTr("Identify displays")
            onClicked: {
                if (root.displayTests.mode === "identify") root.displayTests.stop();
                else root.displayTests.identify(root.displays);
            }
            contentItem: Item {
                RowLayout {
                    anchors.centerIn: parent; width: Math.min(parent.width, implicitWidth); spacing: 12
                    Icon { name: "monitor"; Layout.preferredWidth: 22; Layout.preferredHeight: 22 }
                    ShellText { text: identifyButton.text; Layout.fillWidth: true; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; font.weight: Font.Medium }
                }
            }
            background: ButtonBackground { idleColor: Theme.surface; highlighted: identifyButton.hovered || identifyButton.visualFocus; pressed: identifyButton.down }
            PassiveToolTip { target: identifyButton; text: qsTr("Show each enabled display’s name and connector for five seconds.") }
        }
    }
}
