"""A document editor with direct edits, contextual popovers and export profiles."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from pdf_drafts import PdfDraftDialog, line_icon, size_label
from tools_gui import ToolsDialog


class DocumentButton(QToolButton):
    def event(self,event):
        # The visible text names these actions; QAction's automatic tooltips add no information.
        if event.type()==QEvent.Type.ToolTip:return True
        return super().event(event)


class PdfEditor(PdfDraftDialog):
    def __init__(self,paths=()):
        self.command_id='inspect';self.command_settings={};self.command_title=None
        super().__init__(paths)

    @staticmethod
    def section(text):
        label=QLabel(text);font=label.font();font.setBold(True);label.setFont(font);return label

    def current_action(self):
        spec=dict(next(spec for spec in self.module.ACTIONS if spec['id']==self.command_id))
        if self.command_title:spec['title']=self.command_title
        return spec

    def options(self,state=None):
        settings=dict(self.command_settings)
        records=self.selected_records()
        if records:settings.setdefault('password',records[0].get('password',''))
        return settings

    def set_command(self,action,settings=None,title=None):
        self.command_id=action;self.command_settings=dict(settings or {});self.command_title=title

    def make_action(self,menu,key,text,callback):
        action=menu.addAction(text);action.setObjectName('pdf_'+key)
        action.triggered.connect(lambda _checked=False:callback());self.actions[key]=action
        return action

    def menu_button(self,text,icon,menu=None):
        button=DocumentButton();button.setText(text);button.setIcon(line_icon(icon))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if menu is not None:button.setMenu(menu);button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return button

    def build_ui(self,title,icon):
        self.document=None;self.preview_path=None;self.preview_password_value='';self.preview_needs_password=False
        self.actions={};self.toolbar_controls=[];self.resize(1280,850);self.setMinimumSize(1020,650)
        self.setStyleSheet('''
            QLabel[muted="true"] { color: palette(placeholder-text); }
            QToolButton { padding: 7px 10px; }
            QToolButton[primary="true"]:enabled { background: palette(highlight); color: palette(highlighted-text); border-radius: 6px; }
            QLineEdit, QComboBox { min-height: 28px; }
        ''')
        layout=QVBoxLayout(self);layout.setContentsMargins(20,18,20,14);layout.setSpacing(14)
        header=QHBoxLayout();titles=QVBoxLayout();heading=self.section(title)
        font=heading.font();font.setPointSize(font.pointSize()+7);heading.setFont(font);titles.addWidget(heading)
        self.selection_summary=QLabel();self.selection_summary.setProperty('muted',True);titles.addWidget(self.selection_summary);header.addLayout(titles,1)
        add_menu=QMenu(self);add_action=QAction(line_icon('add'),'Add PDFs…',self);add_action.triggered.connect(self.add_files)
        add_menu.addAction(add_action);self.add_folder=add_menu.addAction('Add folder…');self.add_folder.triggered.connect(self.add_directory)
        self.add=self.menu_button('Add PDFs…','add');self.add.setDefaultAction(add_action);self.add.setMenu(add_menu)
        self.add.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup);header.addWidget(self.add)
        self.undo_button=QPushButton(line_icon('undo'),'Undo');self.undo_button.clicked.connect(self.undo_edit);header.addWidget(self.undo_button)
        self.export_menu=QMenu(self);self.make_action(self.export_menu,'export','Export current PDF…',self.export_current)
        default=QAction('Export…',self);default.triggered.connect(self.export_current);self.actions['export_default']=default
        self.export_menu.addSeparator()
        self.make_action(self.export_menu,'web','For the web…',lambda:self.export_variant('linearize',{},'Web'))
        smaller=self.export_menu.addMenu('Smaller PDF')
        for dpi,title in [('150','Screen · 150 dpi…'),('300','Print · 300 dpi…')]:
            self.make_action(smaller,'dpi_'+dpi,title,lambda dpi=dpi:self.export_variant('reduce',{'dpi':dpi},dpi+' dpi'))
        self.make_action(self.export_menu,'pdfa','Archival PDF/A-2b…',self.archival_export)
        self.export_menu.addSeparator()
        self.make_action(self.export_menu,'pages','Selected pages…',self.pages_export)
        self.make_action(self.export_menu,'images','Embedded images…',lambda:self.export_variant('images',{},'Images'))
        self.export_button=DocumentButton();self.export_button.setDefaultAction(default);self.export_button.setText('Export…')
        self.export_button.setMenu(self.export_menu);self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup);self.export_button.setProperty('primary',True);header.addWidget(self.export_button);layout.addLayout(header)
        toolbar=QHBoxLayout()
        rotation=QMenu(self);self.make_action(rotation,'rotate_page_right','Page · 90° right',lambda:self.rotate(90))
        rotate_default=QAction(line_icon('rotate'),'Rotate page',self);rotate_default.triggered.connect(lambda:self.rotate(90));self.actions['rotate_default']=rotate_default
        self.make_action(rotation,'rotate_page_left','Page · 90° left',lambda:self.rotate(270))
        self.make_action(rotation,'rotate_page_half','Page · 180°',lambda:self.rotate(180));rotation.addSeparator()
        self.make_action(rotation,'rotate_all_right','All pages · 90° right',lambda:self.rotate(90,True))
        self.make_action(rotation,'rotate_all_left','All pages · 90° left',lambda:self.rotate(270,True))
        self.make_action(rotation,'rotate_all_half','All pages · 180°',lambda:self.rotate(180,True))
        self.rotate_button=self.menu_button('Rotate','rotate');self.rotate_button.setDefaultAction(rotate_default)
        self.rotate_button.setText('Rotate page');self.rotate_button.setMenu(rotation);self.rotate_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        toolbar.addWidget(self.rotate_button);self.toolbar_controls.append(self.rotate_button)
        self.watermark_button=self.menu_button('Watermark…','watermark');self.watermark_button.clicked.connect(self.watermark)
        toolbar.addWidget(self.watermark_button);self.toolbar_controls.append(self.watermark_button)
        security=QMenu(self);self.make_action(security,'protect','Set password…',self.protect)
        self.make_action(security,'unprotect','Remove password',lambda:self.apply_edit('unprotect',{},'Removed password'))
        self.security_button=self.menu_button('Password','protect',security);toolbar.addWidget(self.security_button);self.toolbar_controls.append(self.security_button)
        toolbar.addStretch();layout.addLayout(toolbar)
        self.splitter=QSplitter();sidebar=QWidget();sidebar.setMinimumWidth(190);sidebar.setMaximumWidth(260)
        side=QVBoxLayout(sidebar);side.setContentsMargins(0,0,12,0);file_header=QHBoxLayout();file_header.addWidget(self.section('Documents'),1)
        self.remove_button=QPushButton(line_icon('remove'),'');self.remove_button.setAccessibleName('Remove document');self.remove_button.setFixedWidth(30);self.remove_button.clicked.connect(self.remove_selected);file_header.addWidget(self.remove_button);side.addLayout(file_header)
        self.files=QListWidget();self.files.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.files.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.files.itemSelectionChanged.connect(self.invalidate_preview);self.files.currentItemChanged.connect(self.preview_current);self.files.model().rowsMoved.connect(self.invalidate_preview);side.addWidget(self.files,1)
        self.combine_button=QPushButton(line_icon('combine'),'Combine documents');self.combine_button.clicked.connect(lambda:self.apply_edit('combine',{},'Combined documents'));side.addWidget(self.combine_button)
        self.splitter.addWidget(sidebar)
        self.preview_page=QWidget();self.preview_page.setMinimumWidth(320);preview_layout=QVBoxLayout(self.preview_page);preview_layout.setContentsMargins(8,0,8,0)
        self.preview_name=self.section('Document');self.preview_name.setTextFormat(Qt.TextFormat.PlainText);preview_layout.addWidget(self.preview_name)
        self.preview_meta=QLabel();self.preview_meta.setProperty('muted',True);preview_layout.addWidget(self.preview_meta)
        self.preview_stack=QStackedWidget();self.empty_preview=QLabel('Open a PDF to get started.');self.empty_preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview_stack.addWidget(self.empty_preview)
        self.build_pdf_preview(preview_layout);preview_layout.addWidget(self.preview_stack,1);self.splitter.addWidget(self.preview_page)
        right=QWidget();details_layout=QVBoxLayout(right);details_layout.setContentsMargins(16,0,0,0)
        metadata_header=QHBoxLayout();metadata_header.addWidget(self.section('Document'),1)
        metadata_action=QAction(line_icon('metadata'),'Remove metadata',self);metadata_action.setObjectName('pdf_metadata')
        metadata_action.triggered.connect(lambda:self.apply_edit('metadata',{},'Removed metadata'));self.actions['metadata']=metadata_action
        self.metadata_button=self.menu_button('Remove metadata','metadata');self.metadata_button.setDefaultAction(metadata_action)
        metadata_header.addWidget(self.metadata_button);details_layout.addLayout(metadata_header)
        self.details=QTreeWidget();self.details.setHeaderLabels(['Property','Value']);self.details.setRootIsDecorated(False);self.details.setColumnWidth(0,120);self.details.setMaximumHeight(260);details_layout.addWidget(self.details)
        signatures_action=QAction(line_icon('signatures'),'Digital signatures',self);signatures_action.setObjectName('pdf_signatures')
        signatures_action.triggered.connect(self.signatures);self.actions['signatures']=signatures_action
        self.signatures_button=self.menu_button('Digital signatures','signatures');self.signatures_button.setDefaultAction(signatures_action)
        details_layout.addWidget(self.signatures_button)
        self.change_list=QLabel();self.change_list.setWordWrap(True);self.change_list.setProperty('muted',True);details_layout.addWidget(self.change_list)
        self.results_panel=QWidget();results_layout=QVBoxLayout(self.results_panel);results_layout.setContentsMargins(0,12,0,0)
        self.results_title=self.section('Results');results_layout.addWidget(self.results_title)
        self.results=QTreeWidget();self.results.setHeaderLabels(['File','Result','Details']);self.results.setRootIsDecorated(False);self.results.setColumnWidth(0,100);self.results.setColumnWidth(1,85);self.results.setWordWrap(True);self.results.setMinimumHeight(160);self.results.itemDoubleClicked.connect(self.open_result);results_layout.addWidget(self.results,1)
        self.results_empty=QLabel();results_layout.addWidget(self.results_empty)
        result_actions=QHBoxLayout()
        for name,callback in [('Open',self.open_result),('Open folder',self.reveal_result),('Copy',self.copy_results)]:
            button=QPushButton(name);button.clicked.connect(callback);result_actions.addWidget(button)
        results_layout.addLayout(result_actions)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(120);results_layout.addWidget(self.log);self.log.hide();self.results_panel.hide()
        details_layout.addWidget(self.results_panel,1);details_layout.addStretch()
        self.inspector=QScrollArea();self.inspector.setWidgetResizable(True);self.inspector.setFrameShape(QScrollArea.Shape.NoFrame);self.inspector.setMinimumWidth(320);self.inspector.setMaximumWidth(620);self.inspector.setWidget(right);self.splitter.addWidget(self.inspector)
        self.splitter.setStretchFactor(1,3);self.splitter.setStretchFactor(2,2);self.splitter.setSizes([210,650,380]);layout.addWidget(self.splitter,1)
        footer=QHBoxLayout();self.status=QLabel('Ready');self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);footer.addWidget(self.status,1)
        self.progress=QProgressBar();self.progress.setMaximumWidth(180);self.progress.setTextVisible(False);footer.addWidget(self.progress)
        self.cancel=QPushButton('Cancel');self.cancel.clicked.connect(self.cancel_work);footer.addWidget(self.cancel);layout.addLayout(footer)
        self.apply=QPushButton(self);self.apply.hide()

    def action_changed(self,*_args):
        if not self._building:self.update_controls()

    def update_controls(self):
        if self._building:return
        selected=bool(self.selected_records());available=not self.active and selected
        ready=bool(self.document.pageCount())
        for widget in self.toolbar_controls:widget.setEnabled(available and ready)
        for widget in (self.files,self.add,self.add_folder,self.remove_button):widget.setEnabled(not self.active)
        self.combine_button.setEnabled(not self.active and self.files.count()>1)
        self.combine_button.setText(f'Combine {self.files.count()} documents' if self.files.count()>1 else 'Combine documents')
        self.export_button.setEnabled(available);self.undo_button.setEnabled(not self.active and bool(self.history))
        # Disable QAction shortcuts/menu triggers as well as their visible buttons.
        for key,action in self.actions.items():action.setEnabled(available and (ready or key in ('export','export_default')))
        if selected:
            record=self.selected_records()[0];self.actions['unprotect'].setEnabled(available and ready and bool(record.get('password')))
        self.cancel.setVisible(self.active);self.cancel.setEnabled(self.active);self.progress.setVisible(self.active)
        self.update_selection_summary()

    def update_selection_summary(self):
        count=self.files.count();dirty=len(self.dirty_records())
        self.selection_summary.setText(f'{count} document'+('s' if count!=1 else '')+(f' · {dirty} unsaved' if dirty else ''))
        records=self.selected_records();edits=records[0].get('edits',[]) if records else []
        self.change_list.setText(f'{len(edits)} edit'+('s' if len(edits)!=1 else '')+' · Export to save a copy.' if edits else '')
        self.change_list.setVisible(bool(edits))

    def append_paths(self,paths):
        super().append_paths(paths)
        item=self.files.currentItem()
        if item:self.files.setCurrentItem(item,self.files.selectionModel().SelectionFlag.ClearAndSelect)

    def preview_current(self,*args):
        super().preview_current(*args)
        if not self._building:self.update_details()

    def pdf_status(self,status):
        super().pdf_status(status)
        if not self._building:self.update_details()

    def update_details(self):
        from PySide6.QtPdf import QPdfDocument
        self.details.clear();records=self.selected_records()
        if not records:return
        record=records[0]
        def add(name,value):self.details.addTopLevelItem(QTreeWidgetItem([name,str(value)]))
        add('Name',record['name'])
        try:add('Size',size_label(Path(record['path']).stat().st_size))
        except OSError:pass
        if self.document.status()==QPdfDocument.Status.Ready:
            add('Pages',self.document.pageCount());add('Password','Protected' if record.get('password') else 'None')
            for key,label in [('Title','Title'),('Author','Author'),('Subject','Subject'),('Creator','Created with')]:
                value=self.document.metaData(getattr(QPdfDocument.MetaDataField,key))
                if value:add(label,value)
        elif self.preview_needs_password:add('Password','Unlock to edit')

    def apply_edit(self,action,settings=None,title=None):
        if self.active or not self.selected_records():return
        page=self.pdf_view.pageNavigator().currentPage()
        self.set_command(action,settings,title);PdfDraftDialog.run_action(self)
        if self.pending:self.pending['page']=0 if action=='combine' else page

    def undo_edit(self):
        page=self.pdf_view.pageNavigator().currentPage();super().undo_edit();self.jump_page(page)

    def rotate(self,angle,all_pages=False):
        pages='' if all_pages else str(self.pdf_view.pageNavigator().currentPage()+1)
        self.apply_edit('rotate',{'angle':str(angle),'pages':pages},'Rotated all pages' if all_pages else f'Rotated page {pages}')

    def popover(self,title,fields,button_text,anchor=None):
        """A small keyboard-accessible settings popup; closing it makes no edit."""
        popup=QDialog(self,Qt.WindowType.Dialog|Qt.WindowType.FramelessWindowHint);popup.setWindowTitle(title);popup.setMinimumWidth(330)
        body=QVBoxLayout(popup);body.addWidget(self.section(title));form=QFormLayout();body.addLayout(form);controls={}
        for name,label,kind,default,choices in fields:
            if kind=='choice':
                control=QComboBox()
                for text,value in choices:control.addItem(text,value)
                control.setCurrentIndex(max(0,control.findData(default)));control.tool_value=control.currentData
            elif kind=='file':
                control=QWidget();line=QHBoxLayout(control);line.setContentsMargins(0,0,0,0);edit=QLineEdit(str(default));line.addWidget(edit)
                browse=QPushButton('Choose…');line.addWidget(browse);browse.clicked.connect(lambda _checked=False,edit=edit:self.browse_field(edit,'file'));control.tool_value=edit.text
            else:
                control=QLineEdit(str(default));control.tool_value=control.text
                if kind=='password':control.setEchoMode(QLineEdit.EchoMode.Password)
                if name=='pages':control.setPlaceholderText('All pages, or 1-5,7')
            control.setObjectName('pdf_option_'+name);form.addRow(label,control);controls[name]=control
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel);accept=buttons.addButton(button_text,QDialogButtonBox.ButtonRole.AcceptRole)
        error=QLabel();error.setWordWrap(True);body.addWidget(error);error.hide()
        def validate():
            valid=all(bool(controls[key].tool_value()) for key in ('new_password','watermark') if key in controls)
            error.hide()
            if 'pages' in controls:
                from pdf_tasks import page_selection
                try:page_selection(controls['pages'].tool_value(),self.document.pageCount())
                except ValueError as message:valid=False;error.setText(str(message));error.show()
            accept.setEnabled(valid);popup.adjustSize()
        for control in controls.values():
            edits=[control] if isinstance(control,QLineEdit) else control.findChildren(QLineEdit)
            for edit in edits:edit.textChanged.connect(validate)
        validate()
        accept.setDefault(True);buttons.accepted.connect(popup.accept);buttons.rejected.connect(popup.reject);body.addWidget(buttons)
        anchor=anchor or self.export_button;popup.adjustSize();popup.move(anchor.mapToGlobal(QPoint(0,anchor.height()+4)))
        if popup.exec()!=QDialog.DialogCode.Accepted:return None
        return {name:control.tool_value() for name,control in controls.items()}

    def protect(self):
        settings=self.popover('Set password',[('new_password','Password','password','',())],'Apply',self.security_button)
        if settings is not None:self.apply_edit('protect',settings,'Set password')

    def watermark(self):
        settings=self.popover('Watermark',[
            ('watermark','PDF','file','',()),('layer','Position','choice','over',[('Over pages','over'),('Under pages','under')])],
            'Apply',self.watermark_button)
        if settings is not None:self.apply_edit('watermark',settings,'Added watermark')

    def signatures(self):
        if self.active or not self.selected_records():return
        self.set_command('signatures');self.pending=None;self.start_worker('signatures',self.options(),self.selected())

    def export_current(self):
        if not self.active:self.export_files(self.selected_records())

    def pages_export(self):
        settings=self.popover('Export pages',[
            ('pages','Pages','text','',()),('split_mode','Export as','choice','selection',[
                ('One PDF','selection'),('Separate PDFs','separate')])],'Export…')
        if settings is not None:self.export_variant('split',settings,'Selected pages')

    def archival_export(self):
        self.export_variant('pdfa',{},'PDF-A')

    def export_variant(self,variant,settings,suffix):
        if self.active or not self.selected_records():return
        record=deepcopy(self.selected_records()[0]);folder_output=variant=='images' or (variant=='split' and settings.get('split_mode')=='separate')
        initial=Path(record['original']).parent
        if folder_output:target=QFileDialog.getExistingDirectory(self,'Export to folder',str(initial))
        else:
            suggested=initial/(Path(record['name']).stem+' ['+suffix+'].pdf')
            target,_=QFileDialog.getSaveFileName(self,'Export',str(suggested),'PDF (*.pdf)')
        if target:self.export_variant_to(variant,settings,target,record)

    def export_variant_to(self,variant,settings,target,record=None):
        if self.active or (record is None and not self.selected_records()):return
        record=deepcopy(record or self.selected_records()[0]);record['target']=str(target)
        self.set_command(variant,settings)
        self.pending=dict(entries=[record],full=variant in ('linearize','reduce','pdfa'))
        self.start_worker('_pdf_export',dict(variant=variant,settings=settings,directory=self.session.name),[record['path']],plan=[record])

    def start_worker(self,action,options,paths,plan=None):
        ToolsDialog.start_worker(self,action,options,paths,plan)
        self.results_panel.setVisible(action!='_edit');self.results_empty.setText('Working…');self.results_empty.show()
        self.results_title.setText('Exported files' if action in ('_save','_pdf_export') else 'Results')
        self.results_title.setVisible(action!='signatures')
        self.results.setColumnHidden(0,action=='signatures');self.results.setHeaderLabels(['File','Result','Details'])

    def handle_event(self,event):
        if self.mode=='_pdf_export':
            if event['type']=='draft':return
            if event['type']=='row' and event.get('status')=='Saved':
                if Path(event['path']).is_relative_to(self.session.name):return
                if self.pending and self.pending['full']:
                    record=self.pending['entries'][0];self.saved[record['key']]=self.signature(record)
        super().handle_event(event)

    def worker_finished(self,code,status):
        mode=self.mode;page=self.pending.get('page',0) if self.pending else 0
        super().worker_finished(code,status)
        if mode=='_edit' and not code and not self.errors:self.jump_page(page)
        self.update_details()
        if mode=='_pdf_export' and not code and not self.errors:self.status.setText('Exported.')
