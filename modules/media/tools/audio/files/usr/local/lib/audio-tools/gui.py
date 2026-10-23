"""Desktop audio tools with asynchronous, cancellable FFmpeg jobs."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from core import (
    ART_FORMATS,
    FIELDS,
    audio_info,
    conversion,
    probe_command,
    read_presets,
    tag_edit,
)
from PySide6.QtCore import QProcess, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
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
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'audio-tools/presets.json'


class AudioTools(QDialog):
    def __init__(self, paths, config=CONFIG):
        super().__init__()
        self.config = Path(config)
        self.info = {}
        self.drafts = {}
        self.artwork = {}
        self.current = None
        self.jobs = []
        self.operation = None
        self.cancelled = False
        self.active = False
        self.probe_path = None
        self.setWindowTitle('Audio tools')
        self.setWindowIcon(QIcon.fromTheme('audio-x-generic'))
        self.resize(1000, 740)
        self.setMinimumSize(760, 580)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel('Audio tools')
        font = title.font(); font.setPointSize(font.pointSize() + 6); font.setBold(True); title.setFont(font)
        header.addWidget(title); header.addStretch()
        self.add_button = QPushButton(QIcon.fromTheme('list-add'), 'Add files…')
        self.add_button.clicked.connect(self.add_files)
        header.addWidget(self.add_button)
        layout.addLayout(header)
        splitter = QSplitter()
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setMinimumWidth(230)
        self.files.currentItemChanged.connect(self.file_changed)
        self.files.itemSelectionChanged.connect(self.update_selection)
        splitter.addWidget(self.files)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.tags_tab(), 'Tags && artwork')
        self.tabs.addTab(self.convert_tab(), 'Convert')
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.tabs.addTab(self.details, 'File information')
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        self.selection = QLabel()
        layout.addWidget(self.selection)
        self.status = QLabel('Ready'); self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        row.addWidget(self.progress, 1)
        self.cancel = QPushButton('Cancel'); self.cancel.setEnabled(False); self.cancel.clicked.connect(self.cancel_jobs)
        row.addWidget(self.cancel)
        close = QPushButton('Close'); close.clicked.connect(self.close); row.addWidget(close)
        layout.addLayout(row)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(105); self.log.hide()
        layout.addWidget(self.log)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.job_progress)
        self.process.readyReadStandardError.connect(self.job_error)
        self.process.finished.connect(self.job_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.probe = QProcess(self)
        self.probe.finished.connect(self.probed)
        self.probe.errorOccurred.connect(self.probe_error)
        self.cover_process = QProcess(self)
        self.cover_process.finished.connect(self.cover_loaded)
        self.load_presets()
        self.append_files(paths)

    def tags_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.tag_hint = QLabel('Select a file to inspect its tags. Edits stay in the form until saved.')
        self.tag_hint.setWordWrap(True)
        heading = QHBoxLayout(); heading.addWidget(self.tag_hint, 1)
        self.cover = QToolButton(); self.cover.setFixedSize(96, 96); self.cover.setIconSize(QSize(88, 88))
        self.cover.setIcon(QIcon.fromTheme('image-x-generic')); self.cover.setEnabled(False)
        self.cover.setToolTip('Choose cover'); self.cover.setAccessibleName('Choose cover')
        self.cover.clicked.connect(self.choose_cover); heading.addWidget(self.cover)
        self.cover_remove = QToolButton(); self.cover_remove.setIcon(QIcon.fromTheme('edit-delete'))
        self.cover_remove.setEnabled(False)
        self.cover_remove.setToolTip('Remove cover'); self.cover_remove.setAccessibleName('Remove cover')
        self.cover_remove.clicked.connect(self.remove_cover); heading.addWidget(self.cover_remove)
        layout.addLayout(heading)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); form = QFormLayout(body)
        self.fields = {}
        for key, title in FIELDS.items():
            edit = QPlainTextEdit() if key == 'lyrics' else QLineEdit()
            if key == 'lyrics':
                edit.setMaximumHeight(85)
                edit.textChanged.connect(lambda key=key: self.field_edited(key))
            else:
                edit.textEdited.connect(lambda _text, key=key: self.field_edited(key))
            edit.setObjectName('tag_' + key)
            form.addRow(title, edit); self.fields[key] = edit
        scroll.setWidget(body); layout.addWidget(scroll, 1)
        self.batch = QCheckBox('Apply edited fields and cover changes to all selected files')
        layout.addWidget(self.batch)
        self.backup = QCheckBox('Keep a backup when saving tags'); self.backup.setChecked(True)
        layout.addWidget(self.backup)
        buttons = QHBoxLayout()
        self.revert = QPushButton('Discard edits'); self.revert.clicked.connect(self.discard_edits)
        self.save = QPushButton(QIcon.fromTheme('document-save'), 'Save tags'); self.save.clicked.connect(self.save_tags)
        buttons.addWidget(self.revert); buttons.addStretch(); buttons.addWidget(self.save)
        layout.addLayout(buttons)
        return page

    def convert_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        heading = QLabel('Convert selected files'); font = heading.font(); font.setBold(True); heading.setFont(font)
        layout.addWidget(heading)
        self.presets = QComboBox(); self.presets.currentIndexChanged.connect(self.preset_changed)
        layout.addWidget(self.presets)
        self.description = QLabel(); self.description.setWordWrap(True); layout.addWidget(self.description)
        form = QFormLayout()
        output = QHBoxLayout()
        self.output = QLineEdit(); self.output.setPlaceholderText('Beside each source file')
        browse = QPushButton('Choose…'); browse.clicked.connect(self.choose_output)
        output.addWidget(self.output, 1); output.addWidget(browse); form.addRow('Output folder', output)
        layout.addLayout(form)
        self.normalize = QCheckBox('Normalize loudness to −16 LUFS')
        self.normalize.setToolTip('One-pass EBU R128 loudness normalization; true peak −1.5 dB, loudness range 11 LU.')
        layout.addWidget(self.normalize)
        note = QLabel('Outputs use “filename [preset-id].extension”. Existing files are never overwritten.\n'
                      'The first audio track is converted. Tags and supported cover art are copied. Sources are kept.')
        note.setWordWrap(True); layout.addWidget(note)
        layout.addStretch()
        self.convert = QPushButton(QIcon.fromTheme('media-playback-start'), 'Convert selected files')
        self.convert.clicked.connect(self.start_conversion); layout.addWidget(self.convert)
        return page

    def append_files(self, paths):
        known = {self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())}
        for value in paths:
            path = Path(value).resolve()
            if not path.is_file() or path in known:
                continue
            item = QListWidgetItem(QIcon.fromTheme('audio-x-generic'), path.name)
            item.setToolTip(str(path)); item.setData(Qt.ItemDataRole.UserRole, path)
            self.files.addItem(item); known.add(path)
        if self.files.count() and self.files.currentRow() < 0:
            self.files.setCurrentRow(0)
        self.files.selectAll()
        self.update_selection()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add audio files', str(Path.home() / 'Music'),
                                               'Audio (*.mp3 *.flac *.m4a *.aac *.ogg *.opus *.wav *.aiff *.aif *.mka *.wma *.ape *.wv);;All files (*)')
        self.append_files(paths)

    def selected(self):
        return [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]

    def update_selection(self):
        self.selection.setText(f'{len(self.selected())} of {self.files.count()} files selected')

    def file_changed(self, item, _previous):
        self.stop_probe()
        self.current = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.render_tags()
        if self.current and self.current not in self.info:
            self.probe_path = self.current
            command = probe_command(self.current)
            self.probe.start(command[0], command[1:])

    def stop_probe(self):
        self.probe_path = None
        for process in (getattr(self, 'probe', None), getattr(self, 'cover_process', None)):
            if process and process.state() != QProcess.ProcessState.NotRunning:
                process.kill(); process.waitForFinished(1000)

    def probe_error(self, _error):
        if self.probe_path:
            self.status.setText('Could not inspect the file: ' + self.probe.errorString())

    def probed(self, code, _status):
        path = self.probe_path
        if not path:
            return
        self.probe_path = None
        try:
            if code:
                raise ValueError(bytes(self.probe.readAllStandardError()).decode(errors='replace').strip())
            self.info[path] = audio_info(bytes(self.probe.readAllStandardOutput()))
            if path == self.current:
                self.render_tags()
        except (ValueError, KeyError) as error:
            self.status.setText(f'Could not inspect {path.name}: {error}')

    def render_tags(self):
        if self.cover_process.state() != QProcess.ProcessState.NotRunning:
            self.cover_process.kill(); self.cover_process.waitForFinished(1000)
        info = self.info.get(self.current)
        draft = self.drafts.get(self.current, {})
        for key, edit in self.fields.items():
            value = draft.get(key, info['tags'].get(key, '') if info else '')
            edit.blockSignals(True)
            if isinstance(edit, QPlainTextEdit): edit.setPlainText(value)
            else: edit.setText(value)
            edit.blockSignals(False)
            edit.setEnabled(info is not None)
        self.tag_hint.setText(self.current.name if self.current else 'Add audio files to begin.')
        self.cover.setIcon(QIcon.fromTheme('image-x-generic')); self.cover.setText('')
        self.cover.setToolTip('Choose cover · No embedded artwork')
        self.cover.setEnabled(bool(info) and self.current.suffix.lower() in ART_FORMATS)
        art = self.artwork.get(self.current)
        self.cover_remove.setEnabled(self.cover.isEnabled() and bool(art or (info['artwork'] if info and art is None else False)))
        if self.current in self.artwork:
            self.cover.setToolTip('Choose cover · ' + ('Cover will be removed' if art == '' else Path(art).name))
            if art: self.show_cover(QPixmap(art))
        elif info and info['artwork']:
            self.cover.setToolTip(f'Choose cover · {info["artwork"]} embedded cover image(s)')
            self.cover_process.start('ffmpeg', ['-v', 'error', '-nostdin', '-i', str(self.current), '-map', '0:v:0',
                                                '-frames:v', '1', '-vf', 'scale=88:88:force_original_aspect_ratio=decrease',
                                                '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'])
        if info:
            fmt = info['format']
            lines = [str(self.current), '', f'Duration: {float(fmt.get("duration", 0)):.1f} seconds',
                     f'Size: {int(fmt.get("size", 0)) / 1024 / 1024:.2f} MiB',
                     f'Container: {fmt.get("format_long_name", "Unknown")}', '']
            for index, stream in enumerate(info['audio'], 1):
                lines.extend([f'Audio track {index}: {stream.get("codec_long_name", stream.get("codec_name", ""))}',
                              (f'  {stream.get("sample_rate", "?")} Hz · {stream.get("channels", "?")} channels · '
                               f'{stream.get("channel_layout", "")}'),
                              f'  Bitrate: {stream.get("bit_rate", "Unknown")} bit/s'])
            lines.extend(['', 'All tags', *[f'{key}: {value}' for key, value in sorted(info['tags'].items())]])
            self.details.setPlainText('\n'.join(lines))
        else:
            self.details.setPlainText('Reading audio information…')

    def cover_loaded(self, code, _status):
        if not code:
            pixmap = QPixmap(); pixmap.loadFromData(bytes(self.cover_process.readAllStandardOutput()))
            self.show_cover(pixmap)

    def show_cover(self, pixmap):
        if not pixmap.isNull():
            self.cover.setIcon(QIcon(pixmap))

    def field_edited(self, key):
        if not self.current: return
        edit = self.fields[key]
        self.drafts.setdefault(self.current, {})[key] = edit.toPlainText() if isinstance(edit, QPlainTextEdit) else edit.text()

    def choose_cover(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Choose cover', '', 'Images (*.jpg *.jpeg *.png)')
        if filename:
            self.artwork[self.current] = filename; self.render_tags()

    def remove_cover(self):
        self.artwork[self.current] = ''; self.render_tags()

    def discard_edits(self):
        self.drafts.pop(self.current, None); self.artwork.pop(self.current, None)
        self.info.pop(self.current, None)
        self.file_changed(self.files.currentItem(), None)

    def load_presets(self):
        try:
            presets = read_presets(self.config)
        except (OSError, ValueError, TypeError) as error:
            self.status.setText(f'Could not load presets: {error}')
            return
        self.presets.clear()
        for preset in presets: self.presets.addItem(preset['name'], preset)
        self.preset_changed()

    def preset_changed(self, _index=0):
        preset = self.presets.currentData()
        self.description.setText(preset.get('description', '') if preset else '')

    def choose_output(self):
        directory = QFileDialog.getExistingDirectory(self, 'Output folder', self.output.text() or str(Path.home() / 'Music'))
        if directory: self.output.setText(directory)

    def save_tags(self):
        if not self.current or self.current not in self.info: return
        targets = self.selected() if self.batch.isChecked() else [self.current]
        changes = dict(self.drafts.get(self.current, {}))
        artwork = self.artwork.get(self.current)
        if not targets or (not changes and artwork is None):
            self.status.setText('Edit a tag or choose a cover first. Only edited fields will be saved.')
            return
        if self.batch.isChecked() and len(targets) > 1:
            fields = ', '.join(FIELDS[key] for key in changes)
            if artwork is not None: fields += ', cover art'
            if QMessageBox.question(self, 'Apply tags to selected files',
                                    f'Apply these edits to {len(targets)} files?\n{fields}') != QMessageBox.StandardButton.Yes:
                return
        self.begin([('tags', p, (changes, artwork, self.backup.isChecked())) for p in targets])

    def start_conversion(self):
        targets = self.selected(); preset = self.presets.currentData()
        if not targets or not preset: return
        if any(self.drafts.get(p) or p in self.artwork for p in targets):
            QMessageBox.information(self, 'Unsaved tags', 'Save or discard tag edits before converting these files.')
            return
        folder = self.output.text().strip() or None
        if folder and not Path(folder).is_dir():
            QMessageBox.warning(self, 'Output folder', 'Choose an existing output folder.'); return
        self.begin([('convert', p, (dict(preset), folder, self.normalize.isChecked())) for p in targets])

    def begin(self, jobs):
        self.stop_probe()
        self.jobs = jobs; self.total = len(jobs); self.completed = 0; self.failures = 0; self.cancelled = False
        self.log.clear(); self.log.hide(); self.active = True
        self.files.setEnabled(False); self.tabs.setEnabled(False); self.add_button.setEnabled(False); self.cancel.setEnabled(True)
        self.next_job()

    def next_job(self):
        if not self.jobs or self.cancelled:
            self.end_jobs(); return
        self.job = self.jobs.pop(0)
        kind, source, arguments = self.job
        try:
            self.operation = tag_edit(source, *arguments) if kind == 'tags' else conversion(source, *arguments)
        except (OSError, ValueError) as error:
            self.report_error(f'{source.name}: {error}'); self.completed += 1
            QTimer.singleShot(0, self.next_job); return
        self.status.setText(f'{self.completed + 1}/{self.total} · {source.name}')
        self.buffer = ''; self.stderr = ''
        command = self.operation.command
        self.process.start(command[0], command[1:])

    def job_progress(self):
        self.buffer += bytes(self.process.readAllStandardOutput()).decode(errors='replace')
        lines = self.buffer.split('\n'); self.buffer = lines.pop()
        for line in lines:
            if line.startswith('out_time_us='):
                try: seconds = max(0, int(line.split('=', 1)[1])) / 1_000_000
                except ValueError: continue
                duration = float(self.info.get(self.job[1], {}).get('format', {}).get('duration', 0))
                fraction = min(seconds / duration, 0.99) if duration else 0
                self.progress.setValue(int(100 * (self.completed + fraction) / self.total))
                self.status.setText(f'{self.completed + 1}/{self.total} · {self.job[1].name} · {seconds:.0f}s')

    def job_error(self):
        self.stderr = (self.stderr + bytes(self.process.readAllStandardError()).decode(errors='replace'))[-16000:]

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.operation:
            self.stderr = self.process.errorString(); self.job_finished(1, QProcess.ExitStatus.CrashExit)

    def job_finished(self, code, _status):
        if not self.operation: return
        self.job_error()
        try:
            if self.cancelled:
                self.operation.abort()
            elif code:
                raise ValueError(self.stderr.strip() or 'FFmpeg could not process this file.')
            else:
                self.operation.finish()
                kind, source, _ = self.job
                if kind == 'tags':
                    self.drafts.pop(source, None); self.artwork.pop(source, None); self.info.pop(source, None)
                self.log.appendPlainText(f'Saved: {self.operation.target}')
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.operation.abort(); self.report_error(f'{self.job[1].name}: {error}')
        self.operation = None; self.completed += 1
        self.progress.setValue(int(100 * self.completed / self.total))
        QTimer.singleShot(0, self.next_job)

    def report_error(self, message):
        self.failures += 1; self.log.show(); self.log.appendPlainText(message)

    def cancel_jobs(self):
        self.cancelled = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            operation = self.operation
            self.process.terminate()
            QTimer.singleShot(2000, lambda: self.process.kill() if self.operation is operation and self.operation else None)

    def end_jobs(self):
        self.active = False; self.cancel.setEnabled(False)
        self.files.setEnabled(True); self.tabs.setEnabled(True); self.add_button.setEnabled(True)
        self.status.setText(('Cancelled' if self.cancelled else 'Finished') + f' · {self.completed} processed · {self.failures} failed')
        self.log.show()
        self.file_changed(self.files.currentItem(), None)

    def closeEvent(self, event):
        if self.active:
            self.cancel_jobs(); self.status.setText('Stopping… Close again when the current operation has stopped.')
            event.ignore(); return
        if ((any(self.drafts.values()) or self.artwork)
                and QMessageBox.question(self, 'Unsaved tags', 'Discard unsaved tag edits and close?') != QMessageBox.StandardButton.Yes):
            event.ignore(); return
        self.stop_probe(); event.accept()

    def reject(self):
        # Route Escape through the same job and draft handling as the close button.
        self.close()


def main():
    parser = argparse.ArgumentParser(description='Edit audio metadata and convert using saved presets.')
    parser.add_argument('files', nargs='*'); options = parser.parse_args()
    app = QApplication(sys.argv[:1]); app.setApplicationName('Audio tools'); app.setDesktopFileName('audio-tools')
    window = AudioTools(options.files)
    if not options.files: QTimer.singleShot(0, window.add_files)
    window.show()
    return app.exec()
