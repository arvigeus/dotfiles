"""The actual project dashboard shows snapshots and launches only explicit actions."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / 'modules/dev/tools/projects/files/usr/local/lib/project-tools'


class ProjectDashboardTests(unittest.TestCase):
    def test_real_dialog_inspects_filters_refreshes_and_dispatches_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'Example'; root.mkdir()
            (root / 'package.json').write_text('{"name":"Cool <project>","description":"Example project", "dependencies":{"react":"*"}}')
            (root / 'mise.toml').write_text('''[tools]
node="26"
[tasks.check]
description="Check the project"
run="touch MUST_NOT_RUN"
[tasks.build]
description="Build the project"
run="touch MUST_NOT_RUN"
''')
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(LIB), PROJECT_TEST_ROOT=str(root))
            script = '''
import os, time
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea
from project_dashboard import ProjectDialog
root=Path(os.environ['PROJECT_TEST_ROOT'])
app=QApplication([])
calls=[]
w=ProjectDialog(root, lambda *args: calls.append(args))
w.show()
def wait_for(condition):
 deadline=time.monotonic()+10
 while not condition():
  app.processEvents()
  if time.monotonic()>deadline: raise AssertionError('Dashboard timed out: '+w.status.text())
  time.sleep(0.005)
wait_for(lambda:w.snapshot is not None)
assert w.name.text()=='Cool <project>'
assert w.name.textFormat()==Qt.TextFormat.PlainText
assert w.findChild(type(w.hero), 'tech_React') is not None
assert not w.git_card.isVisible() and not w.maintenance.isVisible()
assert w.mise_card.isVisible()
assert w.task_list.topLevelItemCount()==2
assert w.tool_list.topLevelItemCount()==1
# The first column and both tabs grow with the window rather than clipping at 180 px.
app.processEvents()
assert w.content.itemAt(1).layout().itemAt(0).widget() is w.mise_card
w.resize(1400,1200); app.processEvents()
assert w.task_list.height()>180
w.tabs.setCurrentIndex(1); app.processEvents()
assert w.tool_list.height()>180
assert abs(w.tool_list.height()-w.tabs.contentsRect().height())<50
w.tabs.setCurrentIndex(0)

assert not calls and not (root/'MUST_NOT_RUN').exists()
w.task_search.setText('check')
assert w.task_list.topLevelItem(0).isHidden()
assert not w.task_list.topLevelItem(1).isHidden()
w.task_list.setCurrentItem(w.task_list.topLevelItem(1))
assert w.run_button.isEnabled()
w.run_button.click()
assert calls==[('task',root,'check','mise',[])],calls
w.install.click()
assert calls[-1]==('install',root)
w.upgrade.click()
assert calls[-1]==('upgrade',root)
# Refresh sees changed declarations, without keeping project history.
(root/'mise.toml').write_text('[tools]\\npython="3.14"\\n')
old=w.snapshot
w.refresh()
wait_for(lambda:w.snapshot is not old)
assert w.task_list.topLevelItemCount()==0
assert w.tool_list.topLevelItem(0).text(0)=='python'
assert w.tabs.currentIndex()==1
(root/'mise.toml').unlink()
w.refresh()
wait_for(lambda:not w.worker)
assert not w.mise_card.isVisible()
# Other runners remain useful without any Mise configuration.
(root/'package.json').write_text('{"scripts":{"build":"echo build"}}')
(root/'Makefile').write_text('test:\\n\\t@true\\n')
w.refresh()
wait_for(lambda:not w.worker)
assert w.mise_card.isVisible() and not w.install.isVisible()
assert not w.tabs.isTabVisible(1)
assert w.task_list.topLevelItemCount()==2
w.task_search.setText('npm build')
# Search is a substring across tool/name/description.
w.task_search.setText('npm')
item=next(w.task_list.topLevelItem(i) for i in range(2) if w.task_list.topLevelItem(i).text(0)=='npm')
w.task_list.setCurrentItem(item)
w.task_arguments.setText('"space value" --watch')
w.run_button.click()
assert calls[-1]==('task',root,'build','package',['space value','--watch']),calls
# Every scanner language gets a badge, including tiny shares beyond the first seven.
w.show_languages({'partial':False,'languages':[
 {'name':'Rust','percentage':80,'bytes':800,'files':1,'color':'#dea584'},
 *[{'name':'Other'+str(i),'percentage':20/9,'bytes':20,'files':1,'color':'#808080'} for i in range(9)]]})
app.processEvents()
assert w.findChild(QScrollArea).horizontalScrollBar().maximum()==0
badges={w.tech_layout.itemAt(i).widget().objectName():w.tech_layout.itemAt(i).widget() for i in range(w.tech_layout.count())}
from PySide6.QtWidgets import QLabel, QProgressBar
assert 'tech_Rust' in badges and all('tech_Other'+str(i) in badges for i in range(9))
assert badges['tech_Rust'].findChild(QLabel,'techPercentage').text()=='80.0%'
assert not w.findChildren(QProgressBar)
from unittest.mock import patch
w.zed='/test/zeditor'
with patch('project_dashboard.subprocess.Popen') as popen:
 w.open_editor()
 assert popen.call_args.args[0][-2:]==['/test/zeditor',str(root)]
# Refreshing Git metadata selects Fetch; clicks only dispatch an action.
import subprocess
subprocess.run(['git','init','-q','-b','main',str(root)],check=True)
subprocess.run(['git','-C',str(root),'remote','add','origin','git@example.invalid:owner/repo.git'],check=True)
subprocess.run(['git','-C',str(root),'add','package.json'],check=True)
w.refresh();wait_for(lambda:not w.worker)
assert w.sync.text()=='Fetch' and w.sync.isEnabled()
assert w.commit.isEnabled()
w.sync.click();assert calls[-1]==('fetch',root)
w.commit.click();assert calls[-1]==('commit',root)
assert not (root/'MUST_NOT_RUN').exists()
w.close()
'''
            result = subprocess.run([sys.executable, '-c', script], check=False, env=env,
                                    capture_output=True, text=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == '__main__':
    unittest.main()
