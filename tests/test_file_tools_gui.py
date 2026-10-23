"""Exercise the native dialogs, their worker protocol and rename review flow."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[1]
MODULES=['modules/files/tools/common','modules/files/tools/general','modules/files/tools/encryption','modules/media/tools/pdf']
LIBS=[REPO/module/'files/usr/local/lib/desktop-file-tools' for module in MODULES]


class FileToolDialogsTests(unittest.TestCase):
    def test_pdf_drafts_preview_navigate_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            script='''import os,time
from pathlib import Path
import pikepdf
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QAbstractSpinBox
from pdf_gui import PdfEditor
root=Path(os.environ['TOOLS_FIXTURE']);app=QApplication([])
def until(condition,w):
 deadline=time.monotonic()+25
 while not condition():
  app.processEvents();time.sleep(.005)
  assert time.monotonic()<deadline,w.status.text()+w.log.toPlainText()
def run(w):
 w.run_button.click();until(lambda:not w.active,w)
 assert not w.errors,w.log.toPlainText()
source=root/'Report.pdf'
with pikepdf.Pdf.new() as pdf:
 pdf.add_blank_page();pdf.add_blank_page();pdf.add_blank_page();pdf.docinfo['/Title']='Private';pdf.save(source)
 pdf.save(root/'Protected.pdf',encryption=pikepdf.Encryption(user='secret',owner='owner'))
original=source.read_bytes()
w=PdfEditor([source]);w.show();until(lambda:w.document.pageCount()==3,w)
assert w.preview_stack.currentWidget() is w.pdf_view
assert w.page_number.buttonSymbols()==QAbstractSpinBox.ButtonSymbols.NoButtons
w.page_number.setValue(2);app.processEvents();assert w.pdf_view.pageNavigator().currentPage()==1
# Consecutive edits affect the draft; nothing is written beside the original.
w.rotate_button.click();until(lambda:not w.active,w);assert not w.errors,w.log.toPlainText()
w.metadata_button.click();until(lambda:not w.active,w);assert not w.errors,w.log.toPlainText()
assert w.document.pageCount()==3 and w.preview_page.isVisible() and not w.results_panel.isVisible()
with pikepdf.Pdf.open(w.selected()[0]) as pdf:
 assert int(pdf.pages[1].get('/Rotate',0))==90 and '/Title' not in pdf.docinfo
assert list(root.glob('*[[]*'))==[] and source.read_bytes()==original
# Undo exactly one edit, then repeat it and save once.
w.undo_edit()
with pikepdf.Pdf.open(w.selected()[0]) as pdf:
 assert int(pdf.pages[1].get('/Rotate',0))==90 and pdf.docinfo['/Title']=='Private'
w.metadata_button.click();until(lambda:not w.active,w);w.save_to(root/'Edited.pdf');until(lambda:not w.active,w)
assert not w.dirty_records() and w.export_button.isEnabled()
with pikepdf.Pdf.open(root/'Edited.pdf') as pdf:assert '/Title' not in pdf.docinfo
# Saving over an existing file is refused and preserves the draft.
w.actions['rotate_page_right'].trigger();until(lambda:not w.active,w);before=w.selected()
existing=(root/'Edited.pdf').read_bytes();w.save_to(root/'Edited.pdf');until(lambda:not w.active,w)
assert w.errors and w.selected()==before and (root/'Edited.pdf').read_bytes()==existing and w.dirty_records()
w.undo_edit();assert not w.dirty_records()
# A cancelled edit cannot be adopted.
w.actions['rotate_page_right'].trigger();w.cancel_work();until(lambda:not w.active,w);assert not w.dirty_records()
# A failed edit never replaces the good draft or adds an undo entry.
before=w.selected();depth=len(w.history)
w.apply_edit('protect',{'new_password':''});until(lambda:not w.active,w)
assert w.errors and w.selected()==before and len(w.history)==depth
w.close()
# Each document has its own unlock state; combine uses every sidebar item in order.
w=PdfEditor([source,root/'Protected.pdf']);w.show();app.processEvents()
w.files.setCurrentRow(1);until(lambda:w.password_panel.isVisible(),w)
w.preview_password.setText('secret');w.unlock_pdf();until(lambda:w.document.pageCount()==3,w)
w.actions['rotate_all_right'].trigger();until(lambda:not w.active,w);assert not w.errors,w.log.toPlainText()
with pikepdf.Pdf.open(w.selected()[0],password='secret') as pdf:assert pdf.is_encrypted
w.combine_button.click();until(lambda:not w.active,w);assert not w.errors,w.log.toPlainText()
assert w.files.count()==1 and w.document.pageCount()==6
with pikepdf.Pdf.open(w.selected()[0]) as pdf:
 assert int(pdf.pages[0].get('/Rotate',0))==0 and int(pdf.pages[3].get('/Rotate',0))==90
w.undo_edit();assert w.files.count()==2
w.combine_button.click();until(lambda:not w.active,w);assert not w.errors,w.log.toPlainText()
w.save_to(root/'Combined.pdf');until(lambda:not w.active,w);assert not w.errors;w.close()
# Closing protects unsaved drafts; Save finishes before the temporary session is removed.
from unittest.mock import patch
from PySide6.QtWidgets import QMessageBox
w=PdfEditor([source]);w.show();app.processEvents();w.rotate_button.click();until(lambda:not w.active,w);draft=Path(w.selected()[0])
with patch('pdf_drafts.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel):w.close()
assert w.isVisible() and draft.exists()
with patch('pdf_drafts.QMessageBox.question',return_value=QMessageBox.StandardButton.Save), patch('pdf_drafts.QFileDialog.getSaveFileName',return_value=(str(root/'Close-save.pdf'),'')):
 w.close()
until(lambda:not w.active,w)
assert not w.isVisible() and (root/'Close-save.pdf').exists() and not draft.exists()
'''
            result=subprocess.run([sys.executable,'-c',script],env=dict(os.environ,QT_QPA_PLATFORM='offscreen',
                PYTHONPATH=os.pathsep.join(map(str,LIBS)),TOOLS_FIXTURE=directory),capture_output=True,text=True,timeout=100)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_pdf_editor_toolbar_popovers_and_export_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            script='''import os,time
from pathlib import Path
from unittest.mock import patch
import pikepdf
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QLineEdit,QComboBox,QTreeWidget,QTabWidget
from pdf_gui import PdfEditor
root=Path(os.environ['TOOLS_FIXTURE']);app=QApplication([])
def settle():
 for _ in range(4):app.processEvents()
def wait(w):
 end=time.monotonic()+35
 while w.active:
  settle();time.sleep(.005);assert time.monotonic()<end,w.status.text()+w.log.toPlainText()
 assert not w.errors,w.log.toPlainText()
 settle()
errors=[]
def popup(values=None,cancel=False,invalid_pages=False):
 def respond():
  window=app.activeModalWidget()
  try:
   assert window is not None,'Popover did not open'
   box=window.findChild(QDialogButtonBox)
   accept=next(button for button in box.buttons() if box.buttonRole(button)==QDialogButtonBox.ButtonRole.AcceptRole)
   if cancel:window.reject();return
   if invalid_pages:
    field=window.findChild(QLineEdit,'pdf_option_pages');field.setText('0');assert not accept.isEnabled()
   for key,value in (values or {}).items():
    field=window.findChild(QLineEdit,'pdf_option_'+key)
    if field is not None:field.setText(value);continue
    field=window.findChild(QComboBox,'pdf_option_'+key);field.setCurrentIndex(field.findData(value))
   assert accept.isEnabled()
   accept.click()
  except BaseException as error:
   errors.append(error)
   if window:window.reject()
 QTimer.singleShot(0,respond)
source=root/'Report.pdf'
with pikepdf.Pdf.new() as pdf:
 for _ in range(3):pdf.add_blank_page()
 pdf.docinfo['/Title']='Private title';pdf.save(source)
original=source.read_bytes()
w=PdfEditor([source]);w.show();settle()
assert not w.findChildren(QTabWidget) and not w.findChild(QTreeWidget,'toolBrowser')
assert 'find' not in w.actions and not any(key.startswith('ocr') for key in w.actions) and w.details.topLevelItemCount()>=4
assert {'web','dpi_150','dpi_300','pdfa','pages','images'}<=set(w.actions)
assert w.rotate_button.text()=='Rotate page'
# Immediate page edits keep the current page visible; the arrow also offers whole-document rotation.
w.jump_page(1);w.rotate_button.click();wait(w)
assert w.pdf_view.pageNavigator().currentPage()==1
with pikepdf.Pdf.open(w.selected()[0]) as pdf:assert [int(page.get('/Rotate',0)) for page in pdf.pages]==[0,90,0]
w.actions['rotate_all_left'].trigger();wait(w)
with pikepdf.Pdf.open(w.selected()[0]) as pdf:assert [int(page.get('/Rotate',0))%360 for page in pdf.pages]==[270,0,270]
w.undo_edit();assert w.pdf_view.pageNavigator().currentPage()==1
# Password settings run through the real popover and remain reversible.
popup({'new_password':'secret'});w.actions['protect'].trigger();assert not errors,errors;wait(w)
with pikepdf.Pdf.open(w.selected()[0],password='secret') as pdf:assert pdf.is_encrypted
assert w.actions['unprotect'].isEnabled()
w.undo_edit();assert not w.actions['unprotect'].isEnabled()
before=w.selected();history=len(w.history)
popup(cancel=True);w.watermark_button.click();assert not errors,errors
assert w.selected()==before and len(w.history)==history and not w.active
# Every export profile reads the draft; it does not become an edit or change the working PDF.
with patch('pdf_gui.QFileDialog.getSaveFileName',return_value=(str(root/'Copy.pdf'),'')):
 w.export_button.click()
wait(w);assert (root/'Copy.pdf').exists() and not w.dirty_records()
before=w.selected();history=len(w.history)
for key,name in [('web','Web.pdf'),('dpi_150','Screen.pdf'),('dpi_300','Print.pdf')]:
 with patch('pdf_gui.QFileDialog.getSaveFileName',return_value=(str(root/name),'')):
  w.actions[key].trigger()
 wait(w);assert (root/name).exists() and w.selected()==before and len(w.history)==history
with pikepdf.Pdf.open(root/'Web.pdf') as pdf:assert pdf.is_linearized
with patch('pdf_gui.QFileDialog.getSaveFileName',return_value=(str(root/'Archive.pdf'),'')):
 w.actions['pdfa'].trigger()
assert not errors,errors;wait(w)
with pikepdf.Pdf.open(root/'Archive.pdf') as pdf:
 with pdf.open_metadata() as metadata:assert str(metadata['pdfaid:part'])=='2' and str(metadata['pdfaid:conformance'])=='B'
# Page selection validates before enabling Export and can produce one file or a folder.
popup({'pages':'1,3','split_mode':'selection'},invalid_pages=True)
with patch('pdf_gui.QFileDialog.getSaveFileName',return_value=(str(root/'Selected.pdf'),'')):
 w.actions['pages'].trigger()
assert not errors,errors;wait(w)
with pikepdf.Pdf.open(root/'Selected.pdf') as pdf:assert len(pdf.pages)==2
folder=root/'Pages';folder.mkdir();popup({'pages':'2-3','split_mode':'separate'})
with patch('pdf_gui.QFileDialog.getExistingDirectory',return_value=str(folder)):
 w.actions['pages'].trigger()
assert not errors,errors;wait(w)
assert sorted(path.name for path in folder.rglob('*.pdf'))==['0002.pdf','0003.pdf']
folder=root/'Images';folder.mkdir()
with patch('pdf_gui.QFileDialog.getExistingDirectory',return_value=str(folder)):
 w.actions['images'].trigger()
wait(w);assert (folder/'Report [images]').is_dir()
w.signatures_button.click();wait(w)
assert w.results_panel.isVisible() and w.results.topLevelItemCount() and w.preview_page.isVisible()
assert w.selected()==before and source.read_bytes()==original and len(w.history)==history
w.close()
'''
            result=subprocess.run([sys.executable,'-c',script],env=dict(os.environ,QT_QPA_PLATFORM='offscreen',
                PYTHONPATH=os.pathsep.join(map(str,LIBS)),TOOLS_FIXTURE=directory),capture_output=True,text=True,timeout=120)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_real_dialogs_run_jobs_review_renames_and_copy_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            script='''
import os,time
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from tools_gui import ToolsDialog
root=Path(os.environ['TOOLS_FIXTURE'])
app=QApplication([])
def wait(w):
 deadline=time.monotonic()+15
 while w.active:
  app.processEvents();time.sleep(.005)
  assert time.monotonic()<deadline,w.status.text()
# Preview is a distinct operation; changing inputs invalidates it.
source=root/'some name.txt';source.write_text('hello')
w=ToolsDialog('file',[source]);w.show();app.processEvents()
state=w.pages[0];control=state['controls']['transform'];control.setCurrentIndex(control.findData('dashes'))
w.run_button.click();wait(w)
assert w.preview_plan and source.exists() and w.apply.isEnabled()
control.setCurrentIndex(control.findData('title'));assert not w.apply.isEnabled()
control.setCurrentIndex(control.findData('dashes'));w.run_button.click();wait(w);w.apply.click();wait(w)
renamed=root/'some-name.txt';assert renamed.read_text()=='hello' and not source.exists()
assert w.selected()==[str(renamed)]
w.copy_contents(w.selected());assert QApplication.clipboard().text()=='hello'
# Checksums work through the same asynchronous worker used in production.
w.tabs.setCurrentIndex(1);w.run_button.click();wait(w)
assert (root/'some-name.txt.sha256').exists()
w.close()
# All remaining dialogs really render their own controls and tabs.
for kind in ['pdf','encryption']:
 w=ToolsDialog(kind,load_keys=False);w.show();app.processEvents()
 assert w.tabs.count()>=2
 for state in w.pages:
  for index in range(state['combo'].count()):
   state['combo'].setCurrentIndex(index);app.processEvents()
 assert not w.run_button.isEnabled()
 w.close()
# Failed worker startup must restore the controls.
w=ToolsDialog('file',[renamed]);w.show()
w.active=True;w.update_controls()
w.process.start('/does-not-exist')
deadline=time.monotonic()+3
while w.process.errorString()=='Unknown error' and time.monotonic()<deadline:app.processEvents()
assert not w.active
assert w.run_button.isEnabled()
w.close()
'''
            result=subprocess.run([sys.executable,'-c',script],env=dict(os.environ,QT_QPA_PLATFORM='offscreen',
                PYTHONPATH=os.pathsep.join(map(str,LIBS)),TOOLS_FIXTURE=directory),capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
