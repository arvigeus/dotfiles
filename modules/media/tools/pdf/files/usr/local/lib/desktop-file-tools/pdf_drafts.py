"""PDF draft lifecycle and native preview shared by the document editor."""
from copy import deepcopy
from pathlib import Path
import tempfile

from PySide6.QtCore import QByteArray,QItemSelectionModel,QPointF,Qt
from PySide6.QtGui import QAction,QIcon,QKeySequence,QPainter,QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication,QComboBox,QFileDialog,QHBoxLayout,QLabel,QLineEdit,QListWidgetItem,QMessageBox,QPushButton,QSpinBox,QWidget

from tools_gui import ToolsDialog
from pdf_edits import PDF_EDITS
from tool_jobs import files as matching_files

GLYPHS = {
 'combine':'M4 8h7m-3-3v6M14 4h6v16H4v-6',
 'split':'M9 3v18m6-18v18M3 8l4 4-4 4m18-8-4 4 4 4',
 'rotate':'M20 9a8 8 0 1 0 0 6M20 3v6h-6',
 'linearize':'M3 7h18M3 12h12M3 17h16',
 'reduce':'M4 4l6 6m-6 0h6V4m10 16-6-6m6 0h-6v6',
 'metadata':'M5 3h10l4 4v14H5zM9 11l6 6m0-6-6 6',
 'pdfa':'M5 3h10l4 4v14H5zM8 17l4-8 4 8m-6-3h4',
 'protect':'M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4',
 'unprotect':'M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0',
 'watermark':'M5 3h14v18H5zM8 16l4-5 4 5z',
 'images':'M3 4h18v16H3zM3 17l6-6 4 4 3-3 5 5M16 8h.1',
 'inspect':'M12 11v6m0-10h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
 'signatures':'M4 18l12-12 3 3L7 21H4zM14 8l3 3M4 3h8',
 'previous':'M15 5l-7 7 7 7', 'next':'M9 5l7 7-7 7',
 'add':'M12 4v16M4 12h16', 'remove':'M4 12h16',
 'undo':'M9 4 3 10l6 6M3 10h10a7 7 0 0 1 7 9',
}


def line_icon(name):
    color=QApplication.palette().color(QApplication.palette().ColorRole.Text).name()
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><path d="{GLYPHS.get(name,GLYPHS["inspect"])}" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    pixmap=QPixmap(48,48);pixmap.fill(Qt.GlobalColor.transparent);painter=QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter);painter.end();pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def size_label(size):
    for unit in ('B','KiB','MiB','GiB'):
        if size<1024 or unit=='GiB':return f'{size:g} {unit}' if unit=='B' else f'{size:.1f} {unit}'
        size/=1024


