"""A stateless Qt project overview and launcher for explicit project actions."""

import shlex
import shutil
import subprocess
from pathlib import Path

from project_inspector import TECH, inspect, local_file, sync_action
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class Result(QObject):
    ready = Signal(dict)
    failed = Signal(str)


class Inspector(QRunnable):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.result = Result()

    def run(self):
        try:
            self.result.ready.emit(inspect(self.path))
        except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
            self.result.failed.emit(f'Could not inspect this project: {error}')


class ProjectDialog(QDialog):
    def __init__(self, path, launch, auto_refresh=True):
        super().__init__()
        self.path = Path(path).resolve()
        self.launch = launch
        self.snapshot = None
        self.worker = None
        self.setWindowTitle('Project tools · ' + self.path.name)
        self.setWindowIcon(QIcon.fromTheme('applications-development'))
        self.resize(1040, 920)
        self.setMinimumSize(780, 650)
        self.setStyleSheet("""
            QFrame[card="true"] { border: 1px solid palette(mid); border-radius: 12px; background: palette(base); }
            QLabel[muted="true"] { color: palette(placeholder-text); }
            QPushButton { padding: 7px 12px; }
            QTreeWidget { border: none; background: transparent; }
            QTreeWidget::item { padding: 2px 4px; }
            QLineEdit { padding: 6px; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 16)
        top = QHBoxLayout()
        heading = QLabel('PROJECT TOOLS')
        heading.setProperty('muted', True)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        top.addWidget(heading)
        top.addStretch()
        self.refresh_button = self.button(
            'Refresh', 'view-refresh', self.refresh, 'refreshProject'
        )
        top.addWidget(self.refresh_button)
        layout.addLayout(top)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.content = QVBoxLayout(body)
        self.content.setContentsMargins(0, 0, 4, 0)
        self.content.setSpacing(14)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self.hero = self.card()
        hero_layout = QVBoxLayout(self.hero)
        identity = QHBoxLayout()
        identity.setSpacing(16)
        self.project_icon = QLabel()
        self.project_icon.setFixedSize(72, 72)
        self.project_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        identity.addWidget(self.project_icon)
        titles = QVBoxLayout()
        self.name = self.label(self.path.name)
        self.name.setObjectName('projectName')
        font = self.name.font()
        font.setPointSize(font.pointSize() + 9)
        font.setBold(True)
        self.name.setFont(font)
        self.description = self.label('Reading project information…', muted=True)
        self.description.setObjectName('projectDescription')
        titles.addWidget(self.name)
        titles.addWidget(self.description)
        identity.addLayout(titles, 1)
        self.version = self.label('', muted=True)
        identity.addWidget(self.version)
        hero_layout.addLayout(identity)
        path_row = QHBoxLayout()
        self.path_label = self.label(str(self.path), muted=True)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        path_row.addWidget(self.path_label, 1)
        path_row.addWidget(
            self.button(
                'Copy path',
                'edit-copy',
                lambda: QApplication.clipboard().setText(str(self.path)),
            )
        )
        hero_layout.addLayout(path_row)
        self.tech_layout = QGridLayout()
        self.tech_layout.setSpacing(8)
        hero_layout.addLayout(self.tech_layout)
        self.managers = self.label('', muted=True)
        hero_layout.addWidget(self.managers)
        shortcuts = QHBoxLayout()
        self.editor = self.button(
            'Open in Zed', 'zed', self.open_editor, 'openProjectEditor'
        )
        self.zed = shutil.which('zeditor') or shutil.which('zed')
        self.editor.setEnabled(self.zed is not None)
        if not self.editor.isEnabled():
            self.editor.setToolTip('Zed is unavailable.')
        shortcuts.addWidget(self.editor)
        shortcuts.addWidget(self.button('Open folder', 'folder-open', self.open_folder))
        shortcuts.addWidget(
            self.button(
                'Terminal',
                'utilities-terminal',
                lambda: self.launch('terminal', self.path),
            )
        )
        shortcuts.addStretch()
        hero_layout.addLayout(shortcuts)
        self.content.addWidget(self.hero)
        columns = QHBoxLayout()
        columns.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(14)
        columns.addLayout(left, 2)
        self.content.addLayout(columns, 1)
        self.git_card = self.card()
        git_layout = QVBoxLayout(self.git_card)
        git_layout.addWidget(self.section_title('Git', 'vcs-branch'))
        self.branch = self.label('Loading…')
        self.branch.setObjectName('projectBranch')
        font = self.branch.font()
        font.setBold(True)
        self.branch.setFont(font)
        git_layout.addWidget(self.branch)
        self.changes = self.label('')
        self.changes.setObjectName('projectChanges')
        git_layout.addWidget(self.changes)
        self.tracking = self.label('', muted=True)
        git_layout.addWidget(self.tracking)
        self.latest = self.label('', muted=True)
        git_layout.addWidget(self.latest)
        remote_row = QHBoxLayout()
        self.remote = self.label('', muted=True)
        remote_row.addWidget(self.remote, 1)
        self.remote_button = self.button(
            'Open remote', 'internet-web-browser', self.open_remote
        )
        remote_row.addWidget(self.remote_button)
        git_layout.addLayout(remote_row)
        git_actions = QHBoxLayout()
        self.sync_action = 'fetch'
        self.sync = self.button(
            'Fetch',
            'view-refresh',
            lambda: self.launch(self.sync_action, self.path),
            'syncProject',
        )
        self.commit = self.button(
            'Commit staged…',
            'document-save',
            lambda: self.launch('commit', self.path),
            'commitProject',
        )
        self.commit.setToolTip(
            'Native git commit uses your configured editor, signing and hooks. Stage changes in Zed first.'
        )
        git_actions.addWidget(self.sync)
        git_actions.addWidget(self.commit)
        git_layout.addLayout(git_actions)
        left.addWidget(self.git_card)
        self.mise_card = self.card()
        mise_layout = QVBoxLayout(self.mise_card)
        header = QHBoxLayout()
        header.addWidget(
            self.section_title('Tasks and tools', 'applications-development')
        )
        header.addStretch()
        self.config_button = self.button(
            'Open config', 'document-edit', self.open_config
        )
        header.addWidget(self.config_button)
        mise_layout.addLayout(header)
        self.mise_hint = self.label(
            'Tasks are grouped by their native runner.', muted=True
        )
        mise_layout.addWidget(self.mise_hint)
        self.tabs = QTabWidget()
        tasks_page = QWidget()
        task_layout = QVBoxLayout(tasks_page)
        task_layout.setContentsMargins(4, 8, 4, 4)
        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText('Filter tasks…')
        self.task_search.textChanged.connect(self.filter_tasks)
        task_layout.addWidget(self.task_search)
        self.task_list = QTreeWidget()
        self.task_list.setHeaderLabels(['Tool', 'Task', 'Description'])
        self.task_list.setRootIsDecorated(False)
        self.task_list.setObjectName('projectTasks')
        self.task_list.setMinimumHeight(120)
        self.task_list.itemDoubleClicked.connect(lambda *_: self.run_task())
        self.task_list.itemSelectionChanged.connect(self.update_run)
        task_layout.addWidget(self.task_list)
        self.task_arguments = QLineEdit()
        self.task_arguments.setPlaceholderText('Task arguments (optional)')
        self.task_arguments.setToolTip(
            'Arguments use shell-style quoting, but are passed directly without a shell.'
        )
        self.run_button = self.button(
            'Run selected task…',
            'media-playback-start',
            self.run_task,
            'runProjectTask',
        )
        self.run_button.setEnabled(False)
        task_controls = QHBoxLayout()
        task_controls.addWidget(self.task_arguments, 1)
        task_controls.addWidget(self.run_button)
        task_layout.addLayout(task_controls)
        self.tabs.addTab(tasks_page, 'Tasks')
        self.tool_list = QTreeWidget()
        self.tool_list.setHeaderLabels(['Tool', 'Declared version'])
        self.tool_list.setRootIsDecorated(False)
        self.tool_list.setObjectName('projectTools')
        self.tabs.addTab(self.tool_list, 'Mise tools')
        mise_layout.addWidget(self.tabs)
        actions = QHBoxLayout()
        self.install = self.button(
            'Install project tools…',
            'download',
            lambda: self.launch('install', self.path),
        )
        self.upgrade = self.button(
            'Upgrade project tools…',
            'view-refresh',
            lambda: self.launch('upgrade', self.path),
        )
        actions.addWidget(self.install)
        actions.addWidget(self.upgrade)
        actions.addStretch()
        mise_layout.addLayout(actions)
        columns.insertWidget(0, self.mise_card, 3)
        self.maintenance = self.card()
        maintenance_layout = QVBoxLayout(self.maintenance)
        maintenance_layout.addWidget(self.section_title('Maintenance', 'edit-clear'))
        maintenance_layout.addWidget(
            self.label(
                'Preview changes before removing build files or resetting the project.',
                muted=True,
            )
        )
        actions = QVBoxLayout()
        self.clean = self.button(
            'Clean ignored build files…',
            'edit-clear',
            lambda: self.launch('clean', self.path),
        )
        self.reset = self.button(
            'Reset and update from upstream…',
            'view-refresh',
            lambda: self.launch('reset', self.path),
        )
        self.reset.setToolTip(
            'Discards local changes after a preview and typing the project name.'
        )
        actions.addWidget(self.clean)
        actions.addWidget(self.reset)
        maintenance_layout.addLayout(actions)
        left.addWidget(self.maintenance)
        left.addStretch()
        footer = QHBoxLayout()
        self.status = self.label('Reading local project files…', muted=True)
        self.status.setObjectName('projectStatus')
        footer.addWidget(self.status, 1)
        footer.addWidget(self.button('Close', 'window-close', self.close))
        layout.addLayout(footer)
        self.hero.setEnabled(False)
        self.git_card.hide()
        self.mise_card.hide()
        self.maintenance.hide()
        if auto_refresh:
            self.refresh()

    @staticmethod
    def card():
        frame = QFrame()
        frame.setProperty('card', True)
        return frame

    @staticmethod
    def label(text, muted=False):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setProperty('muted', muted)
        return label

    @staticmethod
    def button(text, icon, callback, name=''):
        button = QPushButton(QIcon.fromTheme(icon), text)
        button.setObjectName(name)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def section_title(text, icon):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        symbol = QLabel()
        symbol.setPixmap(
            QIcon.fromTheme(icon, QIcon.fromTheme('applications-development')).pixmap(
                20, 20
            )
        )
        layout.addWidget(symbol)
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)
        layout.addStretch()
        return widget

    def refresh(self):
        if self.worker:
            return
        self.refresh_button.setEnabled(False)
        self.status.setText('Reading local project files…')
        self.worker = Inspector(self.path)
        self.worker.result.ready.connect(self.loaded)
        self.worker.result.failed.connect(self.failed)
        QThreadPool.globalInstance().start(self.worker)

    @Slot(str)
    def failed(self, message):
        self.worker = None
        self.refresh_button.setEnabled(True)
        self.hero.setEnabled(True)
        self.status.setText(message)

    @Slot(dict)
    def loaded(self, snapshot):
        self.worker = None
        self.snapshot = snapshot
        self.path = Path(snapshot['path'])
        self.refresh_button.setEnabled(True)
        self.hero.setEnabled(True)
        self.name.setText(snapshot['name'])
        self.setWindowTitle('Project tools · ' + snapshot['name'])
        self.description.setText(snapshot['description'] or 'Local project overview')
        self.version.setText('v' + snapshot['version'] if snapshot['version'] else '')
        self.path_label.setText(str(self.path))
        fallback = QIcon.fromTheme(
            snapshot['technologies'][0]['icon']
            if snapshot['technologies']
            else 'folder-development',
            QIcon.fromTheme('applications-development'),
        )
        icon = QIcon(snapshot['icon']) if snapshot['icon'] else fallback
        if icon.isNull():
            icon = fallback
        self.project_icon.setPixmap(icon.pixmap(64, 64))
        self.setWindowIcon(icon)
        self.show_languages(snapshot['languages'])
        self.managers.setText(
            'Lockfiles: ' + ' · '.join(snapshot['managers'])
            if snapshot['managers']
            else ''
        )
        state = snapshot['git']
        self.git_card.setVisible(bool(snapshot['git_root']))
        if state:
            self.branch.setText(state['branch'] or 'No commits yet')
            counts = [
                f'{state[key]} {title}'
                for key, title in [
                    ('staged', 'staged'),
                    ('modified', 'modified'),
                    ('untracked', 'untracked'),
                    ('conflicts', 'conflicts'),
                ]
                if state[key]
            ]
            self.changes.setText(
                ' · '.join([state['operation'], *counts]).strip(' ·')
                if state['operation'] or counts
                else 'Working tree clean'
            )
            self.tracking.setText(
                (
                    f'{state["upstream"]} · {state["ahead"]} ahead · {state["behind"]} behind'
                    ' · last fetched state'
                )
                if state['upstream']
                else 'No upstream configured'
            )
            self.latest.setText(
                'Latest commit: ' + state['latest']
                if state['latest']
                else 'No commits yet'
            )
            self.remote.setText(state['remote']['label'] or 'No remote configured')
            self.remote_button.setEnabled(bool(state['remote']['url']))
            ready = not state['conflicts'] and not state['operation']
            self.sync_action = sync_action(state)
            self.sync.setText(self.sync_action.capitalize())
            self.sync.setIcon(
                QIcon.fromTheme(
                    {'fetch': 'view-refresh', 'pull': 'download', 'push': 'go-up'}[
                        self.sync_action
                    ]
                )
            )
            self.sync.setEnabled(ready and bool(state['remote_name']))
            self.sync.setToolTip(
                'Branches have diverged. Fetch updates, then reconcile in Zed.'
                if state['ahead'] and state['behind']
                else 'Uses native Git in a terminal; pull is fast-forward-only and push never forces.'
            )
            self.commit.setEnabled(
                ready
                and state['staged'] > 0
                and not state['branch'].startswith('Detached')
            )
        elif snapshot['git_root']:
            self.branch.setText('Status unavailable')
            self.changes.setText('Refresh to try again.')
            self.tracking.clear()
            self.latest.clear()
            self.remote.clear()
            self.remote_button.setEnabled(False)
            self.sync.setEnabled(False)
            self.commit.setEnabled(False)
        mise = snapshot['mise']
        tasks = snapshot['tasks']
        has_mise = bool(mise['configs'])
        self.mise_card.setVisible(has_mise or bool(tasks))
        self.config_button.setVisible(has_mise)
        self.install.setVisible(has_mise)
        self.upgrade.setVisible(has_mise)
        self.tabs.setTabVisible(1, has_mise)
        self.task_list.clear()
        self.tool_list.clear()
        for task in tasks:
            description = task['description']
            if task['parameters']:
                description += ' · Arguments: ' + task['parameters']
            item = QTreeWidgetItem([task['tool'], task['name'], description])
            item.setData(0, Qt.ItemDataRole.UserRole, task)
            item.setToolTip(1, task['source'])
            item.setToolTip(2, description)
            self.task_list.addTopLevelItem(item)
        for tool in mise['tools']:
            self.tool_list.addTopLevelItem(
                QTreeWidgetItem([tool['name'], tool['version']])
            )
        self.task_list.resizeColumnToContents(0)
        self.task_list.resizeColumnToContents(1)
        self.tool_list.resizeColumnToContents(0)
        self.tabs.setTabText(0, f'Tasks · {len(tasks)}')
        self.tabs.setTabText(1, f'Mise tools · {len(mise["tools"])}')
        self.config_button.setEnabled(
            any(local_file(self.path, p) for p in mise['configs'])
        )
        self.filter_tasks(self.task_search.text())
        self.update_run()
        if not tasks and mise['tools']:
            self.tabs.setCurrentIndex(1)
        self.maintenance.setVisible(
            bool(snapshot['git_root']) and self.path not in (Path('/'), Path.home())
        )
        self.reset.setEnabled(
            bool(state and state['upstream'])
            and not state['conflicts']
            and not state['operation']
        )
        hint = (
            'Local snapshot · refresh after changes'
            if snapshot['git_root'] or mise['configs'] or tasks
            else 'No Git repository or local Mise configuration found'
        )
        status = ' · '.join(snapshot['errors']) or hint
        if snapshot['languages']['partial']:
            status += ' · Partial language scan'
        self.status.setText(status)

    def show_languages(self, report):
        while self.tech_layout.count():
            item = self.tech_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        languages = report['languages']
        by_name = {language['name']: language for language in languages}
        technologies = list(self.snapshot['technologies']) if self.snapshot else []
        aliases = {
            'C / C++': ('C', 'C++'),
            'C# / .NET': ('C#',),
            'Dart / Flutter': ('Dart',),
            'Qt / QML': ('QML',),
        }
        represented = {
            name
            for tech in technologies
            for name in aliases.get(tech['name'], (tech['name'],))
        }
        for language in languages:
            if language['name'] not in represented:
                technologies.append(
                    dict(
                        name=language['name'],
                        color=language['color'],
                        icon=TECH.get(language['name'], ('', 'text-x-generic'))[1],
                        evidence=[],
                    )
                )
        for index, tech in enumerate(technologies):
            matches = [
                by_name[name]
                for name in aliases.get(tech['name'], (tech['name'],))
                if name in by_name
            ]
            chip = QFrame()
            chip.setObjectName('tech_' + tech['name'])
            chip.setProperty('techBadge', True)
            chip.setStyleSheet(
                f'QFrame[techBadge="true"] {{ border-left: 3px solid {tech["color"]}; border-radius: 4px; background: palette(alternate-base); }}'
            )
            row = QHBoxLayout(chip)
            row.setContentsMargins(8, 4, 8, 4)
            row.setSpacing(6)
            symbol = QLabel()
            symbol.setPixmap(
                QIcon.fromTheme(
                    tech['icon'], QIcon.fromTheme('applications-development')
                ).pixmap(18, 18)
            )
            row.addWidget(symbol)
            row.addWidget(self.label(tech['name']))
            row.addStretch()
            if matches:
                percentage = self.label(
                    f'{sum(language["percentage"] for language in matches):.1f}%',
                    muted=True,
                )
                percentage.setObjectName('techPercentage')
                row.addWidget(percentage)
            self.tech_layout.addWidget(chip, index // 6, index % 6)

    def filter_tasks(self, text):
        for index in range(self.task_list.topLevelItemCount()):
            item = self.task_list.topLevelItem(index)
            item.setHidden(
                text.casefold()
                not in (' '.join(item.text(c) for c in range(3))).casefold()
            )
        self.update_run()

    def update_run(self):
        item = self.task_list.currentItem()
        self.run_button.setEnabled(item is not None and not item.isHidden())

    def run_task(self):
        item = self.task_list.currentItem()
        if item and not item.isHidden():
            try:
                arguments = shlex.split(self.task_arguments.text())
            except ValueError as error:
                QMessageBox.warning(self, 'Task arguments', str(error))
                return
            task = item.data(0, Qt.ItemDataRole.UserRole)
            self.launch('task', self.path, task['name'], task['runner'], arguments)

    def open_editor(self):
        subprocess.Popen(
            ['uwsm', 'app', '-t', 'service', '--', self.zed, str(self.path)]
        )

    def open_folder(self):
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))

    def open_remote(self):
        from PySide6.QtCore import QUrl

        if self.snapshot and self.snapshot['git']:
            url = self.snapshot['git']['remote']['url']
            if url:
                QDesktopServices.openUrl(QUrl(url))

    def open_config(self):
        from PySide6.QtCore import QUrl

        if not self.snapshot:
            return
        for relative in self.snapshot['mise']['configs']:
            path = local_file(self.path, relative)
            if path:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return
