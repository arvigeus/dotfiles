"""Native arrangement editor; the shell's shared helper owns validation and saving."""

import copy
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon, QPainter, QPalette, QPen
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


def helper_path():
    base = os.environ.get('XDG_CONFIG_HOME', '')
    return (
        Path(base) if os.path.isabs(base) else Path.home() / '.config'
    ) / 'quickshell/desktop/drawers/displays/backend.py'


def logical_size(row):
    width, height = map(int, row['mode'].split('@')[0].split('x'))
    if row['transform'] % 2:
        width, height = height, width
    return round(width / row['scale']), round(height / row['scale'])


class MonitorItem(QGraphicsObject):
    moved = Signal()
    released = Signal()

    def __init__(self, row, number):
        super().__init__()
        self.row = row
        self.number = number
        self.box = QRectF(0, 0, *logical_size(row))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setPos(row['x'], row['y'])
        self.setToolTip(f'{row["label"]} · {row["name"]}')
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def boundingRect(self):
        return self.box

    def paint(self, painter, option, widget=None):
        palette = QApplication.palette()
        scale = abs(painter.worldTransform().m11()) or 1
        inset = 2 / scale
        box = self.box.adjusted(inset, inset, -inset, -inset)
        selected = self.isSelected()
        fill = palette.color(
            QPalette.ColorRole.Highlight
            if selected
            else QPalette.ColorRole.AlternateBase
        )
        foreground = palette.color(
            QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                palette.color(
                    QPalette.ColorRole.Highlight if selected else QPalette.ColorRole.Mid
                ),
                2 / scale,
            )
        )
        painter.setBrush(fill)
        painter.drawRoundedRect(box, 8 / scale, 8 / scale)
        font = QFont(QApplication.font())
        font.setPixelSize(round(14 / scale))
        painter.setFont(font)
        painter.setPen(foreground)
        text = f'{self.number} · {self.row["name"]}\n{self.row["label"]}'
        if self.box.width() * scale < 170:
            text = f'{self.number}\n{self.row["name"]}'
        painter.drawText(
            box.adjusted(8 / scale, 8 / scale, -8 / scale, -8 / scale),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            text,
        )

    def mousePressEvent(self, event):
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        x, y = self.pos().x(), self.pos().y()
        if not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            scale = abs(self.scene().views()[0].transform().m11()) or 1
            threshold = 12 / scale
            dx, dy = [], []
            for item in self.scene().items():
                if not isinstance(item, MonitorItem) or item is self:
                    continue
                other = item.sceneBoundingRect()
                for a in (x, x + self.box.width()):
                    dx.extend([other.left() - a, other.right() - a])
                for a in (y, y + self.box.height()):
                    dy.extend([other.top() - a, other.bottom() - a])
            if dx and abs(min(dx, key=abs)) <= threshold:
                x += min(dx, key=abs)
            if dy and abs(min(dy, key=abs)) <= threshold:
                y += min(dy, key=abs)
        self.setPos(round(x), round(y))
        self.moved.emit()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.moved.emit()
        self.released.emit()

    def keyPressEvent(self, event):
        directions = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() not in directions:
            return super().keyPressEvent(event)
        dx, dy = directions[event.key()]
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        self.moveBy(dx * step, dy * step)
        self.moved.emit()
        event.accept()


class ArrangementView(QGraphicsView):
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_layout()

    def fit_layout(self):
        if not self.scene() or not self.scene().items():
            return
        box = self.scene().itemsBoundingRect()
        padding = max(box.width(), box.height()) * 0.08
        self.fitInView(
            box.adjusted(-padding, -padding, padding, padding),
            Qt.AspectRatioMode.KeepAspectRatio,
        )


