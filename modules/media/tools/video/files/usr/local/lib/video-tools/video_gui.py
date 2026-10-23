"""Video inspection and cancellable preset conversion in a native Qt dialog."""
import argparse
import os
import math
import sys
from fractions import Fraction
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from video_core import conversion, probe_command, read_presets, video_info

CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'video-tools/presets.json'


def human_duration(value):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 'Unknown'
    if not math.isfinite(seconds) or seconds < 0:
        return 'Unknown'
    # Round once so 59.96 seconds rolls over to 1 min 0 sec.
    tenths = round(seconds * 10)
    hours, remainder = divmod(tenths, 36000)
    minutes, remainder = divmod(remainder, 600)
    seconds = f'{remainder / 10:g}'
    if hours:
        return f'{hours} hr {minutes} min {seconds} sec'
    if minutes:
        return f'{minutes} min {seconds} sec'
    return f'{seconds} sec'


class VideoTools(QDialog):
    def __init__(self, paths, config=CONFIG):
        super().__init__()
        self.config = Path(config); self.info = {}; self.current = None; self.active = False
        self.operation = None; self.cancelled = False; self.probe_path = None
        self.setWindowTitle('Video tools'); self.setWindowIcon(QIcon.fromTheme('video-x-generic'))
        self.resize(1050, 760); self.setMinimumSize(780, 580)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel('Video tools'); font = title.font(); font.setPointSize(font.pointSize()+6); font.setBold(True); title.setFont(font)
        header.addWidget(title); header.addStretch()
        self.add = QPushButton(QIcon.fromTheme('list-add'), 'Add files…'); self.add.clicked.connect(self.add_files); header.addWidget(self.add)
        layout.addLayout(header)
        splitter = QSplitter(); self.files = QListWidget(); self.files.setMinimumWidth(220)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.currentItemChanged.connect(self.file_changed)
        splitter.addWidget(self.files); self.tabs = QTabWidget(); splitter.addWidget(self.tabs); splitter.setStretchFactor(1, 3)
        page = QWidget(); page_layout = QVBoxLayout(page)
        self.summary = QLabel('Add video files to begin.'); self.summary.setWordWrap(True); page_layout.addWidget(self.summary)
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(['Property', 'Value']); self.tree.setColumnWidth(0, 190); page_layout.addWidget(self.tree)
        copy = QPushButton('Copy information'); copy.clicked.connect(self.copy_info); page_layout.addWidget(copy)
        self.tabs.addTab(page, 'Information')
        page = QWidget(); convert_layout = QVBoxLayout(page)
        convert_layout.addWidget(QLabel('Convert selected files'))
        self.presets = QComboBox(); self.presets.currentIndexChanged.connect(self.preset_changed); convert_layout.addWidget(self.presets)
        self.description = QLabel(); self.description.setWordWrap(True); convert_layout.addWidget(self.description)
        output = QHBoxLayout(); output.addWidget(QLabel('Output folder'))
        self.output = QLineEdit(); self.output.setPlaceholderText('Beside each source file'); output.addWidget(self.output, 1)
        choose = QPushButton('Choose…'); choose.clicked.connect(self.choose_output); output.addWidget(choose); convert_layout.addLayout(output)
        note = QLabel('Outputs use “filename [preset-id].extension”. Sources are kept and existing files are never overwritten.')
        note.setWordWrap(True); convert_layout.addWidget(note); convert_layout.addStretch()
        run = QPushButton(QIcon.fromTheme('media-playback-start'), 'Convert selected files'); run.clicked.connect(self.start_conversion); convert_layout.addWidget(run)
        self.tabs.addTab(page, 'Convert'); layout.addWidget(splitter, 1)
        self.status = QLabel('Ready'); self.status.setWordWrap(True); layout.addWidget(self.status)
        footer = QHBoxLayout(); self.progress = QProgressBar(); self.progress.setValue(0); footer.addWidget(self.progress, 1)
        self.cancel = QPushButton('Cancel'); self.cancel.setEnabled(False); self.cancel.clicked.connect(self.cancel_jobs); footer.addWidget(self.cancel)
        close = QPushButton('Close'); close.clicked.connect(self.close); footer.addWidget(close); layout.addLayout(footer)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(110); self.log.hide(); layout.addWidget(self.log)
        self.probe = QProcess(self); self.probe.finished.connect(self.probed)
        self.probe.errorOccurred.connect(lambda _: self.status.setText(self.probe.errorString()) if self.probe_path else None)
        self.process = QProcess(self); self.process.readyReadStandardOutput.connect(self.job_progress)
        self.process.readyReadStandardError.connect(self.job_error); self.process.finished.connect(self.job_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.load_presets(); self.append_files(paths)

    def append_files(self, paths):
        known = {self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())}
        for value in paths:
            path = Path(value).resolve()
            if not path.is_file() or path in known: continue
            item = QListWidgetItem(QIcon.fromTheme('video-x-generic'), path.name)
            item.setData(Qt.ItemDataRole.UserRole, path); item.setToolTip(str(path)); self.files.addItem(item); known.add(path)
        if self.files.count() and self.files.currentRow() < 0: self.files.setCurrentRow(0)
        self.files.selectAll()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add video files', str(Path.home()/'Videos'),
            'Video (*.mp4 *.mkv *.webm *.mov *.avi *.mpeg *.mpg *.m4v *.ts *.ogv *.flv *.wmv *.3gp);;All files (*)')
        self.append_files(paths)

    def stop_probe(self):
        self.probe_path = None
        if self.probe.state() != QProcess.ProcessState.NotRunning:
            self.probe.kill(); self.probe.waitForFinished(1000)

    def file_changed(self, item, _previous):
        self.stop_probe(); self.current = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.tree.clear()
        if self.current in self.info: self.render_info()
        elif self.current:
            self.summary.setText('Reading ' + self.current.name + '…'); self.probe_path = self.current
            command = probe_command(self.current); self.probe.start(command[0], command[1:])

    def probed(self, code, _status):
        path = self.probe_path
        if path is None: return
        self.probe_path = None
        try:
            if code: raise ValueError(bytes(self.probe.readAllStandardError()).decode(errors='replace').strip())
            self.info[path] = video_info(bytes(self.probe.readAllStandardOutput()))
            if path == self.current: self.render_info()
        except (ValueError, KeyError) as error: self.status.setText(f'Could not inspect {path.name}: {error}')

    def render_info(self):
        data = self.info[self.current]; fmt = data.get('format', {}); self.tree.clear()
        duration = float(fmt.get('duration', 0)); size = int(fmt.get('size', 0))
        video = next(s for s in data['streams'] if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic'))
        self.summary.setText(f'{self.current.name}\n{video.get("width", "?")} × {video.get("height", "?")} · {human_duration(duration)} · {size/1024/1024:.1f} MiB')
        def group(title, values):
            parent = QTreeWidgetItem([title]); self.tree.addTopLevelItem(parent)
            for key, value in values:
                if value not in (None, ''): QTreeWidgetItem(parent, [key, str(value)])
            return parent
        group('Container', [('Path', str(self.current)), ('Format', fmt.get('format_long_name')), ('Duration', human_duration(duration)),
                            ('Bitrate', fmt.get('bit_rate')), ('Chapters', len(data.get('chapters', [])))])
        for stream in data.get('streams', []):
            kind = stream.get('codec_type', 'Unknown'); index = stream.get('index', '?')
            fields = [('Codec', stream.get('codec_long_name', stream.get('codec_name'))), ('Profile', stream.get('profile')),
                      ('Language', stream.get('tags', {}).get('language')), ('Title', stream.get('tags', {}).get('title'))]
            if kind == 'video':
                rate = stream.get('avg_frame_rate', '0/0')
                try: rate = f'{float(Fraction(rate)):.3f} fps'
                except (ValueError, ZeroDivisionError): pass
                fields += [('Dimensions', f'{stream.get("width")} × {stream.get("height")}'), ('Frame rate', rate),
                           ('Pixel format', stream.get('pix_fmt')), ('Color space', stream.get('color_space')),
                           ('Color transfer', stream.get('color_transfer')), ('Color primaries', stream.get('color_primaries')),
                           ('Bit depth', stream.get('bits_per_raw_sample'))]
            if kind == 'audio': fields += [('Sample rate', stream.get('sample_rate')), ('Channels', stream.get('channels')), ('Layout', stream.get('channel_layout'))]
            fields += [('Bitrate', stream.get('bit_rate')), ('Default', bool(stream.get('disposition', {}).get('default')))]
            group(f'{kind.title()} track {index}', fields)
        group('Tags', sorted(fmt.get('tags', {}).items()))
        for index, chapter in enumerate(data.get('chapters', []), 1):
            group(f'Chapter {index}', [('Title', chapter.get('tags', {}).get('title')), ('Start', human_duration(chapter.get('start_time'))), ('End', human_duration(chapter.get('end_time')))])
        self.tree.expandAll()

    def copy_info(self):
        lines = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i); lines.append(item.text(0))
            lines.extend('  '+item.child(j).text(0)+': '+item.child(j).text(1) for j in range(item.childCount()))
        QApplication.clipboard().setText('\n'.join(lines))

    def load_presets(self):
        try: presets = read_presets(self.config)
        except (OSError, ValueError, TypeError) as error:
            self.status.setText(f'Could not load presets: {error}'); return
        self.presets.clear()
        for preset in presets: self.presets.addItem(preset['name'], preset)

    def preset_changed(self, _index=0):
        self.description.setText((self.presets.currentData() or {}).get('description', ''))

    def choose_output(self):
        directory = QFileDialog.getExistingDirectory(self, 'Output folder', self.output.text() or str(Path.home()/'Videos'))
        if directory: self.output.setText(directory)

    def start_conversion(self):
        self.jobs = [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]
        self.preset = self.presets.currentData()
        if not self.jobs or not self.preset: return
        self.folder = self.output.text().strip() or None
        if self.folder and not Path(self.folder).is_dir(): self.status.setText('Choose an existing output folder.'); return
        self.stop_probe(); self.total = len(self.jobs); self.completed = 0; self.failures = 0; self.cancelled = False; self.active = True
        self.log.clear(); self.log.hide(); self.files.setEnabled(False); self.tabs.setEnabled(False); self.add.setEnabled(False); self.cancel.setEnabled(True)
        self.next_job()

    def next_job(self):
        if self.cancelled or not self.jobs:
            self.active = False; self.cancel.setEnabled(False); self.files.setEnabled(True); self.tabs.setEnabled(True); self.add.setEnabled(True)
            self.status.setText(('Cancelled' if self.cancelled else 'Finished')+f' · {self.completed} processed · {self.failures} failed'); self.log.show(); return
        self.source = self.jobs.pop(0)
        try: self.operation = conversion(self.source, self.preset, self.folder)
        except (OSError, ValueError) as error:
            self.failures += 1; self.log.show(); self.log.appendPlainText(f'{self.source.name}: {error}'); self.completed += 1
            QTimer.singleShot(0, self.next_job); return
        self.buffer = ''; self.stderr = ''; self.status.setText(f'{self.completed+1}/{self.total} · {self.source.name}')
        command = self.operation.command; self.process.start(command[0], command[1:])

    def job_progress(self):
        self.buffer += bytes(self.process.readAllStandardOutput()).decode(errors='replace')
        lines = self.buffer.split('\n'); self.buffer = lines.pop()
        for line in lines:
            if not line.startswith('out_time_us='): continue
            try: seconds = max(0, int(line.split('=',1)[1]))/1_000_000
            except ValueError: continue
            duration = float(self.info.get(self.source, {}).get('format', {}).get('duration', 0))
            fraction = min(seconds/duration, 0.99) if duration else 0
            self.progress.setValue(int(100*(self.completed+fraction)/self.total))
            self.status.setText(f'{self.completed+1}/{self.total} · {self.source.name} · {seconds:.0f}s')

    def job_error(self):
        self.stderr = (self.stderr + bytes(self.process.readAllStandardError()).decode(errors='replace'))[-16000:]

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.operation:
            self.stderr = self.process.errorString(); self.job_finished(1, QProcess.ExitStatus.CrashExit)

    def job_finished(self, code, _status):
        if not self.operation: return
        self.job_error()
        try:
            if self.cancelled: self.operation.abort()
            elif code: raise ValueError(self.stderr.strip() or 'FFmpeg could not convert this file.')
            else: self.operation.finish(); self.log.appendPlainText('Saved: '+str(self.operation.target))
        except (OSError, ValueError) as error:
            self.operation.abort(); self.failures += 1; self.log.show(); self.log.appendPlainText(f'{self.source.name}: {error}')
        self.operation = None; self.completed += 1; self.progress.setValue(int(100*self.completed/self.total)); QTimer.singleShot(0,self.next_job)

    def cancel_jobs(self):
        self.cancelled = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            operation = self.operation; self.process.terminate()
            QTimer.singleShot(2000, lambda: self.process.kill() if self.operation is operation and self.operation else None)

    def closeEvent(self, event):
        if self.active:
            self.cancel_jobs(); self.status.setText('Stopping the current conversion…'); event.ignore(); return
        self.stop_probe(); event.accept()

    def reject(self): self.close()


def main():
    parser = argparse.ArgumentParser(description='Inspect video and convert using saved presets.'); parser.add_argument('files', nargs='*'); options = parser.parse_args()
    app = QApplication(sys.argv[:1]); app.setApplicationName('Video tools'); app.setDesktopFileName('video-tools')
    window = VideoTools(options.files)
    if not options.files: QTimer.singleShot(0,window.add_files)
    window.show(); return app.exec()
