pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../ui"
import "events"

DrawerPage {
    id: root
    objectName: "eventsDrawer"
    property var service: CalendarService
    property string tab: "calendar"
    property bool tasksLoaded: false
    onTabChanged: if (tab === "tasks") tasksLoaded = true
    property string selectedDate: service.month === Qt.formatDate(new Date(), "yyyy-MM")
        ? Qt.formatDate(new Date(), "yyyy-MM-dd") : service.month + "-01"
    property string taskFilter: "Open"
    property string listFilter: ""
    property var editing: null
    property string editingKind: "VTODO"
    readonly property var snapshot: service.state
    readonly property var visibleTasks: snapshot.tasks.filter(task => {
        if (listFilter && task.list_slug !== listFilter) return false;
        if (search.text && ![task.summary, task.description, task.categories].join(" ").toLowerCase().includes(search.text.toLowerCase())) return false;
        if (taskFilter === "Completed") return task.completed;
        if (task.completed || task.status === "CANCELLED") return taskFilter === "All";
        if (taskFilter === "Today") return !!task.due && task.due <= Qt.formatDate(new Date(), "yyyy-MM-dd");
        if (taskFilter === "Upcoming") return !!task.due && task.due > Qt.formatDate(new Date(), "yyyy-MM-dd");
        if (taskFilter === "Important") return task.priority > 0 && task.priority <= 4;
        return true;
    })
    readonly property string agendaEnd: {
        const month = new Date(service.month + "-01T12:00:00");
        const now = new Date();
        return Qt.formatDate(service.month === Qt.formatDate(now, "yyyy-MM")
            ? new Date(now.getFullYear(), now.getMonth(), now.getDate() + 60)
            : new Date(month.getFullYear(), month.getMonth() + 1, 1), "yyyy-MM-dd");
    }
    readonly property var visibleEvents: snapshot.events.filter(event => event.last_date >= selectedDate && event.date < agendaEnd)
    readonly property bool sectionReady: (tab === "tasks" ? snapshot.tasksReady : snapshot.eventsReady) ?? snapshot.state === "ready"
    readonly property double syncedAt: tab === "tasks" ? snapshot.tasksUpdated || snapshot.updated || 0 : snapshot.updated || 0
    readonly property string syncStatus: syncedAt
        ? qsTr("Last synced %1").arg(Qt.formatDateTime(new Date(syncedAt * 1000), "d MMM, HH:mm")) : ""
    readonly property string contentStatus: {
        if (service.error) return [service.error, snapshot.stale ? syncStatus : ""].filter(Boolean).join(" · ");
        if (snapshot.state === "unconfigured") return qsTr("Configure Nextcloud in ~/.config/quickshell/desktop/integrations/nextcloud.json; select collections in calendar.json. See the shell README for setup.");
        if (snapshot.state === "needs_password") return qsTr("Save the Nextcloud app password in ~/.config/quickshell/desktop/integrations/nextcloud-app-password with mode 0600.");
        if (!sectionReady && (snapshot.error || snapshot.state === "unavailable")) return snapshot.error || (tab === "tasks" ? qsTr("Tasks unavailable.") : qsTr("Agenda unavailable."));
        if (!sectionReady) return tab === "tasks" ? qsTr("Loading tasks…") : qsTr("Loading agenda…");
        if (snapshot.stale) return [qsTr("Showing saved data"), syncStatus].filter(Boolean).join(" · ");
        if (snapshot.state === "ready" && !(tab === "tasks" ? visibleTasks.length : visibleEvents.length))
            return tab === "tasks" ? qsTr("No tasks in this view.") : qsTr("No events in this period.");
        return syncStatus;
    }
    initialFocus: search
    escapeHandler: editor.popupOpen ? (() => editor.closePopups())
        : taskView.popup.visible ? (() => taskView.popup.close())
        : taskList.popup.visible ? (() => taskList.popup.close())
        : editing ? (() => { editing = null; }) : null
    onActiveChanged: { service.active = active; if (!active) { editing = null; taskView.popup.close(); taskList.popup.close(); editor.closePopups(); } }
    Component.onDestruction: service.active = false
    Connections {
        target: root.service
        ignoreUnknownSignals: true
        function onSubmitted(request): void { if (request.op === "save" || request.op === "delete") root.editing = null; }
        function onWriteFailed(request): void {
            if (request.op === "save" && !root.editing && root.active && request.account_id === (root.snapshot.account_id || "")) root.edit(request.kind, request.entry);
        }
    }
    Component.onCompleted: if (service.failedDraft) edit(service.failedDraft.kind, service.failedDraft.entry)

    ListModel { id: eventRows; dynamicRoles: true }
    ListModel { id: taskRows; dynamicRoles: true }
    function rowKey(row: var, task: bool): string {
        const resource = row.href || row._localId || row.uid || row.summary;
        return resource + "#" + (task ? row.recurrence_id || (row.exception ? row.due || row.start_date : "") : row.start);
    }
    function reconcileRows(model: var, rows: var, task: bool): void {
        const keys = rows.map(row => rowKey(row, task));
        const wanted = new Set(keys);
        for (let index = model.count - 1; index >= 0; index--) {
            if (!wanted.has(model.get(index).key)) model.remove(index);
        }
        for (let index = 0; index < rows.length; index++) {
            const key = keys[index];
            let current = index;
            while (current < model.count && model.get(current).key !== key) current++;
            if (current === model.count) model.insert(index, {key, record: rows[index], signature: JSON.stringify(rows[index])});
            else {
                if (current !== index) model.move(current, index, 1);
                const signature = JSON.stringify(rows[index]);
                if (signature !== model.get(index).signature) {
                    model.setProperty(index, "record", rows[index]); model.setProperty(index, "signature", signature);
                }
            }
        }
    }
    onVisibleEventsChanged: reconcileRows(eventRows, visibleEvents, false)
    onVisibleTasksChanged: reconcileRows(taskRows, visibleTasks, true)

    function edit(kind: string, entry: var): void { editingKind = kind; editing = entry; }
    function monthStep(step: int): void {
        const date = new Date(service.month + "-01T12:00:00");
        const next = new Date(date.getFullYear(), date.getMonth() + step, 1);
        service.month = Qt.formatDate(next, "yyyy-MM"); selectedDate = service.month + "-01";
    }
    function yearStep(step: int): void { monthStep(step * 12); }
    function agendaDate(event: var): string { return event ? (event.date < selectedDate ? selectedDate : event.date) : ""; }
    function today(): void {
        selectedDate = Qt.formatDate(new Date(), "yyyy-MM-dd"); service.month = selectedDate.slice(0, 7);
    }
    function dayAt(index: int): string {
        const first = new Date(service.month + "-01T12:00:00");
        return Qt.formatDate(new Date(first.getFullYear(), first.getMonth(), index - (first.getDay() + 6) % 7 + 1), "yyyy-MM-dd");
    }
    headerActions: RowLayout {
        IconButton {
            iconName: "refresh-cw"; text: qsTr("Refresh calendar and tasks")
            enabled: root.active && !(root.service.refreshing ?? root.service.busy)
            onClicked: root.service.refresh(true)
        }
    }
    component Note: ShellText { color: Theme.muted; font.pixelSize: Theme.smallFontSize; wrapMode: Text.Wrap; Layout.fillWidth: true }
    component Heading: ShellText { font.weight: Font.DemiBold; Layout.fillWidth: true }

    component StatusLine: Item {
        id: line
        property string text: ""
        property color textColor: Theme.muted
        Layout.fillWidth: true
        implicitHeight: Math.ceil(metrics.height)
        Layout.minimumHeight: implicitHeight; Layout.maximumHeight: implicitHeight
        FontMetrics { id: metrics; font: label.font }
        ShellText {
            id: label
            anchors.fill: parent; verticalAlignment: Text.AlignVCenter
            text: line.text; color: line.textColor; font.pixelSize: Theme.smallFontSize
            elide: Text.ElideRight; maximumLineCount: 1
        }
        PassiveToolTip { target: line; text: line.text; maximumLineCount: 12 }
    }

    component CalendarButton: IconButton {
        implicitWidth: root.width < 340 ? 24 : 28
        padding: 6
    }

    ColumnLayout {
        anchors.fill: parent; spacing: Theme.gap
        RowLayout {
            visible: !root.editing; Layout.fillWidth: true
            Repeater {
                model: [{key: "calendar", title: qsTr("Calendar")}, {key: "tasks", title: qsTr("Tasks")}]
                ShellButton {
                    required property var modelData
                    Layout.fillWidth: true; Layout.preferredWidth: 1; Layout.minimumWidth: 0; text: modelData.title; checkable: true; checked: root.tab === modelData.key
                    onClicked: root.tab = modelData.key
                }
            }
        }
        ColumnLayout {
            visible: !!root.editing; Layout.fillWidth: true; Layout.fillHeight: true; spacing: Theme.gap
            ItemEditor {
                id: editor
                statusContent: StatusLine { objectName: "editorStatus"; text: root.service.error; textColor: Theme.danger }
                Layout.fillWidth: true; Layout.fillHeight: true
                service: root.service; active: root.active; kind: root.editingKind; entry: root.editing; selectedDate: root.selectedDate
                onCancelled: { root.service.dismissDraft?.(root.editing); root.editing = null; }
            }
        }
        DrawerColumn {
            visible: !root.editing; Layout.fillWidth: true; Layout.fillHeight: true
            RowLayout {
                objectName: "calendarNavigation"
                visible: root.tab === "calendar"; Layout.fillWidth: true; spacing: 2
                CalendarButton { objectName: "previousMonth"; iconName: "chevron-left"; text: qsTr("Previous month"); onClicked: root.monthStep(-1) }
                ShellText {
                    objectName: "calendarMonth"; text: Qt.formatDate(new Date(root.service.month + "-01T12:00:00"), "MMMM")
                    Layout.fillWidth: true; Layout.minimumWidth: 0; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                    font.pixelSize: root.width < 340 ? Theme.smallFontSize : Theme.fontSize
                }
                CalendarButton { objectName: "nextMonth"; iconName: "chevron-right"; text: qsTr("Next month"); onClicked: root.monthStep(1) }
                Item { Layout.fillWidth: true; Layout.minimumWidth: 4 }
                CalendarButton { objectName: "previousYear"; iconName: "chevron-left"; text: qsTr("Previous year"); onClicked: root.yearStep(-1) }
                ShellText {
                    objectName: "calendarYear"; text: root.service.month.slice(0, 4)
                    font.pixelSize: root.width < 340 ? Theme.smallFontSize : Theme.fontSize
                }
                CalendarButton { objectName: "nextYear"; iconName: "chevron-right"; text: qsTr("Next year"); onClicked: root.yearStep(1) }
                CalendarButton {
                    objectName: "calendarToday"; iconName: "calendar-days"; text: qsTr("Today")
                    background: Item {}
                    onClicked: root.today()
                }
            }
            GridLayout {
                visible: root.tab === "calendar"; Layout.fillWidth: true; columns: 7; uniformCellWidths: true; rowSpacing: 3; columnSpacing: 3
                Repeater {
                    model: [qsTr("M"), qsTr("T"), qsTr("W"), qsTr("T"), qsTr("F"), qsTr("S"), qsTr("S")]
                    Note { required property string modelData; text: modelData; horizontalAlignment: Text.AlignHCenter }
                }
                Repeater {
                    model: 42
                    Button {
                        id: day
                        required property int index
                        readonly property string date: root.dayAt(index)
                        readonly property bool hasEvents: root.snapshot.events.some(event => event.date <= date && event.last_date >= date)
                        objectName: "calendarDay:" + date
                        Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 1; implicitWidth: 32; implicitHeight: 38; padding: 0; hoverEnabled: true
                        Accessible.name: Qt.formatDate(new Date(date + "T12:00:00"), "dddd, d MMMM")
                        onClicked: { root.selectedDate = date; if (date.slice(0, 7) !== root.service.month) root.service.month = date.slice(0, 7); }
                        background: Rectangle {
                            radius: Theme.controlRadius
                            color: day.date === root.selectedDate ? Theme.accentSurface : day.hovered || day.visualFocus ? Theme.raised : "transparent"
                            border.width: day.date === Qt.formatDate(new Date(), "yyyy-MM-dd") ? 1 : 0; border.color: Theme.accent
                        }
                        contentItem: Column {
                            ShellText {
                                width: parent.width; text: Number(day.date.slice(-2)); horizontalAlignment: Text.AlignHCenter
                                color: day.date.slice(0, 7) === root.service.month ? Theme.text : Theme.muted
                            }
                            Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 4; height: 4; radius: 2; color: day.hasEvents ? Theme.accent : "transparent" }
                        }
                    }
                }
            }
            RowLayout {
                objectName: "agendaHeading"
                Layout.fillWidth: true
                Heading { text: root.tab === "tasks" ? qsTr("Tasks") : qsTr("Agenda") }
                IconButton {
                    objectName: "sectionAddItem"; iconName: "plus"; text: root.tab === "tasks" ? qsTr("New task") : qsTr("New event on selected day")
                    enabled: root.snapshot.calendars.some(row => row.writable && row.components.includes(root.tab === "tasks" ? "VTODO" : "VEVENT") && (root.tab === "tasks" ? row.tasks_enabled : row.events_enabled))
                    onClicked: root.edit(root.tab === "tasks" ? "VTODO" : "VEVENT", {})
                }
            }
            StatusLine {
                objectName: "sectionStatus"
                text: root.contentStatus
                textColor: root.service.error || root.snapshot.state === "unavailable" ? Theme.danger : Theme.muted
            }
            RowLayout {
                visible: root.tab === "tasks"; Layout.fillWidth: true
                ShellChoice {
                    id: taskView
                    Layout.fillWidth: true; model: ["Open", "Today", "Upcoming", "Important", "Completed", "All"]
                    Accessible.name: qsTr("Task view"); onActivated: root.taskFilter = currentText
                }
                ShellChoice {
                    id: taskList
                    Layout.fillWidth: true; textRole: "name"; valueRole: "slug"
                    model: [{name: qsTr("All lists"), slug: ""}].concat(root.snapshot.calendars.filter(row => row.tasks_enabled && row.components.includes("VTODO")))
                    Accessible.name: qsTr("Task list"); onActivated: root.listFilter = currentValue
                }
            }
            InputField { id: search; objectName: "taskSearch"; visible: root.tab === "tasks"; Layout.fillWidth: true; placeholderText: qsTr("Search tasks and tags") }
            Repeater {
                model: eventRows
                ColumnLayout {
                    id: eventGroup
                    visible: root.tab !== "tasks"
                    required property var record
                    readonly property var modelData: record
                    required property int index
                    Layout.fillWidth: true; spacing: 6
                    Note {
                        objectName: "agendaDate:" + root.agendaDate(eventGroup.modelData)
                        visible: eventGroup.index === 0 || root.agendaDate(root.visibleEvents[eventGroup.index - 1]) !== root.agendaDate(eventGroup.modelData)
                        text: Qt.formatDate(new Date(root.agendaDate(eventGroup.modelData) + "T12:00:00"), "dddd, d MMMM")
                    }
                    ItemDelegate {
                        id: eventRow
                        Layout.fillWidth: true; implicitHeight: Math.max(64, eventText.implicitHeight + 24); padding: 12
                        hoverEnabled: true
                        enabled: !eventGroup.modelData._pending && !eventGroup.modelData._needsSync
                        onClicked: root.edit("VEVENT", eventGroup.modelData)
                        background: ButtonBackground {
                            idleColor: Theme.surface
                            idleBorderColor: Theme.border
                            highlighted: eventRow.hovered || eventRow.visualFocus
                            pressed: eventRow.down
                        }
                        contentItem: ColumnLayout {
                            id: eventText; spacing: 4
                            ShellText { text: eventGroup.modelData.summary; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Note {
                                text: [eventGroup.modelData.all_day ? qsTr("All day") : Qt.formatTime(new Date(eventGroup.modelData.start), "HH:mm") + "–" + Qt.formatTime(new Date(eventGroup.modelData.end), "HH:mm"), eventGroup.modelData.calendar, eventGroup.modelData.location].filter(Boolean).join(" · ")
                            }
                        }
                    }
                }
            }
            Repeater {
                model: root.tasksLoaded ? taskRows : null
                Surface {
                    id: taskRow
                    visible: root.tab === "tasks"
                    required property var record
                    readonly property var modelData: record
                    objectName: "taskRow:" + modelData.uid
                    Layout.fillWidth: true; implicitHeight: Math.max(64, taskContent.implicitHeight + 16); radius: Theme.controlRadius; color: Theme.surface; border.width: 0
                    HoverHandler { id: taskHover; enabled: root.active }
                    ButtonBackground {
                        objectName: "taskBackground:" + taskRow.modelData.uid
                        anchors.fill: parent
                        idleColor: Theme.surface
                        idleBorderColor: Theme.border
                        highlighted: root.active && (taskHover.hovered || completion.visualFocus || taskButton.visualFocus)
                        pressed: completion.down || taskButton.down
                    }
                    RowLayout {
                        id: taskContent; anchors.fill: parent; anchors.margins: 8; spacing: 4
                        CheckBox {
                            id: completion
                            objectName: "taskComplete:" + taskRow.modelData.uid
                            implicitWidth: 34; implicitHeight: 34
                            hoverEnabled: true
                            background: Item {}
                            indicator: Rectangle {
                                anchors.centerIn: parent; width: 18; height: 18; radius: 4
                                color: completion.checked ? Theme.accent : "transparent"
                                border.width: 1; border.color: completion.hovered || completion.visualFocus ? Theme.accent : Theme.muted
                                opacity: completion.enabled ? 1 : 0.4
                                Icon { anchors.centerIn: parent; width: 14; height: 14; name: "check"; visible: completion.checked; color: Theme.accentText }
                            }
                            contentItem: Item {}
                            checked: taskRow.modelData.completed
                            enabled: taskRow.modelData.actionable && !taskRow.modelData._pending && !taskRow.modelData._needsSync
                            Accessible.name: (checked ? qsTr("Reopen %1") : qsTr("Complete %1")).arg(taskRow.modelData.summary)
                            onClicked: root.service.mutate("complete", "VTODO", Object.assign({}, taskRow.modelData, {collection: taskRow.modelData.list_slug}), !taskRow.modelData.completed)
                        }
                        ItemDelegate {
                            id: taskButton
                            objectName: "taskEdit:" + taskRow.modelData.uid
                            Layout.fillWidth: true; implicitHeight: taskText.implicitHeight + 12; padding: 6
                            hoverEnabled: true
                            enabled: !taskRow.modelData._pending && !taskRow.modelData._needsSync
                            onClicked: root.edit("VTODO", taskRow.modelData)
                            background: Item {}
                            contentItem: ColumnLayout {
                                id: taskText; spacing: 3
                                ShellText {
                                    text: (taskRow.modelData.parent ? "↳ " : "") + taskRow.modelData.summary
                                    Layout.fillWidth: true; wrapMode: Text.Wrap; font.strikeout: taskRow.modelData.completed
                                }
                                Note {
                                    text: [taskRow.modelData.due ? qsTr("Due %1").arg(taskRow.modelData.due + (taskRow.modelData.due_time ? " " + taskRow.modelData.due_time : "")) : qsTr("No due date"), taskRow.modelData.list, taskRow.modelData.recurring ? qsTr("Repeats") : "", taskRow.modelData.percent ? taskRow.modelData.percent + "%" : "", taskRow.modelData.priority ? qsTr("Priority %1").arg(taskRow.modelData.priority) : "", taskRow.modelData.categories].filter(Boolean).join(" · ")
                                    color: !taskRow.modelData.completed && taskRow.modelData.due && taskRow.modelData.due < Qt.formatDate(new Date(), "yyyy-MM-dd") ? Theme.warning : Theme.muted
                                }
                                Note { visible: !!taskRow.modelData.parent; text: qsTr("Subtask of %1").arg(root.snapshot.tasks.find(row => row.uid === taskRow.modelData.parent)?.summary || qsTr("another task")) }
                                Note { visible: !!taskRow.modelData.start_date; text: qsTr("Starts %1").arg(taskRow.modelData.start_date + (taskRow.modelData.start_time ? " " + taskRow.modelData.start_time : "")) }
                            }
                        }
                    }
                }
            }
        }
    }
}
