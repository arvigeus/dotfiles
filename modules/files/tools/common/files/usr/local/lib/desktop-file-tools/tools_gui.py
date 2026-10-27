"""Shared PySide6 shell for PDF, Image, File and Encryption tools."""

import argparse
import importlib
import json
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QImageReader
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

APPS = {
    'pdf': ('PDF tools', 'application-pdf', 'pdf_tasks', 'PDF (*.pdf)'),
    'file': ('File tools', 'system-file-manager', 'file_tasks', 'All files (*)'),
    'encryption': (
        'Encryption tools',
        'document-encrypt',
        'encryption_tasks',
        'All files (*)',
    ),
}


class ToolsDialog(QDialog):
    def __init__(self, kind, paths=(), load_keys=True):
        super().__init__()
        self.kind = kind
        title, icon, module, self.file_filter = APPS[kind]
        self.module = importlib.import_module(module)
        self.pages = []
        self.active = False
        self.preview_plan = None
        self.keys = []
        self.key_widgets = []
        self.errors = 0
        self.closing = False
        self.buffer = ''
        self.mode = ''
        self.applying = None
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon.fromTheme(icon))
        self.resize(1060, 800)
        self.setMinimumSize(800, 620)
        self.build_ui(title, icon)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_error)
        self.process.finished.connect(self.worker_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.append_paths(paths)
        self.action_changed()
        if kind == 'encryption' and load_keys:
            QTimer.singleShot(0, lambda: self.start_worker('keys', {}, []))

    def build_ui(self, title, icon):
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        heading = QLabel(title)
        font = heading.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        heading.setFont(font)
        header.addWidget(heading)
        header.addStretch()
        self.add = QPushButton(QIcon.fromTheme('list-add'), 'Add files…')
        self.add.clicked.connect(self.add_files)
        header.addWidget(self.add)
        self.add_folder = QPushButton(QIcon.fromTheme('folder-open'), 'Add folder…')
        self.add_folder.clicked.connect(self.add_directory)
        header.addWidget(self.add_folder)
        layout.addLayout(header)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.files = QListWidget()
        self.files.setMinimumWidth(220)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.files.itemSelectionChanged.connect(self.invalidate_preview)
        self.files.model().rowsMoved.connect(self.invalidate_preview)
        left_layout.addWidget(self.files)
        remove = QPushButton(QIcon.fromTheme('list-remove'), 'Remove selected')
        remove.clicked.connect(self.remove_selected)
        left_layout.addWidget(remove)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)
        groups = {}
        for spec in self.module.ACTIONS:
            groups.setdefault(spec['group'], []).append(spec)
        for group, specs in groups.items():
            page = QWidget()
            page_layout = QVBoxLayout(page)
            combo = QComboBox()
            for spec in specs:
                combo.addItem(spec['title'], spec)
            page_layout.addWidget(combo)
            description = QLabel()
            description.setWordWrap(True)
            page_layout.addWidget(description)
            form = QFormLayout()
            page_layout.addLayout(form)
            page_layout.addStretch()
            state = dict(
                combo=combo,
                form=form,
                description=description,
                controls={},
                cache={},
                previous=None,
            )
            self.pages.append(state)
            self.tabs.addTab(page, group)
            combo.currentIndexChanged.connect(
                lambda _index, state=state: self.render_options(state)
            )
            self.render_options(state)
        self.tabs.currentChanged.connect(self.action_changed)
        output = QHBoxLayout()
        self.output_label = QLabel('Output folder')
        output.addWidget(self.output_label)
        self.output = QLineEdit()
        self.output.setPlaceholderText('Beside each source file')
        self.output.textChanged.connect(self.invalidate_preview)
        output.addWidget(self.output, 1)
        self.output_choose = QPushButton('Choose…')
        self.output_choose.clicked.connect(self.choose_output)
        output.addWidget(self.output_choose)
        right_layout.addLayout(output)
        actions = QHBoxLayout()
        self.apply = QPushButton('Apply rename')
        self.apply.clicked.connect(self.apply_rename)
        actions.addWidget(self.apply)
        actions.addStretch()
        self.run_button = QPushButton(QIcon.fromTheme('media-playback-start'), 'Run')
        self.run_button.clicked.connect(self.run_action)
        actions.addWidget(self.run_button)
        right_layout.addLayout(actions)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(['File / item', 'Result', 'Details'])
        self.results.setRootIsDecorated(False)
        self.results.setColumnWidth(0, 210)
        self.results.setColumnWidth(1, 150)
        self.results.itemDoubleClicked.connect(self.open_result)
        right_layout.addWidget(self.results, 1)
        result_actions = QHBoxLayout()
        for label, callback in [
            ('Open', self.open_result),
            ('Open folder', self.reveal_result),
            ('Copy results', self.copy_results),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            result_actions.addWidget(button)
        result_actions.addStretch()
        right_layout.addLayout(result_actions)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        self.status = QLabel('Ready')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setValue(0)
        footer.addWidget(self.progress, 1)
        self.cancel = QPushButton('Cancel')
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_work)
        footer.addWidget(self.cancel)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.hide()
        layout.addWidget(self.log)

    def append_paths(self, paths):
        known = {
            self.files.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.files.count())
        }
        for value in paths:
            path = Path(value).absolute()
            if not path.exists() and not path.is_symlink():
                continue
            if str(path) in known:
                continue
            item = QListWidgetItem(
                QIcon.fromTheme('folder' if path.is_dir() else APPS[self.kind][1]),
                path.name,
            )
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.files.addItem(item)
            known.add(str(path))
        self.files.selectAll()
        self.invalidate_preview()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            'Add files',
            '',
            self.file_filter + ';;All files (*)'
            if self.kind == 'pdf'
            else self.file_filter,
        )
        self.append_paths(paths)

    def add_directory(self):
        path = QFileDialog.getExistingDirectory(self, 'Add folder')
        if path:
            self.append_paths([path])

    def remove_selected(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))
        self.invalidate_preview()

    def selected(self):
        return [
            self.files.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.files.count())
            if self.files.item(i).isSelected()
        ]

    def current_action(self):
        return self.pages[self.tabs.currentIndex()]['combo'].currentData()

    def options(self, state=None):
        state = state or self.pages[self.tabs.currentIndex()]
        return {name: widget.tool_value() for name, widget in state['controls'].items()}

    def render_options(self, state):
        if state['previous'] is not None:
            state['cache'][state['previous']] = self.options(state)
        while state['form'].rowCount():
            state['form'].removeRow(0)
        state['controls'] = {}
        spec = state['combo'].currentData()
        state['previous'] = spec['id']
        state['description'].setTextFormat(Qt.TextFormat.PlainText)
        state['description'].setText(spec['description'])
        values = state['cache'].get(spec['id'], {})
        for field in spec['fields']:
            value = values.get(field['name'], field['default'])
            kind = field['kind']
            if kind == 'choice':
                widget = QComboBox()
                for label, data in field['choices']:
                    widget.addItem(label, data)
                widget.setCurrentIndex(max(0, widget.findData(value)))
                widget.tool_value = widget.currentData
                widget.currentIndexChanged.connect(self.invalidate_preview)
            elif kind == 'boolean':
                widget = QCheckBox()
                widget.setChecked(bool(value))
                widget.tool_value = widget.isChecked
                widget.toggled.connect(self.invalidate_preview)
            elif kind in ('number', 'pixels', 'quality'):
                widget = QSpinBox()
                widget.setRange(
                    1 if kind == 'quality' else 0, 16384 if kind == 'pixels' else 100
                )
                if kind == 'pixels':
                    widget.setSpecialValueText('Auto')
                widget.setValue(int(value))
                widget.tool_value = widget.value
                widget.valueChanged.connect(self.invalidate_preview)
            elif kind in ('public-keys', 'secret-key'):
                widget = QListWidget() if kind == 'public-keys' else QComboBox()
                if kind == 'public-keys':
                    widget.setMaximumHeight(130)
                    widget.itemChanged.connect(self.invalidate_preview)
                    widget.tool_value = lambda widget=widget: [
                        widget.item(i).data(Qt.ItemDataRole.UserRole)
                        for i in range(widget.count())
                        if widget.item(i).checkState() == Qt.CheckState.Checked
                    ]
                else:
                    widget.tool_value = widget.currentData
                    widget.currentIndexChanged.connect(self.invalidate_preview)
                widget.tool_key_kind = kind
                self.populate_key_widget(widget, value)
                self.key_widgets.append(widget)
            else:
                edit = QLineEdit(str(value))
                edit.textChanged.connect(self.invalidate_preview)
                if kind == 'password':
                    edit.setEchoMode(QLineEdit.EchoMode.Password)
                widget = edit
                widget.tool_value = edit.text
                if kind in ('file', 'folder'):
                    widget = QWidget()
                    line = QHBoxLayout(widget)
                    line.setContentsMargins(0, 0, 0, 0)
                    line.addWidget(edit, 1)
                    browse = QPushButton('Choose…')
                    line.addWidget(browse)
                    browse.clicked.connect(
                        lambda _checked=False, edit=edit, kind=kind: self.browse_field(
                            edit, kind
                        )
                    )
                    widget.tool_value = edit.text
            widget.setObjectName('option_' + field['name'])
            state['form'].addRow(field['title'], widget)
            state['controls'][field['name']] = widget
        self.invalidate_preview()
        if hasattr(self, 'run_button'):
            self.action_changed()

    def populate_key_widget(self, widget, value):
        kind = widget.tool_key_kind
        widget.blockSignals(True)
        widget.clear()
        if kind == 'secret-key':
            widget.addItem('Select signing identity', '')
        for key in self.keys:
            if kind == 'secret-key' and (
                not key['secret'] or 's' not in key['capabilities'].lower()
            ):
                continue
            if kind == 'public-keys' and 'e' not in key['capabilities'].lower():
                continue
            title = (
                (key['name'] or key['fingerprint']) + ' · ' + key['fingerprint'][-16:]
            )
            if kind == 'secret-key':
                widget.addItem(title, key['fingerprint'])
            else:
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, key['fingerprint'])
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if key['fingerprint'] in (value or [])
                    else Qt.CheckState.Unchecked
                )
                widget.addItem(item)
        if kind == 'secret-key':
            widget.setCurrentIndex(max(0, widget.findData(value)))
        widget.blockSignals(False)

    def browse_field(self, edit, kind):
        value = (
            QFileDialog.getExistingDirectory(self, 'Choose folder', edit.text())
            if kind == 'folder'
            else QFileDialog.getOpenFileName(self, 'Choose file', edit.text())[0]
        )
        if value:
            edit.setText(value)

    def choose_output(self):
        value = QFileDialog.getExistingDirectory(
            self, 'Output folder', self.output.text()
        )
        if value:
            self.output.setText(value)

    def invalidate_preview(self, *_args):
        self.preview_plan = None
        if hasattr(self, 'apply'):
            self.update_controls()

    def action_changed(self, *_args):
        self.preview_plan = None
        self.update_controls()

    def update_controls(self):
        spec = self.current_action()
        has_paths = bool(self.selected())
        self.run_button.setText('Preview rename' if spec['preview'] else spec['title'])
        self.run_button.setEnabled(not self.active and has_paths)
        self.apply.setVisible(spec['preview'])
        self.apply.setEnabled(not self.active and bool(self.preview_plan))
        for widget in (self.output, self.output_label, self.output_choose):
            widget.setVisible(spec['output'])
        for widget in (
            self.files,
            self.tabs,
            self.add,
            self.add_folder,
            self.output,
            self.output_choose,
        ):
            widget.setEnabled(not self.active)
        self.cancel.setEnabled(self.active)

    def run_action(self):
        spec = self.current_action()
        paths = self.selected()
        if len(paths) < spec['minimum'] and not any(
            Path(path).is_dir() for path in paths
        ):
            self.status.setText(f'Select at least {spec["minimum"]} items.')
            return
        if spec['id'] == 'clipboard':
            self.copy_contents(paths)
            return
        options = self.options()
        if spec['output']:
            options['output'] = self.output.text().strip()
        self.applying = None
        self.start_worker(spec['id'], options, paths)

    def apply_rename(self):
        if self.preview_plan:
            self.applying = list(self.preview_plan)
            self.start_worker(
                'rename', self.options(), self.selected(), plan=self.applying
            )

    def start_worker(self, action, options, paths, plan=None):
        if self.active:
            return
        self.active = True
        self.mode = action
        self.buffer = ''
        self.errors = 0
        self.preview_plan = None
        self.results.clear()
        self.log.clear()
        self.log.hide()
        self.status.setText('Reading keys…' if action == 'keys' else 'Working…')
        self.progress.setRange(0, 0)
        self.update_controls()
        self.process.start(
            sys.executable, [str(Path(__file__).with_name('tool_worker.py'))]
        )
        self.process.write(
            json.dumps(
                dict(
                    app=self.kind,
                    action=action,
                    paths=paths,
                    options=options,
                    plan=plan,
                )
            ).encode()
        )
        self.process.closeWriteChannel()

    def read_output(self):
        self.buffer += bytes(self.process.readAllStandardOutput()).decode(
            errors='replace'
        )
        lines = self.buffer.split('\n')
        self.buffer = lines.pop()
        for line in lines:
            if not line:
                continue
            try:
                self.handle_event(json.loads(line))
            except (ValueError, KeyError, TypeError) as error:
                self.errors += 1
                self.status.setText('Could not read worker result: ' + str(error))

    def handle_event(self, event):
        kind = event['type']
        if kind == 'row':
            item = QTreeWidgetItem(
                [event['path'], event['status'], event.get('detail', '')]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, event['path'])
            self.results.addTopLevelItem(item)
            if event.get('error'):
                self.errors += 1
        elif kind == 'progress':
            self.progress.setRange(0, max(1, event['total']))
            self.progress.setValue(event['current'])
            self.status.setText(event.get('name') or 'Finishing…')
        elif kind == 'preview':
            self.preview_plan = event['plan']
        elif kind == 'keys':
            self.keys = event['keys']
            self.key_widgets = []
            for state in self.pages:
                for widget in state['controls'].values():
                    if hasattr(widget, 'tool_key_kind'):
                        self.populate_key_widget(widget, widget.tool_value())
                        self.key_widgets.append(widget)
        elif kind == 'log':
            self.log.show()
            self.log.appendPlainText(event['message'])
        elif kind == 'error':
            self.errors += 1
            self.log.show()
            self.log.appendPlainText(event['message'])
            self.status.setText(event['message'])
        elif kind == 'cancelled':
            self.status.setText('Cancelled; completed outputs are kept.')
        elif kind == 'done':
            self.errors = max(self.errors, event.get('failures', 0))
            self.status.setText(
                f'Finished · {self.errors} failed'
                if self.errors
                else (
                    'Keys loaded'
                    if self.mode == 'keys'
                    else (
                        'Review the proposed names, then apply.'
                        if self.preview_plan
                        else (
                            'No names need changing.'
                            if self.preview_plan == []
                            else 'Finished'
                        )
                    )
                )
            )

    def read_error(self):
        text = (
            bytes(self.process.readAllStandardError()).decode(errors='replace').strip()
        )
        if text:
            self.log.show()
            self.log.appendPlainText(text[-8000:])

    def worker_finished(self, code, _status):
        self.read_output()
        self.read_error()
        self.active = False
        self.progress.setRange(0, 100)
        self.progress.setValue(0 if code or self.errors else 100)
        if self.applying:
            for item in self.applying:
                for index in range(self.files.count()):
                    widget = self.files.item(index)
                    if (
                        widget.data(Qt.ItemDataRole.UserRole) == item['source']
                        and not Path(item['source']).exists()
                        and Path(item['target']).exists()
                    ):
                        widget.setData(Qt.ItemDataRole.UserRole, item['target'])
                        widget.setText(Path(item['target']).name)
            self.applying = None
        self.update_controls()
        if self.closing:
            self.close()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.active = False
            self.status.setText(self.process.errorString())
            self.update_controls()

    def cancel_work(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.status.setText('Stopping…')
            self.process.terminate()
            pid = self.process.processId()
            QTimer.singleShot(
                10000,
                lambda: (
                    self.process.kill()
                    if self.active and self.process.processId() == pid
                    else None
                ),
            )

    def open_result(self, *_args):
        item = self.results.currentItem()
        if item:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(item.data(0, Qt.ItemDataRole.UserRole))
            )

    def reveal_result(self):
        item = self.results.currentItem()
        if item:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(
                    str(Path(item.data(0, Qt.ItemDataRole.UserRole)).parent)
                )
            )

    def copy_results(self):
        rows = []
        for index in range(self.results.topLevelItemCount()):
            item = self.results.topLevelItem(index)
            rows.append(
                '\t'.join(
                    [item.data(0, Qt.ItemDataRole.UserRole), item.text(1), item.text(2)]
                )
            )
        QApplication.clipboard().setText('\n'.join(rows))

    def copy_contents(self, paths):
        try:
            if len(paths) == 1:
                reader = QImageReader(paths[0])
                size = reader.size()
                if size.isValid():
                    if size.width() * size.height() > 40_000_000:
                        raise ValueError('Choose an image smaller than 40 megapixels.')
                    image = reader.read()
                    if image.isNull():
                        raise ValueError('Could not read this image.')
                    QApplication.clipboard().setImage(image)
                    self.status.setText('Image copied.')
                    return
            if sum(Path(path).stat().st_size for path in paths) > 8 * 1024 * 1024:
                raise ValueError('Choose at most 8 MiB of text.')
            texts = [Path(path).read_text(encoding='utf-8') for path in paths]
            if any('\x00' in text for text in texts):
                raise ValueError('Select an image or UTF-8 text files.')
            QApplication.clipboard().setText('\n'.join(texts))
            self.status.setText('Text copied.')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))

    def closeEvent(self, event):
        if self.active:
            self.closing = True
            self.cancel_work()
            event.ignore()
            return
        event.accept()

    def reject(self):
        self.close()


def main(kind):
    parser = argparse.ArgumentParser(description=APPS[kind][0])
    parser.add_argument('files', nargs='*')
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APPS[kind][0])
    app.setDesktopFileName(kind + '-tools')
    if kind == 'pdf':
        from pdf_gui import PdfEditor

        window = PdfEditor(args.files)
    else:
        window = ToolsDialog(kind, args.files)
    window.show()
    return app.exec()