class DisplayArrangement(QDialog):
    def __init__(self, auto_load=True, helper=None):
        super().__init__()
        self.helper = Path(helper) if helper else helper_path()
        self.baseline = None
        self.mode = ''
        self.stale = False
        self.pending_refresh = False
        self.items = {}
        self.event_buffer = b''
        self.setWindowTitle('Display arrangement')
        self.setWindowIcon(QIcon.fromTheme('preferences-desktop-display'))
        self.resize(960, 680)
        self.setMinimumSize(600, 420)
        layout = QVBoxLayout(self)
        heading = QLabel('Display arrangement')
        font = heading.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        self.summary = QLabel('Reading connected displays…')
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.scene = QGraphicsScene(self)
        self.scene.selectionChanged.connect(self.selection_changed)
        self.view = ArrangementView(self.scene)
        self.view.setAccessibleName(
            'Monitor positions. Drag to arrange; arrow keys move one pixel, Shift and arrows move ten.'
        )
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.view, 1)
        coordinates = QHBoxLayout()
        self.selected = QLabel('Select a display')
        self.selected.setTextFormat(Qt.TextFormat.PlainText)
        self.selected.setWordWrap(True)
        coordinates.addWidget(self.selected, 1)
        self.x = QSpinBox()
        self.y = QSpinBox()
        for field, label in ((self.x, 'X'), (self.y, 'Y')):
            field.setRange(-32768, 32768)
            field.setAccessibleName(f'{label} position in logical pixels')
            field.valueChanged.connect(self.coordinates_changed)
            coordinates.addWidget(QLabel(label))
            coordinates.addWidget(field)
        layout.addLayout(coordinates)
        hint = QLabel(
            'Drag displays to match your desk. Edges snap; hold Shift to move freely.'
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.reload = QPushButton(QIcon.fromTheme('view-refresh'), 'Reload arrangement')
        self.reload.clicked.connect(self.reload_clicked)
        footer.addWidget(self.reload)
        footer.addStretch()
        self.apply = QPushButton('Apply arrangement')
        self.apply.setDefault(True)
        self.apply.clicked.connect(self.apply_arrangement)
        footer.addWidget(self.apply)
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.close)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.process = QProcess(self)
        self.process.started.connect(self.write_request)
        self.process.finished.connect(self.request_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.debounce = QTimer(self)
        self.debounce.setInterval(500)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.refresh)
        self.socket = QLocalSocket(self)
        self.socket.readyRead.connect(self.read_events)
        self.socket.errorOccurred.connect(self.event_error)
        self.update_actions()
        if auto_load:
            runtime = os.environ.get('XDG_RUNTIME_DIR', '')
            instance = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE', '')
            if os.path.isabs(runtime) and instance and '/' not in instance:
                self.socket.connectToServer(
                    str(Path(runtime) / 'hypr' / instance / '.socket2.sock')
                )
            QTimer.singleShot(0, self.refresh)

    def event_error(self, _):
        self.status.setText(
            'Display change notifications are unavailable. Reload before applying changes.'
        )

    def read_events(self):
        self.event_buffer += bytes(self.socket.readAll())
        while b'\n' in self.event_buffer:
            line, self.event_buffer = self.event_buffer.split(b'\n', 1)
            if line.startswith(
                (
                    b'monitoraddedv2>>',
                    b'monitorremoved>>',
                    b'configreloaded>>',
                    b'custom>>desktop-displays-changed',
                )
            ):
                self.debounce.start()

    def positions(self):
        return {
            name: dict(x=round(item.pos().x()), y=round(item.pos().y()))
            for name, item in self.items.items()
        }

    def original_positions(self):
        return {
            row['name']: dict(x=row['x'], y=row['y'])
            for row in (self.baseline or {}).get('displays', [])
            if row['enabled'] and row['mirror'] == 'none'
        }

    def dirty(self):
        return self.positions() != self.original_positions()

    def update_actions(self):
        busy = bool(self.mode)
        selected = bool(self.scene.selectedItems())
        self.view.setEnabled(not busy)
        self.reload.setEnabled(not busy)
        self.apply.setEnabled(
            bool(self.baseline) and self.dirty() and not busy and not self.stale
        )
        self.x.setEnabled(selected and not busy and not self.stale)
        self.y.setEnabled(selected and not busy and not self.stale)
        self.close_button.setEnabled(not busy)

    def selection_changed(self):
        selected = self.scene.selectedItems()
        item = selected[0] if selected else None
        self.selected.setText(item.row['label'] if item else 'Select a display')
        if item:
            self.x.blockSignals(True)
            self.y.blockSignals(True)
            self.x.setValue(round(item.pos().x()))
            self.y.setValue(round(item.pos().y()))
            self.x.blockSignals(False)
            self.y.blockSignals(False)
        self.update_actions()

    def coordinates_changed(self):
        selected = self.scene.selectedItems()
        if selected:
            selected[0].setPos(self.x.value(), self.y.value())
            self.view.fit_layout()
            self.update_actions()

    def item_moved(self):
        self.selection_changed()
        self.update_actions()

    def load_state(self, data):
        self.baseline = copy.deepcopy(data)
        self.stale = False
        self.scene.blockSignals(True)
        self.scene.clear()
        self.items = {}
        rows = data['displays']
        for number, row in enumerate(rows, 1):
            if row['enabled'] and row['mirror'] == 'none':
                item = MonitorItem(row, number)
                item.moved.connect(self.item_moved)
                item.released.connect(self.view.fit_layout)
                self.scene.addItem(item)
                self.items[row['name']] = item
        self.scene.blockSignals(False)
        labels = []
        for row in rows:
            suffix = (
                ' (disabled)'
                if not row['enabled']
                else f' (mirrors {row["mirror"]})'
                if row['mirror'] != 'none'
                else ''
            )
            labels.append(row['label'] + suffix)
        self.summary.setText(' · '.join(labels) or 'No connected displays')
        if self.items:
            next(iter(self.items.values())).setSelected(True)
        self.view.fit_layout()
        self.selection_changed()

    def request(self, mode, **values):
        if self.mode:
            self.pending_refresh = True
            return
        self.mode = mode
        self.payload = json.dumps(dict(op=mode, **values)).encode() + b'\n'
        self.process.start(sys.executable, [str(self.helper)])
        self.update_actions()

    def write_request(self):
        self.process.write(self.payload)
        self.process.closeWriteChannel()

    def refresh(self):
        self.request('status')

    def reload_clicked(self):
        if (
            self.dirty()
            and QMessageBox.question(
                self,
                'Discard position edits?',
                'Reload the current arrangement and discard your unapplied positions?',
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.stale = False
        self.baseline = None
        self.refresh()

    def apply_arrangement(self):
        if self.apply.isEnabled():
            self.status.setText('Applying arrangement…')
            self.request(
                'arrange', token=self.baseline['token'], positions=self.positions()
            )

    def request_finished(self, exit_code, _):
        mode = self.mode
        self.mode = ''
        try:
            result = json.loads(bytes(self.process.readAllStandardOutput()))
            if exit_code or not result.get('ok'):
                raise ValueError(result.get('error') or 'The display helper failed.')
            data = result['data']
            if mode == 'status' and self.baseline and self.dirty():
                if data['token'] != self.baseline['token']:
                    self.stale = True
                    self.status.setText(
                        'Displays changed while editing. Reload the arrangement before applying.'
                    )
            else:
                self.load_state(data)
                self.status.setText(
                    'Arrangement saved for these connected displays.'
                    if mode == 'arrange'
                    else ''
                )
        except (ValueError, KeyError, TypeError) as error:
            self.status.setText(str(error))
            if mode == 'arrange':
                self.stale = True
        self.update_actions()
        if self.pending_refresh:
            self.pending_refresh = False
            self.debounce.start()

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.mode = ''
            self.status.setText('Could not start the display helper.')
            self.update_actions()

    def closeEvent(self, event):
        if self.mode:
            event.ignore()
            return
        if (
            self.dirty()
            and QMessageBox.question(
                self,
                'Discard position edits?',
                'Close without applying your position edits?',
            )
            != QMessageBox.StandardButton.Yes
        ):
            event.ignore()
            return
        self.socket.abort()
        # QDialog.closeEvent calls reject(), which routes back through our guard.
        # Complete the dialog directly after the user has confirmed discarding.
        super().reject()
        event.accept()

    def reject(self):
        self.close()


def main():
    app = QApplication(sys.argv)
    app.setDesktopFileName('display-tools')
    window = DisplayArrangement()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