class PdfDraftDialog(ToolsDialog):
    def __init__(self,paths=()):
        self._building=True;self.records={};self.saved={};self.history=[];self.pending=None
        self.session=tempfile.TemporaryDirectory(prefix='pdf-tools-drafts-')
        super().__init__('pdf',paths,load_keys=False)
        self._building=False;self.action_changed();self.preview_current()
        for button in self.findChildren(QPushButton):button.setAutoDefault(False)
        for key,callback in [('Ctrl+S',self.export_current),('Ctrl+Z',self.undo_edit)]:
            action=QAction(self);action.setShortcut(QKeySequence(key));action.triggered.connect(callback);self.addAction(action)

    def snapshot(self):
        return deepcopy([self.records[self.files.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.files.count())])

    @staticmethod
    def signature(record):return (record['path'],record['name'])

    def dirty_records(self):return [record for record in self.snapshot() if self.signature(record)!=self.saved.get(record['key'])]

    def selected_records(self):return [self.records[item.data(Qt.ItemDataRole.UserRole)] for item in self.files.selectedItems()]

    def selected(self):return [record['path'] for record in self.selected_records()]

    def append_paths(self,paths):
        extensions={'.pdf'}
        try:paths=matching_files(paths,extensions)
        except (OSError,ValueError) as error:self.status.setText(str(error));return
        added=[]
        for path in paths:
            key=str(path)
            if key in self.records:continue
            record=dict(key=key,original=key,path=key,name=path.name,password='',edits=[])
            self.records[key]=record;self.saved[key]=self.signature(record)
            item=QListWidgetItem(path.name);item.setData(Qt.ItemDataRole.UserRole,key);self.files.addItem(item);added.append(item)
        if added:
            self.files.clearSelection()
            for item in added:item.setSelected(True)
            self.files.setCurrentItem(added[0],QItemSelectionModel.SelectionFlag.NoUpdate)
        self.invalidate_preview()

    def restore(self,records):
        selected={record['key'] for record in self.selected_records()}
        current=self.files.currentItem();current_key=current.data(Qt.ItemDataRole.UserRole) if current else None
        self.files.blockSignals(True);self.files.clear();self.records={record['key']:record for record in deepcopy(records)}
        for record in records:
            item=QListWidgetItem(record['name']);item.setData(Qt.ItemDataRole.UserRole,record['key']);self.files.addItem(item)
        self.files.blockSignals(False)
        current_item=None
        for index in range(self.files.count()):
            item=self.files.item(index);key=item.data(Qt.ItemDataRole.UserRole)
            if key in selected:item.setSelected(True)
            if key==current_key:current_item=item
        if self.files.count():
            current_item=current_item or self.files.item(0)
            if not self.files.selectedItems():current_item.setSelected(True)
            self.files.setCurrentItem(current_item,QItemSelectionModel.SelectionFlag.NoUpdate)
        self.preview_current();self.update_controls()

    def remove_selected(self):
        if not self.files.selectedItems():return
        self.history.append(self.snapshot())
        for item in self.files.selectedItems():self.records.pop(item.data(Qt.ItemDataRole.UserRole));self.files.takeItem(self.files.row(item))
        self.preview_current();self.update_controls()

    def undo_edit(self):
        if self.active or not self.history:return
        self.restore(self.history.pop());self.status.setText('Edit undone.')

    def is_edit(self):return self.current_action()['id'] in PDF_EDITS

    def run_action(self):
        if self.active:return
        if not self.is_edit():return
        action=self.current_action()['id'];entries=self.snapshot() if action=='combine' else deepcopy(self.selected_records())
        if len(entries)<self.current_action()['minimum']:return
        settings=self.options()
        if settings.get('password'):
            for entry in entries:
                if not entry.get('password'):entry['password']=settings['password']
        directory=tempfile.mkdtemp(prefix='edit-',dir=self.session.name)
        self.pending=dict(before=self.snapshot(),entries=entries,action=action,settings=settings,outputs=[],ok=False,cancelled=False)
        self.start_worker('_edit',dict(action=action,settings=settings,directory=directory),[entry['path'] for entry in entries],plan=entries)

    def handle_event(self,event):
        if self.mode=='_edit' and self.pending:
            if event['type']=='row' and event['status']=='Saved':return
            if event['type']=='draft':self.pending['outputs'].append(event['path']);return
            if event['type']=='done':self.pending['ok']=not event.get('failures',0)
            if event['type']=='cancelled':self.pending['cancelled']=True
        if self.mode=='_save' and event['type']=='row' and event['status']=='Saved' and self.pending:
            for record in self.pending['entries']:
                if record['target']==event['path']:self.saved[record['key']]=self.signature(record)
        super().handle_event(event)
        if event['type']=='row' and self.mode!='_save':
            record=next((record for record in self.records.values() if record['path']==event['path']),None)
            if record:self.results.topLevelItem(self.results.topLevelItemCount()-1).setText(0,record['name'])
        if event['type']=='cancelled' and self.mode=='_edit':self.status.setText('Cancelled. Your draft is unchanged.')
        if event['type'] in ('row','error','log') or event.get('error'):self.results_panel.show()
        if event['type']=='row':
            self.results_empty.hide()
            row=self.results.topLevelItem(self.results.topLevelItemCount()-1)
            row.setText(0,Path(row.text(0)).name)
        if event['type']=='done' and not self.results.topLevelItemCount():self.results_empty.setText('No results.')

    def worker_finished(self,code,status):
        pending=self.pending
        # Consume the last output before inspecting success; defer close until draft adoption.
        self.read_output();self.read_error();self.active=False
        if self.mode=='_edit' and pending:
            expected=1 if pending['action']=='combine' else len(pending['entries'])
            if not code and not self.errors and pending['ok'] and not pending['cancelled'] and len(pending['outputs'])==expected:
                self.history.append(pending['before']);records=self.snapshot();action=pending['action']
                if action=='combine':
                    record=deepcopy(pending['entries'][0]);record.update(path=pending['outputs'][0],name='Combined documents.pdf',password='',edits=['Combined documents'])
                    records=[record]
                else:
                    updated={}
                    for record,path in zip(pending['entries'],pending['outputs']):
                        record['path']=path;record['edits'].append(self.current_action()['title'])
                        if action=='protect':record['password']=pending['settings']['new_password']
                        if action=='unprotect':record['password']=''
                        updated[record['key']]=record
                    records=[updated.get(record['key'],record) for record in records]
                self.restore(records);self.results_panel.hide();self.status.setText('Draft updated. Export when you’re ready.')
            elif not self.errors and not pending['cancelled']:self.status.setText('Edit did not finish. Your draft is unchanged.')
        if self.mode=='_save' and not code and not self.errors:
            self.status.setText(f'Exported {len(pending["entries"])} '+('copy.' if len(pending['entries'])==1 else 'copies.'))
        if not self.results.topLevelItemCount():self.results_empty.setText('Operation failed.' if self.errors or code else 'No results.')
        if self.log.toPlainText():self.results_panel.show()
        self.pending=None;self.progress.setRange(0,100);self.progress.setValue(0);self.update_controls()
        if self.closing:
            if self.mode=='_save' and (code or self.errors):self.closing=False
            else:self.close()

    def export_files(self,entries):
        if self.active or not entries:return
        if len(entries)==1:
            record=entries[0];suggestion=Path(record['original']).parent/(Path(record['name']).stem+' [edited].pdf')
            target,_=QFileDialog.getSaveFileName(self,'Export',str(suggestion),'PDF (*.pdf)')
        else:target=QFileDialog.getExistingDirectory(self,'Export copies to folder')
        if target:self.save_to(target,entries)

    def save_to(self,target,entries=None):
        if self.active:return
        entries=deepcopy(self.selected_records() if entries is None else entries)
        if not entries:return
        target=Path(target)
        for record in entries:record['target']=str(target/(Path(record['name']).stem+' [edited].pdf') if target.is_dir() else target)
        if len(entries)>1 and not target.is_dir():self.status.setText('Choose a folder for multiple copies.');return
        self.pending=dict(entries=entries)
        self.start_worker('_save',{},[record['path'] for record in entries],plan=entries)

    def preview_current(self,*_args):
        if self._building:return
        self.results_panel.hide()
        item=self.files.currentItem();record=self.records.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
        path=Path(record['path']) if record else None;self.preview_path=path;self.preview_stack.setCurrentWidget(self.empty_preview)
        if self.document is not None:
            self.document.close();self.document.setPassword('');self.password_panel.hide();self.page_number.setRange(1,1);self.page_total.setText('/ 0')
            for widget in self.pdf_controls:widget.setEnabled(False)
            self.preview_password.clear();self.preview_password_value=record.get('password','') if record else '';self.preview_needs_password=False
        self.preview_meta.clear();self.preview_name.setText(record['name'] if record else 'Preview');self.action_changed()
        if path is None:self.empty_preview.setText('Open a PDF to get started.');return
        self.document.setPassword(self.preview_password_value);self.document.load(str(path))


    def build_pdf_preview(self,layout):
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPdfWidgets import QPdfView
        self.document=QPdfDocument(self);self.pdf_view=QPdfView();self.pdf_view.setDocument(self.document)
        self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage);self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)
        self.preview_stack.addWidget(self.pdf_view)
        controls=QHBoxLayout();previous=QPushButton(line_icon('previous'),'');previous.setAccessibleName('Previous page');previous.clicked.connect(lambda:self.jump_page(self.page_number.value()-2));controls.addWidget(previous)
        self.page_number=QSpinBox();self.page_number.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons);self.page_number.setFixedWidth(54);self.page_number.setRange(1,1);self.page_number.valueChanged.connect(lambda value:self.jump_page(value-1));controls.addWidget(self.page_number)
        self.page_total=QLabel('/ 0');controls.addWidget(self.page_total)
        next_page=QPushButton(line_icon('next'),'');next_page.setAccessibleName('Next page');next_page.clicked.connect(lambda:self.jump_page(self.page_number.value()));controls.addWidget(next_page);controls.addStretch()
        self.zoom=QComboBox();self.zoom.addItems(['Fit page','Fit width','100%']);self.zoom.currentIndexChanged.connect(self.set_pdf_zoom);controls.addWidget(self.zoom);layout.addLayout(controls)
        self.pdf_controls=[previous,self.page_number,next_page,self.zoom]
        for widget in self.pdf_controls:widget.setEnabled(False)
        self.password_panel=QWidget();password_layout=QHBoxLayout(self.password_panel);password_layout.setContentsMargins(0,0,0,0)
        self.preview_password=QLineEdit();self.preview_password.setEchoMode(QLineEdit.EchoMode.Password);self.preview_password.setPlaceholderText('Document password');self.preview_password.returnPressed.connect(self.unlock_pdf);password_layout.addWidget(self.preview_password,1)
        unlock=QPushButton('Unlock preview');unlock.clicked.connect(self.unlock_pdf);password_layout.addWidget(unlock);layout.addWidget(self.password_panel);self.password_panel.hide()
        self.document.statusChanged.connect(self.pdf_status);self.document.passwordRequired.connect(self.password_required)
        self.pdf_view.pageNavigator().currentPageChanged.connect(self.page_changed)

    def pdf_status(self,status):
        from PySide6.QtPdf import QPdfDocument
        if status==QPdfDocument.Status.Ready:
            count=self.document.pageCount();self.page_number.setRange(1,max(1,count));self.page_number.setValue(1);self.page_total.setText(f'/ {count}')
            try:size=self.preview_path.stat().st_size
            except OSError:size=0
            self.preview_meta.setText(f'{count} page'+('s' if count!=1 else '')+' · '+size_label(size))
            for widget in self.pdf_controls:widget.setEnabled(True)
            self.preview_stack.setCurrentWidget(self.pdf_view);self.password_panel.hide();self.jump_page(0)
            self.action_changed()
        elif status==QPdfDocument.Status.Error:
            self.empty_preview.setText('Preview unavailable. Protected PDFs need their password.')
            self.preview_stack.setCurrentWidget(self.empty_preview)

    def password_required(self):
        self.preview_needs_password=True;self.password_panel.show();self.empty_preview.setText('This PDF is password protected.');self.action_changed()

    def unlock_pdf(self):
        if self.preview_path:
            self.preview_password_value=self.preview_password.text();self.document.setPassword(self.preview_password_value);self.document.load(str(self.preview_path))
            if self.document.pageCount() and self.files.currentItem():self.records[self.files.currentItem().data(Qt.ItemDataRole.UserRole)]['password']=self.preview_password_value

    def jump_page(self,index):
        if self.document.pageCount():
            index=max(0,min(index,self.document.pageCount()-1));self.pdf_view.pageNavigator().jump(index,QPointF(),self.pdf_view.zoomFactor())

    def page_changed(self,index):
        self.page_number.blockSignals(True);self.page_number.setValue(index+1);self.page_number.blockSignals(False)

    def set_pdf_zoom(self,index):
        from PySide6.QtPdfWidgets import QPdfView
        if index==2:self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom);self.pdf_view.setZoomFactor(1)
        else:self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView if index==0 else QPdfView.ZoomMode.FitToWidth)

    def closeEvent(self,event):
        if self.active:self.closing=True;self.cancel_work();event.ignore();return
        self.closing=False
        if self.dirty_records():
            answer=QMessageBox.question(self,'Unsaved edits','Export your changes before closing?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
            if answer==QMessageBox.StandardButton.Cancel:event.ignore();return
            if answer==QMessageBox.StandardButton.Save:
                self.export_files(self.dirty_records());self.closing=self.active;event.ignore();return
        if self.document is not None:self.document.close()
        self.session.cleanup();event.accept()
