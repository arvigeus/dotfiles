pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Templates as T
import QtQuick.Layouts
import Quickshell
import "../ui"
import "keyboard"

DrawerPage {
    id: root
    property var service: InputLanguage
    // Observation follows this page; the singleton finishes pending adjustments.
    property var backlightService: BacklightService
    KeyedModel { id: backlightsModel; values: root.backlightService.values; keyField: "key" }
    readonly property alias referencePopup: reference
    property Popup openLighting: null
    property bool focusAfterSelection: false
    readonly property var languages: [
        {code: "en", name: "English", flag: "", detail: ""},
        {code: "bg", name: "Български", flag: "🇧🇬", detail: qsTr("Phonetic")},
        {code: "vi", name: "Tiếng Việt", flag: "🇻🇳", detail: qsTr("Telex")}
    ]
    escapeHandler: openLighting ? (() => openLighting.close()) : reference.visible ? (() => reference.close()) : null
    onActiveChanged: {
        backlightService.observe(root, active);
        if (active) service.refresh();
        else {
            reference.close(); focusAfterSelection = false; refocus.stop();
            if (openLighting) openLighting.close();
            Qt.inputMethod.reset(); testInput.clear();
        }
    }
    Component.onCompleted: { backlightService.observe(root, active); if (active) service.refresh(); }
    Component.onDestruction: backlightService.observe(root, false)
    headerActions: IconButton {
        objectName: "keyboardSettings"
        iconName: "pencil"; text: qsTr("Input method settings")
        onClicked: { Apps.launch(["fcitx5-configtool"]); root.closeRequested(); }
    }
    Connections {
        target: root.service
        function onSelectionFinished(code, success): void {
            if (!root.focusAfterSelection) return;
            root.focusAfterSelection = false;
            if (root.active && success) refocus.restart();
        }
    }
    // Cold-started Fcitx needs a fresh text-input focus transition.
    Timer { id: refocus; interval: 100; onTriggered: if (root.active) testInput.forceActiveFocus() }
    Timer { interval: 5000; repeat: true; running: root.active; onTriggered: root.service.refresh() }
    component Note: ShellText {
        Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap; textFormat: Text.PlainText
    }
    ColumnLayout {
        anchors.fill: parent; spacing: Theme.gap
        DrawerColumn {
            objectName: "keyboardScroll"
            Layout.fillWidth: true; Layout.fillHeight: true
            RowLayout {
                Layout.fillWidth: true
                ShellText { text: qsTr("Languages"); font.weight: Font.DemiBold; Layout.fillWidth: true }
                IconButton {
                    id: helpButton
                    objectName: "keyboardHelp"; iconName: "info"; text: qsTr("Language maps and keyboard shortcuts")
                    checked: reference.visible
                    onClicked: {
                        if (root.openLighting) root.openLighting.close();
                        reference.visible ? reference.close() : reference.open();
                    }
                }
            }
            Note {
                visible: !root.service.loaded
                text: qsTr("Reading input language…")
            }
            Note { visible: root.service.error !== ""; text: root.service.error; color: Theme.danger }
            Note { objectName: "keyboardPrimaryLabel"; text: qsTr("Primary language") }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 4
                Repeater {
                    model: root.languages
                    delegate: ColumnLayout {
                        id: language
                        required property var modelData
                        Layout.fillWidth: true; spacing: 4
                        Note { visible: language.modelData.code === "bg"; text: qsTr("Secondary language"); topPadding: 12; bottomPadding: 4 }
                        Button {
                            id: choice
                            objectName: "language-" + language.modelData.code
                            Layout.fillWidth: true; implicitHeight: 60; padding: 10; hoverEnabled: true
                            readonly property bool current: root.service.loaded && root.service.language === language.modelData.code
                            readonly property bool switching: root.service.selectingLanguage === language.modelData.code
                            readonly property bool unavailable: language.modelData.code === "vi" && !root.service.available
                            enabled: root.active && root.service.loaded && !root.service.selecting && !unavailable
                            text: language.modelData.name
                            Accessible.name: text + (current ? qsTr(", active") : "")
                                + (language.modelData.code === root.service.secondary ? qsTr(", secondary language") : "")
                                + (switching ? qsTr(", switching") : "")
                            opacity: enabled || switching ? 1 : 0.45
                            contentItem: RowLayout {
                                spacing: 12
                                Item {
                                    Layout.preferredWidth: 28; Layout.preferredHeight: 28
                                    Icon { anchors.centerIn: parent; name: "languages"; width: 22; height: 22; visible: language.modelData.code === "en" }
                                    ShellText { anchors.centerIn: parent; text: language.modelData.flag; font.pixelSize: 24; visible: language.modelData.code !== "en" }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 2
                                    ShellText { text: choice.text; Layout.fillWidth: true; elide: Text.ElideRight; font.weight: choice.current ? Font.DemiBold : Font.Normal }
                                    Note { visible: language.modelData.detail !== ""; text: language.modelData.detail }
                                }
                                Item {
                                    Layout.preferredWidth: 18; Layout.preferredHeight: 18
                                    Icon {
                                        anchors.fill: parent
                                        objectName: "language-secondary-" + language.modelData.code
                                        name: "check"; color: Theme.text
                                        visible: root.service.loaded && language.modelData.code === root.service.secondary && !choice.switching
                                    }
                                    BusySpinner {
                                        anchors.fill: parent
                                        objectName: "language-loading-" + language.modelData.code
                                        visible: choice.switching
                                        running: visible && root.active
                                    }
                                }
                            }
                            background: ButtonBackground {
                                idleColor: choice.current ? Theme.accentSurface : Theme.surface
                                highlighted: choice.hovered || choice.visualFocus; pressed: choice.down
                            }
                            onClicked: {
                                Qt.inputMethod.commit(); root.forceActiveFocus();
                                root.focusAfterSelection = true;
                                root.service.select(language.modelData.code);
                            }
                        }
                    }
                }
            }
            Note {
                visible: root.service.loaded && !root.service.available
                text: qsTr("Vietnamese is unavailable. It needs Fcitx5, UniKey and the Vietnamese input service.")
            }
            ColumnLayout {
                visible: backlightsModel.values.length > 0 || root.backlightService.error !== ""
                    || (root.backlightService.loaded === false && root.backlightService.busy === true)
                Layout.fillWidth: true; spacing: 4
                ShellText { text: qsTr("Keyboards"); font.weight: Font.DemiBold }
                RowLayout {
                    visible: root.backlightService.loaded === false && root.backlightService.busy === true
                    BusySpinner { implicitWidth: 16; implicitHeight: 16 }
                    Note { text: qsTr("Detecting keyboards…") }
                }
                Repeater {
                    model: backlightsModel
                    delegate: BacklightCard {
                        required property var modelData
                        record: modelData
                        Layout.fillWidth: true; service: root.backlightService; active: root.active
                        onOptionsOpened: menu => {
                            if (root.openLighting && root.openLighting !== menu) root.openLighting.close();
                            reference.close(); root.openLighting = menu;
                        }
                        onOptionsClosed: menu => { if (root.openLighting === menu) root.openLighting = null; }
                    }
                }
                Note { visible: root.backlightService.error !== ""; text: root.backlightService.error; color: Theme.danger }
            }
        }
        InputField {
            id: testInput
            objectName: "keyboardTestInput"
            Layout.fillWidth: true
            enabled: root.active && !root.service.selecting
            placeholderText: qsTr("Type here to test…")
            Accessible.name: qsTr("Test your keyboard")
        }
    }

    component ReferenceTab: T.TabButton {
        id: tab
        width: Math.max(0, tabs.availableWidth - tabs.spacing * (tabs.count - 1)) / Math.max(1, tabs.count)
        implicitHeight: 38
        padding: 8
        hoverEnabled: true
        contentItem: ShellText {
            text: tab.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            font.weight: tab.checked ? Font.DemiBold : Font.Normal
            font.pixelSize: tabs.width < 300 ? Theme.smallFontSize : Theme.fontSize
            elide: Text.ElideRight
        }
        background: ButtonBackground {
            idleColor: Theme.surface
            highlighted: tab.checked || tab.hovered || tab.visualFocus
            pressed: tab.down
        }
    }
    component ReferenceHeading: ColumnLayout {
        property string text
        Layout.fillWidth: true; spacing: 6
        ShellText { text: parent.text; font.weight: Font.DemiBold }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border }
    }
    component Keycap: Rectangle {
        id: keycap
        required property string keys
        implicitWidth: Math.max(28, keyText.implicitWidth + 14)
        implicitHeight: 28; radius: Theme.controlRadius; color: Theme.surface
        ShellText { id: keyText; anchors.centerIn: parent; text: keycap.keys; font.family: Theme.monospaceFamily; font.pixelSize: Theme.smallFontSize }
    }
    Popup {
        id: reference
        property alias currentTab: tabs.currentIndex
        objectName: "keyboardReference"
        popupType: Popup.Item
        parent: helpButton
        x: helpButton.width - width; y: helpButton.height + 4
        width: root.width
        height: Math.max(0, Math.min(referenceScroll.contentHeight + tabs.implicitHeight + 36, 700,
            (Overlay.overlay?.height ?? root.height) - 16))
        padding: 12; margins: 8; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        onClosed: if (root.active) helpButton.forceActiveFocus()
        background: Surface { color: Theme.background; radius: Theme.controlRadius }
        contentItem: ColumnLayout {
            spacing: 12
            T.TabBar {
                id: tabs
                objectName: "keyboardReferenceTabs"
                Layout.fillWidth: true
                implicitHeight: 38
                spacing: 8; padding: 0
                background: null
                contentItem: Row {
                    spacing: tabs.spacing
                    Repeater { model: tabs.contentModel }
                }
                onCurrentIndexChanged: if (referenceScroll.contentItem) referenceScroll.contentItem.contentY = 0
                ReferenceTab { objectName: "keyboardTelexTab"; text: qsTr("Telex") }
                ReferenceTab { objectName: "keyboardPhoneticTab"; text: qsTr("Phonetic"); Accessible.name: qsTr("Bulgarian phonetic map") }
                ReferenceTab { objectName: "keyboardShortcutsTab"; text: qsTr("Shortcuts") }
            }
            DrawerColumn {
                id: referenceScroll
                objectName: "keyboardReferenceScroll"
                Layout.fillWidth: true; Layout.fillHeight: true
                ColumnLayout {
                    visible: tabs.currentIndex === 0
                    Layout.fillWidth: true; spacing: 16
                    ReferenceHeading { text: qsTr("Diacritics") }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2; columnSpacing: 16; rowSpacing: 0
                        Repeater {
                            model: [["ă", "aw"], ["â", "aa"], ["đ", "dd"], ["ê", "ee"], ["ô", "oo"], ["ơ", "ow"], ["ư", "uw"]]
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 0
                                RowLayout {
                                    Layout.fillWidth: true; Layout.preferredHeight: 38
                                    ShellText { text: modelData[0]; font.pixelSize: 20; Layout.fillWidth: true }
                                    Keycap { keys: modelData[1] }
                                }
                                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border; opacity: 0.45 }
                            }
                        }
                    }
                    ReferenceHeading { text: qsTr("Tones") }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 0
                        Repeater {
                            model: [[qsTr("Sắc (up)"), "á", "s"], [qsTr("Huyền (down)"), "à", "f"],
                                [qsTr("Hỏi (hook)"), "ả", "r"], [qsTr("Ngã (tilde)"), "ã", "x"], [qsTr("Nặng (dot)"), "ạ", "j"]]
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true; spacing: 0
                                RowLayout {
                                    Layout.fillWidth: true; Layout.preferredHeight: 38; spacing: 12
                                    ShellText { text: modelData[0]; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                    ShellText { text: modelData[1]; font.pixelSize: 20 }
                                    Keycap { keys: modelData[2] }
                                }
                                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border; opacity: 0.45 }
                            }
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        ShellText { text: qsTr("Clear mark"); Layout.fillWidth: true }
                        Keycap { keys: "z" }
                    }
                    Note { text: qsTr("Repeat a modifier to type it literally: aaa → aa.") }
                }
                ColumnLayout {
                    visible: tabs.currentIndex === 1
                    Layout.fillWidth: true; spacing: 16
                    ReferenceHeading { text: qsTr("Български · Phonetic") }
                    GridLayout {
                        Layout.fillWidth: true; columns: 3; columnSpacing: 12; rowSpacing: 0
                        Repeater {
                            model: [["а", "A"], ["б", "B"], ["в", "W"], ["г", "G"], ["д", "D"], ["е", "E"],
                                ["ж", "V"], ["з", "Z"], ["и", "I"], ["й", "J"], ["к", "K"], ["л", "L"],
                                ["м", "M"], ["н", "N"], ["о", "O"], ["п", "P"], ["р", "R"], ["с", "S"],
                                ["т", "T"], ["у", "U"], ["ф", "F"], ["х", "H"], ["ц", "C"], ["ч", "`"],
                                ["ш", "["], ["щ", "]"], ["ъ", "Y"], ["ь", "X"], ["ю", "\\"], ["я", "Q"]]
                            delegate: ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true; Layout.preferredWidth: 1; spacing: 0
                                RowLayout {
                                    Layout.fillWidth: true; Layout.preferredHeight: 38; spacing: 6
                                    ShellText { text: modelData[0]; font.pixelSize: 20; Layout.fillWidth: true }
                                    Keycap { objectName: "phonetic:" + modelData[0]; keys: modelData[1] }
                                }
                                Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.border; opacity: 0.45 }
                            }
                        }
                    }
                    Note { text: qsTr("Traditional phonetic layout · Shift+X → ѝ") }
                }
                ColumnLayout {
                    visible: tabs.currentIndex === 2
                    Layout.fillWidth: true; spacing: 12
                    Note { text: qsTr("Win is the Super key.") }
                    Repeater {
                        model: [
                            ["Alt+Shift", qsTr("Switch input language")],
                            ["Win+R", qsTr("Application search")],
                            ["Win+1 / Ctrl+Alt+Delete", qsTr("Spaces")], ["Win+Shift+P", qsTr("Performance")],
                            ["Ctrl+D in search", qsTr("Toggle app favorite")],
                            ["Win+T / F / B", qsTr("Terminal / files / browser")],
                            ["Win+Arrow", qsTr("Focus window")],
                            ["Ctrl+Win+↑ / ↓", qsTr("Previous / next workspace")],
                            ["Ctrl+Win+Shift+↑ / ↓", qsTr("Move window and follow")],
                            ["Win+Shift+← / →", qsTr("Move column")],
                            ["Win+J", qsTr("Unstack window")], ["Win+[ / ]", qsTr("Resize column")],
                            ["Win+.", qsTr("Center column")], ["Win+M / V", qsTr("Maximize / float")],
                            ["Win+mouse wheel", qsTr("Scroll columns")],
                            ["Win+left / right drag", qsTr("Move / resize window")],
                            ["Win+Q / Alt+F4", qsTr("Close window")], ["Win+L", qsTr("Lock screen")],
                            ["Print / Win+Shift+S", qsTr("Select screenshot area")], ["Win+Shift+R", qsTr("Record area / stop recording")]
                        ]
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true; spacing: 12
                            ShellText {
                                text: modelData[0]; font.family: Theme.monospaceFamily; font.pixelSize: Theme.smallFontSize
                                Layout.preferredWidth: Math.min(164, reference.availableWidth * 0.46)
                                wrapMode: Text.Wrap; textFormat: Text.PlainText
                            }
                            ShellText { text: modelData[1]; Layout.fillWidth: true; wrapMode: Text.Wrap; textFormat: Text.PlainText }
                        }
                    }
                }
            }
        }
    }
}
