pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../../ui"
import "../audio"

ColumnLayout {
    id: root
    spacing: Theme.gap
    property alias statusContent: statusSlot.data
    property var service
    property string kind: "VTODO"
    property var entry: null
    property string selectedDate: ""
    property bool active: true
    readonly property bool task: kind === "VTODO"
    readonly property bool pending: service.isPending ? service.isPending(entry) : !!service.writing
    readonly property bool existing: !!entry?.href
    readonly property bool writable: !existing || !!entry?.editable
    readonly property var collections: service.state.calendars.filter(row => row.writable && row.components.includes(kind) && (task ? row.tasks_enabled : row.events_enabled))
    readonly property bool popupOpen: collection.popup.visible || status.popup.visible || parentTask.popup.visible || presets.popup.visible
    function closePopups(): void {
        for (const chooser of [collection, status, parentTask, presets]) chooser.popup.close();
    }
    onVisibleChanged: if (!visible) closePopups()
    signal cancelled()

    function load(): void {
        if (!entry) return;
        form.contentItem.contentY = 0;
        title.text = entry.summary || ""; notes.text = entry.description || "";
        collection.currentIndex = existing ? collections.findIndex(row => row.slug === (entry.collection || (task ? entry.list_slug : entry.calendar_slug))) : Math.max(0, collections.findIndex(row => row.slug === entry.collection));
        startDate.text = task ? entry.start_date || "" : entry.start_date || (existing ? Qt.formatDate(new Date(entry.start), "yyyy-MM-dd") : selectedDate);
        endDate.text = task ? entry.due || "" : entry.end_date || (existing ? (entry.all_day ? entry.last_date : Qt.formatDate(new Date(entry.end), "yyyy-MM-dd")) : selectedDate);
        allDay.checked = !!entry.all_day;
        startTime.text = task ? entry.start_time || "" : entry.start_time || (existing && !entry.all_day ? Qt.formatTime(new Date(entry.start), "HH:mm") : "09:00");
        endTime.text = task ? entry.due_time || "" : entry.end_time || (existing && !entry.all_day ? Qt.formatTime(new Date(entry.end), "HH:mm") : "10:00");
        priority.value = entry.priority || 0; percent.value = entry.percent || 0;
        status.currentIndex = Math.max(0, status.model.findIndex(row => row.value === (entry.status || "NEEDS-ACTION")));
        tags.text = entry.categories || ""; rule.text = entry.recurrence_rule || "";
        location.text = entry.location || ""; link.text = entry.url || "";
        parentTask.currentIndex = Math.max(0, parentTask.model.findIndex(row => row.uid === entry.parent));
    }
    function save(): void {
        const value = Object.assign({}, entry, {
            summary: title.text, description: notes.text, collection: collection.currentValue,
            start_date: startDate.text, start_time: root.task || !allDay.checked ? startTime.text : "",
            end_date: endDate.text, end_time: endTime.text, all_day: allDay.checked,
            due: endDate.text, due_time: endTime.text, priority: priority.value, percent: percent.value,
            status: status.currentValue, categories: tags.text, parent: parentTask.currentValue || "",
            recurrence_rule: rule.text, location: location.text, url: link.text
        });
        service.mutate("save", kind, value);
    }
    onEntryChanged: { deleteButton.cancel(); Qt.callLater(load); }
    onKindChanged: { deleteButton.cancel(); Qt.callLater(load); }
    component Note: ShellText { color: Theme.muted; font.pixelSize: Theme.smallFontSize; Layout.fillWidth: true; wrapMode: Text.Wrap }
    RowLayout {
        objectName: "itemToolbar"
        Layout.fillWidth: true; spacing: 4
        AudioIconButton {
            objectName: "itemBack"; iconName: "chevron-left"; text: qsTr("Back")
            enabled: !root.pending; onClicked: root.cancelled()
        }
        ShellText {
            Layout.fillWidth: true; Layout.minimumWidth: 0; elide: Text.ElideRight
            text: root.task ? (root.existing ? qsTr("Task details") : qsTr("New task"))
                : root.existing ? qsTr("Event details") : qsTr("New event")
        }
        HoldButton {
            id: deleteButton
            objectName: "itemDelete"
            text: root.entry?.recurring ? qsTr("Hold to delete the entire series and its saved occurrences")
                : root.task ? qsTr("Hold to delete task") : qsTr("Hold to delete event")
            Accessible.name: text; hint: text
            implicitWidth: Theme.controlHeight; implicitHeight: Theme.controlHeight
            horizontalPadding: 8; verticalPadding: 8; idleColor: "transparent"
            contentItem: Icon { name: "trash"; color: deleteButton.hovered || deleteButton.visualFocus ? Theme.accent : Theme.muted }
            visible: root.existing && root.writable
            enabled: !root.pending; armed: root.active
            onConfirmed: root.service.mutate("delete", root.kind, Object.assign({}, root.entry, {collection: root.task ? root.entry.list_slug : root.entry.calendar_slug}))
        }
        AudioIconButton {
            objectName: "itemSave"; iconName: "check"; text: root.pending ? qsTr("Saving…") : qsTr("Save")
            visible: root.writable
            enabled: !!title.text.trim() && collection.currentIndex >= 0 && !root.pending
            onClicked: root.save()
        }
    }
    ColumnLayout { id: statusSlot; Layout.fillWidth: true; spacing: 0 }
    DrawerColumn {
        id: form; objectName: "itemForm"
        Layout.fillWidth: true; Layout.fillHeight: true
        Note { visible: root.task && !!root.entry?.recurring; text: qsTr("Changes apply to the entire recurring task series.") }
        Note { visible: !root.writable; text: qsTr("This item is read-only here. Recurring events and individual task exceptions can be edited in Nextcloud.") }
        InputField { id: title; objectName: "itemTitle"; Layout.fillWidth: true; placeholderText: qsTr("Title"); maximumLength: 250; enabled: root.writable && !root.pending; Accessible.name: qsTr("Title") }
        Note { text: root.task ? qsTr("Task list") : qsTr("Calendar") }
        ShellChoice {
            id: collection; visible: root.writable; Layout.fillWidth: true; model: root.collections; textRole: "name"; valueRole: "slug"
            enabled: !root.existing && !root.pending; Accessible.name: root.task ? qsTr("Task list") : qsTr("Calendar")
        }
        Note { visible: !root.writable; text: (root.task ? root.entry?.list : root.entry?.calendar) || "" }
        Note { visible: !root.collections.length && root.writable; text: qsTr("No writable collection is enabled. Check calendar.json and the account permissions.") }
        ColumnLayout {
            Layout.fillWidth: true; enabled: root.writable && !root.pending; spacing: Theme.gap
            CheckBox { id: allDay; visible: !root.task; text: qsTr("All day") }
            Note { text: root.task ? qsTr("Starts · optional date and time") : qsTr("Starts · local time") }
            RowLayout {
                Layout.fillWidth: true
                InputField { id: startDate; Layout.fillWidth: true; placeholderText: "YYYY-MM-DD"; Accessible.name: qsTr("Start date") }
                InputField { id: startTime; visible: root.task || !allDay.checked; Layout.preferredWidth: 100; placeholderText: "HH:MM"; Accessible.name: qsTr("Start time") }
            }
            Note { text: root.task ? qsTr("Due · optional date and time") : allDay.checked ? qsTr("Ends · inclusive date") : qsTr("Ends · local time") }
            RowLayout {
                Layout.fillWidth: true
                InputField { id: endDate; Layout.fillWidth: true; placeholderText: "YYYY-MM-DD"; Accessible.name: root.task ? qsTr("Due date") : qsTr("End date") }
                InputField { id: endTime; visible: root.task || !allDay.checked; Layout.preferredWidth: 100; placeholderText: "HH:MM"; Accessible.name: root.task ? qsTr("Due time") : qsTr("End time") }
            }
            ColumnLayout {
                visible: root.task; Layout.fillWidth: true; spacing: Theme.gap
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Note { text: qsTr("Priority · 0 none, 1 highest") }
                        NumberField { id: priority; from: 0; to: 9; Accessible.name: qsTr("Task priority") }
                    }
                    ColumnLayout {
                        Note { text: qsTr("Progress %") }
                        NumberField { id: percent; from: 0; to: 100; Accessible.name: qsTr("Task progress") }
                    }
                }
                ShellChoice {
                    id: status; Layout.fillWidth: true; textRole: "name"; valueRole: "value"
                    model: [{name: qsTr("Open"), value: "NEEDS-ACTION"}, {name: qsTr("In progress"), value: "IN-PROCESS"}, {name: qsTr("Completed"), value: "COMPLETED"}, {name: qsTr("Cancelled"), value: "CANCELLED"}]
                    Accessible.name: qsTr("Task status")
                }
                InputField { id: tags; Layout.fillWidth: true; placeholderText: qsTr("Tags, separated by commas"); Accessible.name: qsTr("Task tags") }
                Note { text: qsTr("Parent task") }
                ShellChoice {
                    id: parentTask; Layout.fillWidth: true; textRole: "summary"; valueRole: "uid"
                    model: [{summary: qsTr("None"), uid: ""}].concat(root.service.state.tasks.filter(row => !row.exception && row.uid !== root.entry?.uid && row.list_slug === collection.currentValue))
                    Accessible.name: qsTr("Parent task")
                }
                Note { text: qsTr("Repeat") }
                ShellChoice {
                    id: presets; Layout.fillWidth: true
                    model: [qsTr("Choose preset…"), qsTr("Does not repeat"), qsTr("Daily"), qsTr("Weekdays"), qsTr("Weekly"), qsTr("Monthly"), qsTr("Yearly")]
                    onActivated: if (currentIndex > 0) rule.text = ["", "FREQ=DAILY", "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "FREQ=WEEKLY", "FREQ=MONTHLY", "FREQ=YEARLY"][currentIndex - 1]
                    Accessible.name: qsTr("Recurrence preset")
                }
                InputField { id: rule; Layout.fillWidth: true; placeholderText: "FREQ=WEEKLY;INTERVAL=2;COUNT=10"; Accessible.name: qsTr("Recurrence rule") }
                Note { text: qsTr("A repeating task needs a start or due date. Complete it with its checkbox to save that occurrence and advance the next one. COUNT and UNTIL can limit repeats.") }
            }
            InputField { id: location; Layout.fillWidth: true; placeholderText: qsTr("Location"); Accessible.name: qsTr("Location") }
            InputField { id: link; Layout.fillWidth: true; placeholderText: qsTr("URL"); Accessible.name: qsTr("URL") }
            Note { text: qsTr("Notes") }
            TextArea {
                id: notes; Layout.fillWidth: true; implicitHeight: Math.max(120, contentHeight + 24); wrapMode: TextEdit.Wrap
                color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize
                selectByMouse: true; padding: 12; Accessible.name: qsTr("Notes")
                background: Rectangle { color: Theme.surface; radius: Theme.controlRadius; border.width: 1; border.color: notes.activeFocus ? Theme.accent : Theme.border }
            }
        }
    }
}
