"""Native media-tools client for the socket-owned desktop speech service."""

import json
import os
from pathlib import Path
import uuid

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TranscriptionPanel(QWidget):
    busyChanged = Signal(bool)

    def __init__(self, source, video=False, parent=None):
        super().__init__(parent)
        self.source = source
        self.state = {}
        self.job_id = ''
        self.pending = []
        self.buffer = b''
        self.busy = False
        self.initialized = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        row = QHBoxLayout()
        self.models = QComboBox()
        self.models.setAccessibleName('Transcription model')
        self.models.setToolTip(
            'Larger models need more memory and processing time. Missing models download on first use.'
        )
        row.addWidget(self.models, 1)
        self.languages = QComboBox()
        self.languages.setAccessibleName('Spoken language')
        self.languages.setToolTip(
            'Spoken language; transcription preserves the original language.'
        )
        row.addWidget(self.languages, 1)
        layout.addLayout(row)
        self.models.currentIndexChanged.connect(self.model_changed)
        self.output = QComboBox()
        self.output.addItem('Plain text', 'clipboard')
        if video:
            self.output.addItem('Subtitles (.srt)', 'srt')
        self.output.setVisible(video)
        self.output.setAccessibleName('Transcription output')
        self.output.setToolTip(
            'Plain text is copied to the clipboard. '
            'Subtitles are saved beside the video with the same filename (.srt). Existing files are kept.'
        )
        layout.addWidget(self.output)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.message)
        layout.addStretch()
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel = QPushButton('Cancel')
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.cancel_job)
        row.addWidget(self.cancel)
        self.start = QPushButton('Transcribe')
        self.start.setEnabled(False)
        self.start.setToolTip(
            'Runs locally in the background, including after closing this window.'
        )
        self.start.clicked.connect(self.transcribe)
        row.addWidget(self.start)
        layout.addLayout(row)
        self.socket = QLocalSocket(self)
        self.socket.connected.connect(lambda: self.send({'op': 'status'}))
        self.socket.readyRead.connect(self.read)
        self.socket.errorOccurred.connect(self.unavailable)
        self.socket.disconnected.connect(self.unavailable)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(5000)
        self.timeout.timeout.connect(self.unavailable)

    def showEvent(self, event):
        super().showEvent(event)
        if self.socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self.connect_service()

    def connect_service(self):
        runtime = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        self.message.setText('Connecting…')
        self.buffer = b''
        self.timeout.start()
        self.socket.connectToServer(str(Path(runtime) / 'desktop-capture/control.sock'))

    def unavailable(self, *_):
        self.timeout.stop()
        self.socket.abort()
        self.pending.clear()
        self.start.setEnabled(False)
        self.message.setText(
            'Transcription service unavailable. Check desktop-capture.socket, then reopen this tab.'
        )
        # The service owns the job; losing the window/connection must not cancel it.
        self.set_busy(False)

    def send(self, request):
        self.pending.append(request)
        self.socket.write((json.dumps(request) + '\n').encode())
        self.socket.flush()
        self.timeout.start()

    def read(self):
        self.buffer += bytes(self.socket.readAll())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                packet = json.loads(line)
            except (ValueError, TypeError):
                self.unavailable()
                continue
            request = (
                self.pending.pop(0) if packet.get('reply') and self.pending else {}
            )
            if request:
                self.timeout.stop()
            self.state = packet.get('speech') or {}
            if not self.state:
                continue
            if 'srt' not in self.state.get('fileOutputs', []):
                self.timeout.stop()
                self.start.setEnabled(False)
                self.message.setText(
                    'Reboot to load the updated transcription service.'
                )
                continue
            if not self.initialized:
                self.initialize_options()
            if request.get('op') == 'speech-file' and (
                packet.get('requestError') or self.state.get('jobId') != self.job_id
            ):
                self.message.setText(
                    packet.get('requestError')
                    or self.state.get('error')
                    or 'Another speech job is running.'
                )
                self.job_id = ''
                self.set_busy(False)
            else:
                self.update_state()
            self.start.setEnabled(not self.busy and self.state.get('phase') == 'idle')

    def initialize_options(self):
        self.initialized = True
        options = self.state.get('options', {})
        for model in self.state.get('models', []):
            self.models.addItem(
                model['name']
                + ' · '
                + model['size']
                + (' ✓' if model['installed'] else ''),
                model['id'],
            )
        self.models.setCurrentIndex(max(0, self.models.findData(options.get('model'))))
        self.model_changed()
        self.languages.setCurrentIndex(
            max(0, self.languages.findData(options.get('language')))
        )
        self.message.clear()

    def model_changed(self, *_):
        language = self.languages.currentData()
        self.languages.clear()
        # Filter the complete engine catalogue to the chosen checkpoint.
        for item in self.state.get(
            'allLanguages',
            self.state.get('languages', [{'code': 'auto', 'name': 'Auto-detect'}]),
        ):
            if item['code'] == 'yue' and self.models.currentData() not in (
                'large-v3',
                'large-v3-turbo',
            ):
                continue
            self.languages.addItem(item['name'], item['code'])
        self.languages.setCurrentIndex(max(0, self.languages.findData(language)))

    def set_busy(self, value):
        if self.busy != value:
            self.busy = value
            self.busyChanged.emit(value)
        for control in (self.models, self.languages, self.output):
            control.setEnabled(not value)
        self.cancel.setEnabled(value)
        self.progress.setVisible(value)

    def update_state(self):
        state = self.state
        source = str(Path(self.source()).resolve())
        if state.get('source') == source and state.get('phase') != 'idle':
            self.job_id = state['jobId']
        if not self.job_id or state.get('jobId') != self.job_id:
            return
        active = state.get('phase') != 'idle'
        self.set_busy(active)
        if active:
            progress = (
                state.get('progress', -1) if state['phase'] == 'preparing' else -1
            )
            self.progress.setRange(0, 100 if progress >= 0 else 0)
            if progress >= 0:
                self.progress.setValue(int(progress))
            self.message.setText(
                {
                    'preparing': 'Downloading speech model…',
                    'converting': 'Reading audio…',
                    'transcribing': 'Transcribing locally…',
                    'delivering': 'Copying transcript…',
                }.get(state['phase'], 'Working…')
            )
        else:
            result = state.get('result', {})
            self.message.setText(
                result.get('error')
                or result.get('path')
                or result.get('message')
                or state.get('message', '')
            )
            self.job_id = ''

    def transcribe(self):
        if self.busy:
            return
        self.job_id = uuid.uuid4().hex
        self.set_busy(True)
        self.start.setEnabled(False)
        self.send(
            dict(
                op='speech-file',
                path=str(Path(self.source()).resolve()),
                output=self.output.currentData(),
                model=self.models.currentData(),
                language=self.languages.currentData(),
                jobId=self.job_id,
            )
        )

    def cancel_job(self):
        if self.busy and self.job_id:
            self.send(dict(op='speech-cancel', jobId=self.job_id))
