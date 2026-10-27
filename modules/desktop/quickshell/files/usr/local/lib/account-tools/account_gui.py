"""Native profile editor with asynchronous account reads and writes."""

import json
from pathlib import Path
import sys
import tempfile

from PySide6.QtCore import QProcess, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AccountTools(QDialog):
    def __init__(self, auto_load=True):
        super().__init__()
        self.baseline = {}
        self.photo_path = ''
        self.photo_files = []
        self.mode = ''
        self.setWindowTitle('Account tools')
        self.setWindowIcon(QIcon.fromTheme('user-info'))
        self.resize(880, 680)
        self.setMinimumSize(720, 520)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.title = QLabel('My account')
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        font = self.title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        self.title.setFont(font)
        self.username = QLabel()
        titles.addWidget(self.title)
        titles.addWidget(self.username)
        header.addLayout(titles, 1)
        self.photo = QToolButton()
        self.photo.setFixedSize(88, 88)
        self.photo.setIconSize(QSize(80, 80))
        self.photo.setAccessibleName('Choose account photo')
        self.photo.setToolTip('Choose account photo')
        self.photo.clicked.connect(self.choose_photo)
        header.addWidget(self.photo)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        profile = QWidget()
        profile_layout = QVBoxLayout(profile)
        form = QFormLayout()
        self.fields = {}
        for key, title in [
            ('RealName', 'Full name'),
            ('Email', 'Email'),
            ('Location', 'Location'),
        ]:
            edit = QLineEdit()
            edit.setMaxLength(4096)
            edit.setObjectName(key)
            edit.textChanged.connect(self.update_actions)
            form.addRow(title, edit)
            self.fields[key] = edit
        profile_layout.addLayout(form)
        profile_layout.addStretch()
        self.tabs.addTab(profile, 'Profile')
        account = QWidget()
        account_layout = QHBoxLayout(account)
        self.details = QTreeWidget()
        self.details.setHeaderLabels(['Account', 'Value'])
        self.details.setRootIsDecorated(False)
        self.details.setColumnWidth(0, 160)
        account_layout.addWidget(self.details, 3)
        box = QGroupBox('Groups')
        group_layout = QVBoxLayout(box)
        self.groups = QTreeWidget()
        self.groups.setHeaderLabels(['Group', 'GID', 'Membership'])
        self.groups.setRootIsDecorated(False)
        group_layout.addWidget(self.groups)
        account_layout.addWidget(box, 2)
        self.tabs.addTab(account, 'Account information')
        self.status = QLabel('Reading account…')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.reload = QPushButton(QIcon.fromTheme('view-refresh'), 'Refresh')
        self.reload.clicked.connect(self.refresh)
        footer.addWidget(self.reload)
        self.discard = QPushButton('Discard edits')
        self.discard.clicked.connect(self.discard_edits)
        footer.addWidget(self.discard)
        footer.addStretch()
        self.save = QPushButton(QIcon.fromTheme('document-save'), 'Save profile')
        self.save.clicked.connect(self.save_profile)
        footer.addWidget(self.save)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.process = QProcess(self)
        self.process.finished.connect(self.request_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.update_actions()
        self.render_photo()
        if auto_load:
            QTimer.singleShot(0, self.refresh)

    def changes(self):
        values = {key: edit.text() for key, edit in self.fields.items()}
        values['IconFile'] = self.photo_path
        return {
            key: value
            for key, value in values.items()
            if value != self.baseline.get(key, '')
        }

    def update_actions(self):
        busy = bool(self.mode)
        dirty = bool(self.changes())
        self.save.setEnabled(
            not busy and bool(self.baseline) and self.available and dirty
        )
        self.discard.setEnabled(not busy and dirty)
        self.reload.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        for edit in self.fields.values():
            edit.setEnabled(not busy and self.available)
        self.photo.setEnabled(not busy and bool(self.baseline) and self.available)

    @property
    def available(self):
        return getattr(self, 'service_available', False)

    def start(self, mode, payload=None):
        self.mode = mode
        self.update_actions()
        self.status.setText('Saving profile…' if mode == 'save' else 'Reading account…')
        self.process.start(
            sys.executable,
            [str(Path(__file__).with_name('account_core.py'))]
            + (['--save'] if mode == 'save' else []),
        )
        if payload is not None:
            self.process.write(json.dumps(payload).encode())
            self.process.closeWriteChannel()

    def refresh(self):
        if self.mode:
            return
        if (
            self.changes()
            and QMessageBox.question(
                self, 'Discard edits?', 'Discard unsaved profile changes and refresh?'
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.start('load')

    def request_finished(self, code, _status):
        mode = self.mode
        if not mode:
            return
        self.mode = ''
        try:
            if code:
                raise ValueError(
                    bytes(self.process.readAllStandardError())
                    .decode(errors='replace')
                    .strip()
                    or 'Account helper failed.'
                )
            result = json.loads(bytes(self.process.readAllStandardOutput()))
            if mode == 'load':
                if 'fields' not in result:
                    raise ValueError(result.get('error', 'Could not read account.'))
                self.loaded(result)
            else:
                self.baseline.update(result.get('saved', {}))
                self.title.setText(self.baseline.get('RealName') or 'My account')
                self.title.setTextFormat(Qt.TextFormat.PlainText)
                self.status.setText(result.get('error') or 'Profile saved.')
        except (ValueError, TypeError, KeyError) as error:
            self.status.setText(str(error))
        self.update_actions()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.mode = ''
            self.status.setText(self.process.errorString())
            self.update_actions()

    def loaded(self, data):
        self.service_available = data['available']
        self.baseline = dict(data['fields'])
        self.username.setTextFormat(Qt.TextFormat.PlainText)
        self.username.setText('@' + data['username'])
        self.discard_edits()
        self.details.clear()
        self.groups.clear()
        rows = [
            ('Username', data['username']),
            ('User ID', data['uid']),
            ('Primary group ID', data['gid']),
            ('Home folder', data['home']),
            ('Login shell', data['shell']),
        ]
        props = data['details']
        for key, title, mapping in [
            ('AccountType', 'Account type', {0: 'Standard', 1: 'Administrator'}),
            ('LocalAccount', 'Local account', {True: 'Yes', False: 'No'}),
            ('Locked', 'Account locked', {True: 'Yes', False: 'No'}),
            ('AutomaticLogin', 'Automatic login', {True: 'Enabled', False: 'Disabled'}),
            (
                'PasswordMode',
                'Password',
                {0: 'Set', 1: 'Change required at next login', 2: 'No password'},
            ),
        ]:
            if key in props:
                rows.append((title, mapping.get(props[key], 'Unknown')))
        for key, value in rows:
            QTreeWidgetItem(self.details, [key, str(value)])
        for group in data['groups']:
            QTreeWidgetItem(
                self.groups,
                [
                    group['name'],
                    str(group['gid']),
                    'Primary' if group['primary'] else 'Supplementary',
                ],
            )
        self.status.setText(
            'Ready'
            if data['available']
            else 'Profile editing unavailable: ' + data['error']
        )
        self.update_actions()

    def discard_edits(self):
        self.title.setText(self.baseline.get('RealName') or 'My account')
        for key, edit in self.fields.items():
            edit.setText(self.baseline.get(key, ''))
        self.photo_path = self.baseline.get('IconFile', '')
        self.render_photo()
        self.update_actions()

    def render_photo(self):
        pixmap = QPixmap(self.photo_path) if self.photo_path else QPixmap()
        self.photo.setIcon(
            QIcon(pixmap)
            if not pixmap.isNull()
            else QIcon.fromTheme('avatar-default', QIcon.fromTheme('user-info'))
        )

    def choose_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose account photo', '', 'Images (*.png *.jpg *.jpeg *.webp)'
        )
        if not path:
            return
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 40_000_000:
            self.status.setText('Choose an image smaller than 40 megapixels.')
            return
        image = reader.read()
        if image.isNull():
            self.status.setText('Could not read this image.')
            return
        image = image.scaled(
            512,
            512,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        photo = tempfile.NamedTemporaryFile(prefix='account-photo-', suffix='.png')
        if not image.save(photo.name, 'PNG'):
            photo.close()
            self.status.setText('Could not prepare this photo.')
            return
        # AccountsService opens the normalized PNG as the calling user.
        self.photo_files.append(photo)
        self.photo_path = photo.name
        self.render_photo()
        self.update_actions()

    def save_profile(self):
        if self.mode or not self.available:
            return
        changes = self.changes()
        if changes:
            self.start('save', changes)

    def closeEvent(self, event):
        if self.mode == 'save':
            event.ignore()
            return
        if (
            self.changes()
            and QMessageBox.question(
                self, 'Discard edits?', 'Close without saving profile changes?'
            )
            != QMessageBox.StandardButton.Yes
        ):
            event.ignore()
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        for photo in self.photo_files:
            photo.close()
        event.accept()

    def reject(self):
        self.close()


def main():
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Account tools')
    app.setDesktopFileName('account-tools')
    window = AccountTools()
    window.show()
    return app.exec()
