"""Desktop audio tools with asynchronous, cancellable FFmpeg jobs."""
import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import audio_lyrics
from core import (
    ART_FORMATS,
    FIELDS,
    audio_info,
    conversion,
    probe_command,
    read_presets,
    rename_file,
    tag_edit,
)
from PySide6.QtCore import QProcess, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'audio-tools/presets.json'


def human_duration(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 'Unknown'
    if not math.isfinite(seconds) or seconds < 0:
        return 'Unknown'
    tenths = round(seconds * 10)
    hours, remainder = divmod(tenths, 36000)
    minutes, remainder = divmod(remainder, 600)
    seconds = f'{remainder / 10:g}'
    if hours:
        return f'{hours} hr {minutes} min {seconds} sec'
    if minutes:
        return f'{minutes} min {seconds} sec'
    return f'{seconds} sec'


class AudioTools(QDialog):
    def __init__(self, path, config=CONFIG):
        super().__init__()
        self.config = Path(config)
        self.info = {}
        self.drafts = {}
        self.artwork = {}
        self.current = None
        self.operation = None
        self.cancelled = False
        self.active = False
        self.renaming = False
        self.probe_path = None
        self.lyrics_request = None
        self.setWindowTitle('Audio tools')
        self.setWindowIcon(QIcon.fromTheme('audio-x-generic'))
        self.resize(780, 740)
        self.setMinimumSize(600, 580)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel('Audio tools')
        font = title.font(); font.setPointSize(font.pointSize() + 6); font.setBold(True); title.setFont(font)
        header.addWidget(title); header.addStretch()
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.tags_tab(), 'Tags && artwork')
        self.tabs.addTab(self.convert_tab(), 'Convert')
        self.tabs.addTab(self.information_tab(), 'File information')
        layout.addWidget(self.tabs, 1)
        self.status = QLabel(); self.status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
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
        self.lyrics_process = QProcess(self)
        self.lyrics_process.finished.connect(self.lyrics_finished)
        self.lyrics_process.errorOccurred.connect(self.lyrics_error)
        self.load_presets()
        self.current = Path(path).resolve()
        self.filename.setText(self.current.name)
        self.setWindowTitle(self.current.name + ' — Audio tools')
        self.inspect_file()

    def tags_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16); layout.setSpacing(12)
        self.tag_options = QWidget(); options = QVBoxLayout(self.tag_options)
        options.setContentsMargins(0, 0, 0, 0); options.setSpacing(12)
        self.tag_hint = QLabel('Edit this file’s tags. Edits stay in the form until saved.')
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
        options.addLayout(heading)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(); body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0); body_layout.setSpacing(0)
        form = QFormLayout(); body_layout.addLayout(form); body_layout.addStretch(1)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setHorizontalSpacing(12); form.setVerticalSpacing(10)
        self.fields = {}
        for key, title in FIELDS.items():
            edit = QPlainTextEdit() if key == 'lyrics' else QLineEdit()
            if key == 'lyrics':
                edit.setFixedHeight(85)
                edit.setStyleSheet('QPlainTextEdit { border: 1px solid palette(mid); border-radius: 5px; '
                                  'padding: 4px; background: palette(base); } '
                                  'QPlainTextEdit:focus { border-color: palette(highlight); }')
                edit.textChanged.connect(lambda key=key: self.field_edited(key))
            else:
                edit.textEdited.connect(lambda _text, key=key: self.field_edited(key))
            edit.setObjectName('tag_' + key)
            if key == 'lyrics':
                section = QWidget(); lyrics_layout = QVBoxLayout(section)
                lyrics_layout.setContentsMargins(0, 0, 0, 0); lyrics_layout.setSpacing(4)
                heading = QHBoxLayout(); heading.addWidget(QLabel(title)); heading.addStretch()
                self.lyrics_fetch = QPushButton(QIcon.fromTheme('view-refresh'), 'Fetch lyrics')
                self.lyrics_fetch.setEnabled(False); self.lyrics_fetch.clicked.connect(self.lookup_lyrics)
                heading.addWidget(self.lyrics_fetch); lyrics_layout.addLayout(heading); lyrics_layout.addWidget(edit)
                form.addRow(section)
            else:
                form.addRow(title, edit)
            self.fields[key] = edit
        scroll.setWidget(body); options.addWidget(scroll, 1)
        self.backup = QCheckBox('Keep a backup when saving tags')
        options.addWidget(self.backup)
        layout.addWidget(self.tag_options, 1)
        buttons = QHBoxLayout()
        self.revert = QPushButton('Discard edits'); self.revert.clicked.connect(self.discard_edits)
        self.save = QPushButton(QIcon.fromTheme('document-save'), 'Save tags'); self.save.clicked.connect(self.save_tags)
        self.tag_cancel = QPushButton('Cancel'); self.tag_cancel.hide(); self.tag_cancel.clicked.connect(self.cancel_job)
        buttons.addWidget(self.revert); buttons.addStretch(); buttons.addWidget(self.tag_cancel); buttons.addWidget(self.save)
        layout.addLayout(buttons)
        return page

    def information_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.filename_view = QWidget()
        name_row = QHBoxLayout(self.filename_view); name_row.setContentsMargins(0, 0, 0, 0)
        self.filename_label = QLabel(); self.filename_label.setWordWrap(True)
        self.filename_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.edit_filename = QToolButton(); self.edit_filename.setObjectName('audio_edit_filename')
        self.edit_filename.setAutoRaise(True)
        self.edit_filename.setAccessibleName('Edit file name')
        self.edit_filename.setToolTip('Edit file name')
        icon = QIcon.fromTheme('document-edit')
        if icon.isNull(): icon = QIcon.fromTheme('edit-rename')
        self.edit_filename.setIcon(icon)
        if icon.isNull(): self.edit_filename.setText('✎')
        self.edit_filename.clicked.connect(self.start_rename_edit)
        name_row.addWidget(self.filename_label, 1); name_row.addWidget(self.edit_filename)
        layout.addWidget(self.filename_view)

        self.filename_editor = QWidget()
        rename_row = QHBoxLayout(self.filename_editor); rename_row.setContentsMargins(0, 0, 0, 0)
        self.filename = QLineEdit(); self.filename.setObjectName('audio_filename')
        self.filename.setAccessibleName('Audio filename')
        self.filename.setToolTip('Rename in the same folder. Keep the existing audio extension.')
        self.filename.textEdited.connect(self.update_rename_controls)
        self.rename_button = QPushButton('Rename'); self.rename_button.setObjectName('audio_rename')
        self.rename_button.clicked.connect(self.rename_current_file)
        self.cancel_rename = QPushButton('Cancel'); self.cancel_rename.clicked.connect(self.cancel_rename_edit)
        rename_row.addWidget(self.filename, 1); rename_row.addWidget(self.rename_button); rename_row.addWidget(self.cancel_rename)
        self.filename_editor.hide(); layout.addWidget(self.filename_editor)

        self.summary = QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(['Property', 'Value'])
        self.tree.setColumnWidth(0, 190); layout.addWidget(self.tree)
        copy = QPushButton('Copy information'); copy.clicked.connect(self.copy_info); layout.addWidget(copy)
        return page

    def convert_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16); layout.setSpacing(12)
        self.convert_options = QWidget(); options = QVBoxLayout(self.convert_options)
        options.setContentsMargins(0, 0, 0, 0); options.setSpacing(12)
        heading = QLabel('Convert file'); font = heading.font(); font.setBold(True); heading.setFont(font)
        options.addWidget(heading)
        self.presets = QComboBox(); self.presets.currentIndexChanged.connect(self.preset_changed)
        options.addWidget(self.presets)
        self.description = QLabel(); self.description.setWordWrap(True); options.addWidget(self.description)
        form = QFormLayout()
        output = QHBoxLayout()
        self.output = QLineEdit(); self.output.setPlaceholderText('Beside the source file')
        browse = QPushButton('Choose…'); browse.clicked.connect(self.choose_output)
        output.addWidget(self.output, 1); output.addWidget(browse); form.addRow('Output folder', output)
        options.addLayout(form)
        self.normalize = QCheckBox('Normalize loudness to −16 LUFS')
        self.normalize.setToolTip('One-pass EBU R128 loudness normalization; true peak −1.5 dB, loudness range 11 LU.')
        options.addWidget(self.normalize)
        note = QLabel('Outputs use “filename [preset-id].extension”. Existing files are never overwritten.\n'
                      'The first audio track is converted. Tags and supported cover art are copied. Sources are kept.')
        note.setWordWrap(True); options.addWidget(note)
        layout.addWidget(self.convert_options)
        layout.addStretch()
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout(); buttons.addStretch()
        self.cancel = QPushButton('Cancel'); self.cancel.setEnabled(False); self.cancel.clicked.connect(self.cancel_job)
        buttons.addWidget(self.cancel)
        self.convert = QPushButton(QIcon.fromTheme('media-playback-start'), 'Convert file')
        self.convert.clicked.connect(self.start_conversion); buttons.addWidget(self.convert)
        layout.addLayout(buttons)
        return page

    def inspect_file(self):
        self.stop_probe()
        self.render_tags()
        if self.current not in self.info:
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
        self.tag_hint.setText(self.current.name)
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
        self.render_info()
        self.update_lyrics_button()

    def render_info(self):
        self.tree.clear()
        self.update_rename_controls()
        self.filename_label.setText(self.current.name)
        info = self.info.get(self.current)
        if not info:
            self.summary.setText('Reading audio information…'); return
        fmt = info['format']; audio = info['audio'][0]
        duration = human_duration(fmt.get('duration', audio.get('duration')))
        size = int(fmt.get('size', 0))
        codec = audio.get('codec_name', 'Audio').upper()
        self.summary.setText(f'{codec} · {duration} · {size/1024/1024:.1f} MiB')

        def group(title, values):
            parent = QTreeWidgetItem([title]); self.tree.addTopLevelItem(parent)
            for key, value in values:
                if value not in (None, ''): QTreeWidgetItem(parent, [key, str(value)])

        group('Container', [('Path', str(self.current)), ('Format', fmt.get('format_long_name')),
                            ('Duration', duration), ('Bitrate', fmt.get('bit_rate')),
                            ('Audio tracks', len(info['audio'])), ('Embedded covers', info['artwork'])])
        for index, stream in enumerate(info['audio']):
            tags = stream.get('tags', {})
            group(f'Audio track {stream.get("index", index)}', [
                ('Codec', stream.get('codec_long_name', stream.get('codec_name'))),
                ('Profile', stream.get('profile')), ('Language', tags.get('language')), ('Title', tags.get('title')),
                ('Sample rate', stream.get('sample_rate')), ('Channels', stream.get('channels')),
                ('Layout', stream.get('channel_layout')), ('Sample format', stream.get('sample_fmt')),
                ('Bit depth', stream.get('bits_per_raw_sample') or stream.get('bits_per_sample')),
                ('Bitrate', stream.get('bit_rate')), ('Default', bool(stream.get('disposition', {}).get('default')))])
        group('Tags', sorted(info['tags'].items()))
        self.tree.expandAll()

    def update_rename_controls(self, *_args):
        pending = bool(self.drafts.get(self.current)) or self.current in self.artwork
        available = not self.active and not pending and self.current in self.info and self.current.is_file()
        self.filename_view.setVisible(not self.renaming)
        self.filename_editor.setVisible(self.renaming)
        self.edit_filename.setEnabled(available)
        self.filename.setEnabled(available and self.renaming)
        self.rename_button.setEnabled(available and self.renaming and self.filename.text() != self.current.name)
        self.cancel_rename.setEnabled(self.renaming and not self.active)
        hint = ('Save or discard tag edits before renaming.' if pending else
                'Rename in the same folder. Keep the existing audio extension.')
        self.filename.setToolTip(hint)
        self.rename_button.setToolTip(hint)

    def start_rename_edit(self):
        if self.active or self.current not in self.info or self.drafts.get(self.current) or self.current in self.artwork:
            return
        self.renaming = True
        self.filename.setText(self.current.name)
        self.update_rename_controls()
        self.filename.setFocus()
        self.filename.selectAll()

    def cancel_rename_edit(self):
        self.renaming = False
        self.filename.setText(self.current.name)
        self.update_rename_controls()

    def rename_current_file(self):
        if self.active or not self.renaming or self.current not in self.info:
            return
        if self.drafts.get(self.current) or self.current in self.artwork:
            self.status.setText('Save or discard tag edits before renaming this file.')
            return
        previous = self.current
        self.stop_probe()
        try:
            target = rename_file(previous, self.filename.text())
        except (OSError, ValueError) as error:
            self.status.setText(f'Could not rename {previous.name}: {error}')
            self.update_rename_controls()
            return
        if target == previous:
            self.cancel_rename_edit()
            return
        self.renaming = False
        self.info.pop(previous, None)
        self.current = target
        self.filename.setText(target.name)
        self.filename_label.setText(target.name)
        self.setWindowTitle(target.name + ' — Audio tools')
        self.status.setText(f'Renamed to {target.name}.')
        self.inspect_file()

    def copy_info(self):
        lines = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i); lines.append(item.text(0))
            lines.extend('  ' + item.child(j).text(0) + ': ' + item.child(j).text(1) for j in range(item.childCount()))
        QApplication.clipboard().setText('\n'.join(lines))

    def cover_loaded(self, code, _status):
        if not code:
            pixmap = QPixmap(); pixmap.loadFromData(bytes(self.cover_process.readAllStandardOutput()))
            self.show_cover(pixmap)

    def show_cover(self, pixmap):
        if not pixmap.isNull():
            self.cover.setIcon(QIcon(pixmap))

    def field_edited(self, key):
        if not self.current: return
        if key in ('title', 'artist', 'album', 'lyrics') and self.lyrics_request:
            self.stop_lyrics()
            self.status.setText('Lyrics lookup cancelled because the song details or lyrics changed.')
        edit = self.fields[key]
        self.drafts.setdefault(self.current, {})[key] = edit.toPlainText() if isinstance(edit, QPlainTextEdit) else edit.text()
        self.update_rename_controls()
        self.update_lyrics_button()

    def update_lyrics_button(self):
        self.lyrics_fetch.setText('Cancel fetch' if self.lyrics_request else 'Fetch lyrics')
        ready = self.current in self.info and all(self.fields[key].text().strip() for key in ('title', 'artist'))
        self.lyrics_fetch.setEnabled(not self.active and bool(self.lyrics_request or ready))
        self.lyrics_fetch.setToolTip('' if ready else 'Set the title and artist first.')

    def lookup_lyrics(self):
        if self.lyrics_request:
            self.stop_lyrics(); self.status.setText('Lyrics lookup cancelled.'); return
        if self.active or self.current not in self.info: return
        song = {key: self.fields[key].text().strip() for key in ('title', 'artist', 'album')}
        if not song['title'] or not song['artist']:
            self.status.setText('Set the title and artist before fetching lyrics.'); return
        previous = self.fields['lyrics'].toPlainText()
        if previous.strip() and QMessageBox.question(self, 'Replace lyrics?',
                'Replace the lyrics in the form with a fetched version?') != QMessageBox.StandardButton.Yes:
            return
        info = self.info[self.current]
        song['duration'] = info['format'].get('duration') or info['audio'][0].get('duration') or 0
        self.lyrics_request = (self.current, song, previous)
        self.update_lyrics_button(); self.status.setText('Fetching lyrics…')
        self.lyrics_process.start(sys.executable, [str(Path(audio_lyrics.__file__).resolve())])
        self.lyrics_process.write(json.dumps(song).encode())
        self.lyrics_process.closeWriteChannel()

    def stop_lyrics(self):
        self.lyrics_request = None
        if self.lyrics_process.state() != QProcess.ProcessState.NotRunning:
            self.lyrics_process.kill(); self.lyrics_process.waitForFinished(1000)
        self.update_lyrics_button()

    def lyrics_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.lyrics_request:
            self.lyrics_request = None; self.update_lyrics_button()
            self.status.setText('Could not start the lyrics lookup.')

    def lyrics_finished(self, code, _status):
        request = self.lyrics_request
        self.lyrics_request = None; self.update_lyrics_button()
        if not request: return
        path, song, previous = request
        if (path != self.current or self.active or self.fields['lyrics'].toPlainText() != previous
                or any(self.fields[key].text().strip() != song[key] for key in ('title', 'artist', 'album'))):
            self.status.setText('Lyrics lookup discarded because the song details or lyrics changed.'); return
        try:
            result = json.loads(bytes(self.lyrics_process.readAllStandardOutput()))
            if not isinstance(result, dict): raise ValueError()
            if code or result.get('error'):
                self.status.setText(result.get('error') or 'The lyrics lookup failed.'); return
            if not result.get('available'):
                self.status.setText('No matching lyrics found.'); return
            text = result.get('lyrics')
            if not isinstance(text, str) or len(text) > audio_lyrics.MAX_LYRICS or '\0' in text:
                raise ValueError()
        except (ValueError, TypeError):
            self.status.setText('The lyrics lookup returned an invalid response.'); return
        self.fields['lyrics'].setPlainText(text)
        self.status.setText('Lyrics loaded. Save tags to keep them in the file.')

    def choose_cover(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Choose cover', '', 'Images (*.jpg *.jpeg *.png)')
        if filename:
            self.artwork[self.current] = filename; self.render_tags()

    def remove_cover(self):
        self.artwork[self.current] = ''; self.render_tags()

    def discard_edits(self):
        self.stop_lyrics()
        self.drafts.pop(self.current, None); self.artwork.pop(self.current, None)
        self.info.pop(self.current, None)
        self.inspect_file()

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
        changes = dict(self.drafts.get(self.current, {}))
        artwork = self.artwork.get(self.current)
        if not changes and artwork is None:
            self.status.setText('Edit a tag or choose a cover first. Only edited fields will be saved.')
            return
        self.begin('tags', (changes, artwork, self.backup.isChecked()))

    def start_conversion(self):
        preset = self.presets.currentData()
        if not preset: return
        if self.drafts.get(self.current) or self.current in self.artwork:
            QMessageBox.information(self, 'Unsaved tags', 'Save or discard tag edits before converting this file.')
            return
        folder = self.output.text().strip() or None
        if folder and not Path(folder).is_dir():
            QMessageBox.warning(self, 'Output folder', 'Choose an existing output folder.'); return
        self.begin('convert', (dict(preset), folder, self.normalize.isChecked()))

    def begin(self, kind, arguments):
        if self.active: return
        self.stop_lyrics()
        self.stop_probe()
        self.job = (kind, self.current, arguments)
        self.failures = 0; self.cancelled = False
        self.log.clear(); self.log.hide(); self.active = True
        self.update_rename_controls()
        self.update_lyrics_button()
        self.tabs.setCurrentIndex(0 if kind == 'tags' else 1)
        self.tabs.tabBar().setEnabled(False)
        self.tag_options.setEnabled(False); self.revert.setEnabled(False); self.save.setEnabled(False)
        self.convert_options.setEnabled(False); self.convert.setEnabled(False)
        self.tag_cancel.setVisible(kind == 'tags'); self.cancel.setEnabled(kind == 'convert')
        if kind == 'convert': self.progress.setValue(0)
        try:
            self.operation = tag_edit(self.current, *arguments) if kind == 'tags' else conversion(self.current, *arguments)
        except (OSError, ValueError) as error:
            self.report_error(f'{self.current.name}: {error}')
            self.end_job(); return
        self.status.setText(self.current.name)
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
                if self.job[0] == 'convert': self.progress.setValue(int(100 * fraction))
                self.status.setText(f'{self.current.name} · {seconds:.0f}s')

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
        self.operation = None
        if self.job[0] == 'convert' and not self.cancelled and not self.failures: self.progress.setValue(100)
        self.end_job()

    def report_error(self, message):
        self.failures += 1; self.log.show(); self.log.appendPlainText(message)

    def cancel_job(self):
        self.cancelled = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            operation = self.operation
            self.process.terminate()
            QTimer.singleShot(2000, lambda: self.process.kill() if self.operation is operation and self.operation else None)

    def end_job(self):
        self.active = False; self.cancel.setEnabled(False)
        self.tabs.tabBar().setEnabled(True)
        self.tag_options.setEnabled(True); self.revert.setEnabled(True); self.save.setEnabled(True)
        self.convert_options.setEnabled(True); self.convert.setEnabled(True); self.tag_cancel.hide()
        self.status.setText('Cancelled' if self.cancelled else 'Failed' if self.failures else 'Finished')
        self.log.show()
        self.inspect_file()

    def closeEvent(self, event):
        if self.active:
            self.cancel_job(); self.status.setText('Stopping… Close again when the current operation has stopped.')
            event.ignore(); return
        if ((any(self.drafts.values()) or self.artwork)
                and QMessageBox.question(self, 'Unsaved tags', 'Discard unsaved tag edits and close?') != QMessageBox.StandardButton.Yes):
            event.ignore(); return
        self.stop_probe(); event.accept()
        self.stop_lyrics()

    def reject(self):
        # Route Escape through the same job and draft handling as the close button.
        self.close()


def main():
    parser = argparse.ArgumentParser(description='Edit audio metadata and convert using saved presets.')
    parser.add_argument('file', nargs='?'); options = parser.parse_args()
    app = QApplication(sys.argv[:1]); app.setApplicationName('Audio tools'); app.setDesktopFileName('audio-tools')
    path = options.file
    if not path:
        path, _ = QFileDialog.getOpenFileName(None, 'Open audio file', str(Path.home() / 'Music'),
            'Audio (*.mp3 *.flac *.m4a *.aac *.ogg *.opus *.wav *.aiff *.aif *.mka *.wma *.ape *.wv);;All files (*)')
        if not path: return 0
    window = AudioTools(path)
    window.show()
    return app.exec()
