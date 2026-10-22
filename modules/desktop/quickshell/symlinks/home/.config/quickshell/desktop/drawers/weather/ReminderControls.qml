pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../ui"

ColumnLayout {
    id: root
    property var service: ReminderService
    property bool active: false
    readonly property var focusEntry: service.entries.find(entry => entry.kind === "pomodoro") ?? null
    readonly property var reminders: service.entries.filter(entry => entry.kind === "alarm")
    readonly property bool popupOpen: focusEditor.visible || reminderEditor.visible
    signal popupOpened()
    spacing: 16
    function closePopup(): void { focusEditor.close(); reminderEditor.close(); }
    function togglePopup(popup): void {
        const wasOpen = popup.visible;
        closePopup();
        if (!wasOpen) popup.open();
    }
    onActiveChanged: if (!active) closePopup()

    component Heading: ShellText { Layout.fillWidth: true; font.weight: Font.DemiBold }
    component Note: ShellText { color: Theme.muted; font.pixelSize: Theme.smallFontSize }
    component Action: ShellButton { Layout.fillWidth: true }
    component Editor: Popup {
        id: popup
        required property Item button
        popupType: Popup.Item
        parent: button
        x: 0; y: button.height + 8
        // Use the laid-out trigger width so the editor fills its section.
        width: button.width
        padding: 16; margins: 8; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        background: Surface { color: Theme.background; radius: Theme.controlRadius }
        onAboutToShow: { root.popupOpened(); root.service.now = root.service.clock(); }
        onClosed: if (root.active) button.forceActiveFocus()
    }

    ColumnLayout {
        Layout.fillWidth: true; spacing: 8
        Heading { text: qsTr("Focus") }
        Action {
            id: focusButton
            objectName: "focusToggle"
            iconName: root.focusEntry ? "x" : "play"
            text: !root.focusEntry ? qsTr("Set up focus") : root.focusEntry.phase === "focus"
                ? qsTr("Stop focus · %1").arg(root.service.remaining(root.focusEntry))
                : qsTr("Stop break · %1").arg(root.service.remaining(root.focusEntry))
            checked: !!root.focusEntry || focusEditor.visible
            onClicked: {
                if (root.focusEntry) root.service.stop(root.focusEntry.id);
                else root.togglePopup(focusEditor);
            }
            Editor {
                id: focusEditor
                objectName: "focusPopup"; button: focusButton
                onOpened: focusMinutes.focusEditor()
                contentItem: ColumnLayout {
                    spacing: 12
                    RowLayout {
                        Layout.fillWidth: true; spacing: 12
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 4
                            Note { text: qsTr("Focus · min") }
                            NumberField {
                                id: focusMinutes
                                objectName: "reminderFocusMinutes"
                                Layout.fillWidth: true; value: 25; from: 1; to: 1440
                                Accessible.name: qsTr("Focus minutes")
                                onAccepted: if (startFocus.enabled) startFocus.clicked()
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 4
                            Note { text: qsTr("Break · min") }
                            NumberField {
                                id: breakMinutes
                                objectName: "reminderBreakMinutes"
                                Layout.fillWidth: true; value: 5; from: 1; to: 1440
                                Accessible.name: qsTr("Break minutes")
                                onAccepted: if (startFocus.enabled) startFocus.clicked()
                            }
                        }
                    }
                    Note { text: qsTr("Repeats until stopped.") }
                    ShellButton {
                        id: startFocus
                        objectName: "focusStart"; Layout.fillWidth: true; text: qsTr("Start")
                        enabled: focusMinutes.acceptableInput && breakMinutes.acceptableInput && !root.focusEntry
                        onClicked: if (root.service.addPomodoro(focusMinutes.number, breakMinutes.number)) focusEditor.close()
                    }
                }
            }
        }
    }
    ColumnLayout {
        Layout.fillWidth: true; spacing: 8
        Heading { text: qsTr("Reminders") }
        Action {
            id: add
            objectName: "reminderAdd"
            iconName: "alarm-clock"; text: qsTr("Add reminder"); checked: reminderEditor.visible
            onClicked: root.togglePopup(reminderEditor)
            Editor {
                id: reminderEditor
                objectName: "reminderPopup"; button: add
                property double day: 0
                readonly property string time: String(hour.number).padStart(2, "0") + ":" + String(minute.number).padStart(2, "0")
                readonly property bool futureTime: hour.acceptableInput && minute.acceptableInput && root.service.nextAlarm(time, root.service.now, day) > 0
                onOpened: {
                    const next = new Date(Math.floor(root.service.clock() / 60000) * 60000 + 60000);
                    day = next.getTime(); hour.value = next.getHours(); minute.value = next.getMinutes();
                    hour.focusEditor();
                }
                Timer { interval: 1000; repeat: true; running: reminderEditor.visible; onTriggered: root.service.now = root.service.clock() }
                contentItem: ColumnLayout {
                    spacing: 12
                    RowLayout {
                        spacing: 6
                        NumberField {
                            id: hour
                            objectName: "reminderHour"; from: 0; to: 23; padded: true
                            Layout.preferredWidth: 88; Accessible.name: qsTr("Reminder hour")
                            onAccepted: minute.focusEditor()
                        }
                        ShellText { text: ":"; verticalAlignment: Text.AlignVCenter }
                        NumberField {
                            id: minute
                            objectName: "reminderMinute"; from: 0; to: 59; padded: true
                            Layout.preferredWidth: 88; Accessible.name: qsTr("Reminder minute")
                            onAccepted: message.forceActiveFocus()
                        }
                    }
                    Note {
                        Layout.fillWidth: true; wrapMode: Text.Wrap
                        visible: !reminderEditor.futureTime || Qt.formatDate(new Date(reminderEditor.day), "yyyy-MM-dd") !== Qt.formatDate(new Date(root.service.now), "yyyy-MM-dd")
                        text: reminderEditor.futureTime ? qsTr("Tomorrow") : qsTr("Choose a later time.")
                    }
                    InputField {
                        id: message
                        objectName: "reminderAlarmMessage"
                        Layout.fillWidth: true; placeholderText: qsTr("Message (optional)"); maximumLength: 160
                        Accessible.name: qsTr("Reminder message")
                        onAccepted: if (addReminder.enabled) addReminder.clicked()
                    }
                    ShellButton {
                        id: addReminder
                        objectName: "reminderStart"; Layout.fillWidth: true; text: qsTr("Schedule")
                        enabled: reminderEditor.futureTime
                        onClicked: if (root.service.addAlarm(reminderEditor.time, message.text, reminderEditor.day)) { message.clear(); reminderEditor.close(); }
                    }
                }
            }
        }
        Repeater {
            model: root.reminders
            delegate: RowLayout {
                id: reminder
                required property var modelData
                objectName: "reminder:" + modelData.id
                Layout.fillWidth: true; spacing: 8
                Icon { name: "alarm-clock"; color: Theme.muted; implicitWidth: 16; implicitHeight: 16 }
                ColumnLayout {
                    Layout.fillWidth: true; spacing: 0
                    ShellText { text: reminder.modelData.message || qsTr("Reminder"); Layout.fillWidth: true; elide: Text.ElideRight }
                    Note { objectName: "reminderStatus:" + reminder.modelData.id; text: root.service.dueLabel(reminder.modelData.deadline) }
                }
                IconButton {
                    objectName: "reminderStop:" + reminder.modelData.id
                    iconName: "x"; text: qsTr("Stop %1").arg(reminder.modelData.message || qsTr("reminder"))
                    background: Item {}
                    onClicked: root.service.stop(reminder.modelData.id)
                }
            }
        }
    }
}
