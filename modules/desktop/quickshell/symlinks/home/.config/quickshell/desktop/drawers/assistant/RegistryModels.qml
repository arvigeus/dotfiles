pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

Column {
    id: root
    required property string source
    required property string query
    property bool active: false
    property int refreshToken: 0
    property string repository: ""
    readonly property string sourceName: source === "huggingface" ? qsTr("Hugging Face") : qsTr("ModelScope")
    readonly property var details: inspection.result
    readonly property var variants: details?.variants ?? []
    readonly property bool compatible: !!details && (!AssistantService.needsVision || details.labels.includes("vision"))
    objectName: "assistantRegistry:" + source
    spacing: Theme.spacingSmall
    visible: active
    onQueryChanged: repository = ""
    onActiveChanged: if (!active)
        repository = ""

    RegistryRequest {
        id: discovery
        objectName: "assistantRegistrySearch:" + root.source
        active: root.active
        payload: ({
                op: "registry_search",
                source: root.source,
                query: root.query,
                refresh: root.refreshToken
            })
    }
    RegistryRequest {
        id: inspection
        objectName: "assistantRegistryInspection:" + root.source
        active: root.active && !!root.repository
        delay: 0
        payload: ({
                op: "registry_variants",
                source: root.source,
                repository: root.repository
            })
    }
    RowLayout {
        width: parent.width
        ShellText {
            Layout.fillWidth: true
            text: root.sourceName
            color: Theme.muted
            font.pixelSize: Theme.smallFontSize
        }
        BusyIndicator {
            Layout.preferredWidth: Theme.iconSize
            Layout.preferredHeight: Theme.iconSize
            running: discovery.busy
            visible: running
        }
        IconButton {
            visible: !!discovery.error
            iconName: "refresh-cw"
            text: qsTr("Retry %1 search").arg(root.sourceName)
            onClicked: discovery.reload()
        }
    }
    ShellText {
        width: parent.width
        visible: !!discovery.error || (!discovery.busy && discovery.result?.results?.length === 0)
        text: discovery.error || qsTr("No matching repositories")
        color: discovery.error ? Theme.danger : Theme.muted
        font.pixelSize: Theme.smallFontSize
        wrapMode: Text.Wrap
    }
    Repeater {
        model: discovery.result?.results ?? []
        delegate: Column {
            id: entry
            required property var modelData
            readonly property bool expanded: root.repository === modelData.id
            width: root.width
            spacing: Theme.spacingSmall
            Button {
                id: repositoryButton
                objectName: "assistantRepository:" + root.source + ":" + entry.modelData.id
                width: parent.width
                padding: Theme.spacingMedium
                implicitHeight: contentItem.implicitHeight + topPadding + bottomPadding
                hoverEnabled: true
                text: entry.modelData.id
                Accessible.name: text
                Accessible.expanded: entry.expanded
                onClicked: root.repository = entry.expanded ? "" : entry.modelData.id
                background: ButtonBackground {
                    idleColor: Theme.surface
                    idleBorderColor: entry.expanded ? Theme.accent : Theme.border
                    highlighted: repositoryButton.hovered || repositoryButton.visualFocus
                    pressed: repositoryButton.down
                }
                contentItem: RowLayout {
                    spacing: Theme.spacingMedium
                    ShellText {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: entry.modelData.id
                        elide: Text.ElideMiddle
                    }
                    Icon {
                        name: entry.expanded ? "chevron-up" : "chevron-down"
                        color: Theme.muted
                    }
                }
                PassiveToolTip {
                    target: repositoryButton
                    text: entry.modelData.id + "\n" + qsTr("Check available quantizations in %1").arg(root.sourceName)
                }
            }
            // One install form per provider; move it below the expanded row.
            Loader {
                width: parent.width
                active: entry.expanded
                visible: active
                sourceComponent: installForm
            }
        }
    }
    Component {
        id: installForm
        ColumnLayout {
            spacing: Theme.spacingSmall
            RowLayout {
                Layout.fillWidth: true
                visible: inspection.busy
                BusyIndicator {
                    Layout.preferredWidth: Theme.iconSize
                    Layout.preferredHeight: Theme.iconSize
                    running: inspection.busy
                }
                ShellText {
                    Layout.fillWidth: true
                    text: qsTr("Checking model files…")
                    color: Theme.muted
                    font.pixelSize: Theme.smallFontSize
                }
            }
            ShellText {
                Layout.fillWidth: true
                visible: !!inspection.error || (!!root.details && !root.compatible)
                text: inspection.error || qsTr("A vision model is required for these images.")
                color: Theme.danger
                wrapMode: Text.Wrap
                font.pixelSize: Theme.smallFontSize
            }
            ShellButton {
                visible: !!inspection.error
                text: qsTr("Retry")
                onClicked: inspection.reload()
            }
            RowLayout {
                Layout.fillWidth: true
                visible: root.compatible
                ShellChoice {
                    id: quantization
                    objectName: "assistantRegistryQuantization:" + root.source
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    model: root.variants.map(row => row.name + (row.size > 0 ? " · " + (row.size / 1e9).toFixed(1) + " GB" : ""))
                    function chooseDefault(): void {
                        currentIndex = Math.max(0, root.variants.findIndex(row => row.name === "Q4_K_M"));
                    }
                    onModelChanged: Qt.callLater(chooseDefault)
                    Accessible.name: qsTr("Quantization")
                }
                ShellButton {
                    objectName: "assistantRegistryDownload:" + root.source
                    text: qsTr("Download")
                    enabled: AssistantService.online && !AssistantService.busy && !!root.variants[quantization.currentIndex]
                    onClicked: AssistantService.installRegistryModel(root.source, root.repository, root.variants[quantization.currentIndex].name)
                }
            }
        }
    }
}
