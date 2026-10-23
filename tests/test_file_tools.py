"""Native tool backends operate on disposable files and isolated GnuPG keyrings."""
import importlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

REPO=Path(__file__).resolve().parents[1]
MODULES=['modules/files/tools/common','modules/files/tools/general','modules/files/tools/encryption','modules/media/tools/pdf']
LIBS=[REPO/module/'files/usr/local/lib/desktop-file-tools' for module in MODULES]
for library in LIBS:sys.path.insert(0,str(library))
from tool_jobs import Output
import file_tasks

ENV=dict(os.environ,PYTHONPATH=os.pathsep.join(map(str,LIBS)))
WORKER=LIBS[0]/'tool_worker.py'


def job(kind,action,paths,options=None,plan=None,env=None):
    result=subprocess.run([sys.executable,str(WORKER)],input=json.dumps(dict(app=kind,action=action,paths=list(map(str,paths)),options=options or {},plan=plan)),
        env=env or ENV,capture_output=True,text=True,timeout=90)
    events=[json.loads(line) for line in result.stdout.splitlines()]
    return result,events


def successful(test,result,events):
    errors=[event for event in events if event['type']=='error' or (event['type']=='row' and event.get('error'))]
    test.assertEqual(result.returncode,0,result.stderr+str(errors));test.assertFalse(errors,errors)


class FileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_output_races_never_replace_files_or_folders(self):
        target=self.root/'output.txt'
        with Output(target) as output:
            output.path.write_text('new');target.write_text('original')
            with self.assertRaises(FileExistsError):output.publish()
        self.assertEqual(target.read_text(),'original')
        folder=self.root/'folder'
        with Output(folder,directory=True) as output:
            (output.path/'new').write_text('new');folder.mkdir();(folder/'keep').write_text('old')
            with self.assertRaises(FileExistsError):output.publish()
        self.assertEqual(list(p.name for p in folder.iterdir()),['keep'])
        self.assertFalse(list(self.root.glob('.file-tools-*')))

    def test_rename_preview_rejects_collisions_and_changed_sources(self):
        source=self.root/"User's $(touch UNEXPECTED) file.txt";source.write_text('data')
        result,events=job('file','rename',[source],{'transform':'dashes'})
        successful(self,result,events);self.assertTrue(source.exists())
        plan=next(event['plan'] for event in events if event['type']=='preview')
        source.write_text('changed')
        result,events=job('file','rename',[source],{'transform':'dashes'},plan)
        self.assertNotEqual(result.returncode,0);self.assertTrue(source.exists())
        plan=file_tasks.rename_plan([source],'dashes')
        result,events=job('file','rename',[source],{'transform':'dashes'},plan)
        successful(self,result,events);self.assertFalse(source.exists())
        target=Path(plan[0]['target']);self.assertEqual(target.read_text(),'changed')
        self.assertFalse((self.root/'UNEXPECTED').exists())
        a=self.root/'test one';b=self.root/'test-one';a.write_text('a');b.write_text('b')
        with self.assertRaises(FileExistsError):file_tasks.rename_plan([a],'dashes')
        self.assertEqual(a.read_text(),'a');self.assertEqual(b.read_text(),'b')

    def test_checksum_algorithms_handle_unusual_names_and_tampering(self):
        source=self.root/"odd\nfile\\' $(touch UNEXPECTED).txt";source.write_text('original')
        for algorithm in ['md5','sha1','sha256','sha512']:
            result,events=job('file','hash',[source],{'algorithm':algorithm});successful(self,result,events)
            manifest=source.with_name(source.name+'.'+algorithm)
            result,events=job('file','verify',[manifest],{'algorithm':algorithm});successful(self,result,events)
            self.assertTrue(any(event.get('status')=='Verified' for event in events))
        source.write_text('tampered')
        result,events=job('file','verify',[source.with_name(source.name+'.sha256')],{'algorithm':'sha256'})
        self.assertTrue(any(event.get('status')=='Mismatch' for event in events))
        self.assertFalse((self.root/'UNEXPECTED').exists())

    def test_checksum_verification_rejects_external_manifest_paths(self):
        manifest=self.root/'SHA256SUMS'
        manifest.write_text('0'*64+'  ../outside.txt\n')
        result,events=job('file','verify',[manifest])
        self.assertTrue(any('inside the manifest folder' in event.get('detail','') for event in events))

    def test_discovery_and_hard_links_preserve_all_files(self):
        one=self.root/'one';one.write_text('same');two=self.root/'two';two.write_text('same')
        empty=self.root/'empty';empty.touch();folder=self.root/'empty-dir';folder.mkdir()
        (self.root/'broken').symlink_to(self.root/'missing');(self.root/'link').symlink_to(one)
        for kind,expected in [('duplicates',2),('empty-files',1),('empty-directories',1),('broken',1),('symbolic',2)]:
            result,events=job('file','find',[self.root],{'kind':kind});successful(self,result,events)
            self.assertEqual(len([event for event in events if event['type']=='row']),expected,kind)
        dest=self.root/'links';dest.mkdir()
        result,events=job('file','hardlink',[one],{'destination':str(dest)});successful(self,result,events)
        self.assertEqual(one.stat().st_ino,(dest/'one').stat().st_ino)
        self.assertEqual(one.read_text(),'same');self.assertEqual(two.read_text(),'same')


@unittest.skipUnless(importlib.util.find_spec('pikepdf'),'pikepdf required')
class PdfToolsTests(unittest.TestCase):
    def setUp(self):
        import pikepdf
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/"User's $(touch UNEXPECTED).pdf"
        with pikepdf.Pdf.new() as pdf:
            pdf.add_blank_page(page_size=(200,300));pdf.add_blank_page(page_size=(300,200));pdf.docinfo['/Title']='Original'
            pdf.save(self.source)
        self.original=self.source.read_bytes()

    def test_combine_split_rotate_metadata_linearize_and_password_roundtrip(self):
        import pikepdf
        second=self.root/'second.pdf';shutil.copy(self.source,second)
        result,events=job('pdf','combine',[second,self.source]);successful(self,result,events)
        with pikepdf.Pdf.open(self.root/'Combined documents.pdf') as pdf:self.assertEqual(len(pdf.pages),4)
        for action in ['split','rotate','metadata','linearize','protect']:
            result,events=job('pdf',action,[self.source],{'angle':'270','new_password':'test secret'})
            successful(self,result,events)
        self.assertEqual(len(list((self.root/(self.source.stem+' [pages]')).glob('*.pdf'))),2)
        with pikepdf.Pdf.open(self.root/(self.source.stem+' [rotate].pdf')) as pdf:self.assertEqual(pdf.pages[0].obj['/Rotate'],270)
        with pikepdf.Pdf.open(self.root/(self.source.stem+' [metadata].pdf')) as pdf:self.assertFalse(pdf.docinfo)
        with pikepdf.Pdf.open(self.root/(self.source.stem+' [linearize].pdf')) as pdf:self.assertTrue(pdf.is_linearized)
        encrypted=self.root/(self.source.stem+' [protect].pdf')
        with self.assertRaises(pikepdf.PasswordError):pikepdf.Pdf.open(encrypted)
        result,events=job('pdf','unprotect',[encrypted],{'password':'test secret'});successful(self,result,events)
        with pikepdf.Pdf.open(self.root/(encrypted.stem+' [unprotect].pdf')) as pdf:self.assertFalse(pdf.is_encrypted)
        self.assertEqual(self.source.read_bytes(),self.original);self.assertFalse((self.root/'UNEXPECTED').exists())

    def test_export_profile_preserves_working_pdf_and_refuses_existing_targets(self):
        import pikepdf
        protected=self.root/'Protected.pdf'
        with pikepdf.Pdf.open(self.source) as pdf:
            pdf.save(protected,encryption=pikepdf.Encryption(user='secret',owner='owner'))
        original=protected.read_bytes();session=self.root/'session';session.mkdir(mode=0o700)
        target=self.root/'Web.pdf';entry=dict(path=str(protected),name=protected.name,password='secret',target=str(target))
        options=dict(variant='linearize',settings={},directory=str(session))
        result,events=job('pdf','_pdf_export',[protected],options,[entry]);successful(self,result,events)
        with pikepdf.Pdf.open(target,password='secret') as pdf:
            self.assertTrue(pdf.is_encrypted);self.assertTrue(pdf.is_linearized)
        saved=target.read_bytes()
        result,events=job('pdf','_pdf_export',[protected],options,[entry])
        self.assertNotEqual(result.returncode,0);self.assertEqual(target.read_bytes(),saved)
        self.assertEqual(protected.read_bytes(),original);self.assertEqual(list(session.iterdir()),[])
        self.assertEqual(target.stat().st_mode & 0o777,0o600)

    def test_page_ranges_export_selected_pages_and_reject_invalid_input(self):
        import pikepdf
        source=self.root/'Seven.pdf'
        with pikepdf.Pdf.new() as pdf:
            for number in range(1,8):pdf.add_blank_page(page_size=(100+number,200))
            pdf.save(source,min_version='1.7')
        original=source.read_bytes()
        for name,pages,widths in [('selection','1-5,7',[101,102,103,104,105,107]),('ordered','7, 2-3,2',[107,102,103])]:
            folder=self.root/name;folder.mkdir()
            result,events=job('pdf','split',[source],dict(pages=pages,split_mode='selection',output=str(folder)))
            successful(self,result,events)
            with pikepdf.Pdf.open(folder/'Seven [selection].pdf') as pdf:
                self.assertEqual([int(page.mediabox[2]) for page in pdf.pages],widths)
                self.assertGreaterEqual(pdf.pdf_version,'1.7')
        folder=self.root/'separate';folder.mkdir()
        result,events=job('pdf','split',[source],dict(pages='1-2,7',split_mode='separate',output=str(folder)))
        successful(self,result,events)
        self.assertEqual(sorted(path.name for path in (folder/'Seven [pages]').iterdir()),['0001.pdf','0002.pdf','0007.pdf'])
        folder=self.root/'invalid';folder.mkdir()
        for value in ['0','8','3-1','1,,2','1-','-1','one','1-8','1,2;3','1.5','1--3']:
            result,events=job('pdf','split',[source],dict(pages=value,output=str(folder)))
            self.assertTrue(any(event.get('error') for event in events),value)
            self.assertEqual(list(folder.iterdir()),[],value)
        self.assertEqual(source.read_bytes(),original)

    def test_watermarks_and_information(self):
        import pikepdf
        mark=self.root/'mark.pdf'
        with pikepdf.Pdf.new() as pdf:
            page=pdf.add_blank_page();page.obj['/Contents']=pdf.make_stream(b'0 0 1 rg 0 0 100 100 re f');pdf.save(mark)
        for layer in ['over','under']:
            output=self.root/layer;output.mkdir()
            result,events=job('pdf','watermark',[self.source],{'watermark':str(mark),'layer':layer,'output':str(output)})
            successful(self,result,events)
            with pikepdf.Pdf.open(next(output.glob('*.pdf'))) as pdf:self.assertTrue(pdf.pages[0].obj['/Resources'].get('/XObject'))
        result,events=job('pdf','inspect',[self.source]);successful(self,result,events)
        self.assertTrue(any(event.get('status')=='Pages' and event.get('detail')=='2' for event in events))
        result,events=job('pdf','find',[self.root],{'condition':'unoptimized'})
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(any(event.get('message')=='Unknown operation.' for event in events))

    @unittest.skipUnless(shutil.which('gs') and shutil.which('ocrmypdf'),'PDF command tools required')
    def test_reduction_pdfa_without_recognition_and_image_extraction(self):
        from PIL import Image, ImageDraw
        import pikepdf
        raster=self.root/'scan.png'
        image=Image.new('RGB',(1200,240),'white');draw=ImageDraw.Draw(image)
        from PIL import ImageFont
        font=ImageFont.truetype('DejaVuSans.ttf',48);draw.text((40,80),'Hello world 123',fill='black',font=font)
        image.save(raster)
        scan=self.root/'scan.pdf';image.save(scan,resolution=150)
        original=scan.read_bytes()
        for action,options in [('reduce',{'dpi':'150'}),('images',{}),('pdfa',{})]:
            result,events=job('pdf',action,[scan],options);successful(self,result,events)
        self.assertTrue(list((self.root/'scan [images]').iterdir()))
        text=subprocess.check_output(['pdftotext',str(self.root/'scan [pdfa].pdf'),'-']).decode()
        self.assertEqual(text.strip(),'')
        with pikepdf.Pdf.open(self.root/'scan [pdfa].pdf') as pdf:
            with pdf.open_metadata() as metadata:
                self.assertEqual(str(metadata['pdfaid:part']),'2')
                self.assertEqual(str(metadata['pdfaid:conformance']),'B')
        self.assertEqual(scan.read_bytes(),original)

    def test_cancellation_terminates_owned_child_and_cleans_partial_outputs(self):
        commands=self.root/'bin';commands.mkdir();pid_file=self.root/'pid'
        executable=commands/'gs';executable.write_text('#!/usr/bin/python3\nimport os,time\nopen('+repr(str(pid_file))+',"w").write(str(os.getpid()))\ntime.sleep(30)\n');executable.chmod(0o755)
        process=subprocess.Popen([sys.executable,str(WORKER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            env=dict(ENV,PATH=str(commands)+':'+os.environ['PATH']))
        process.stdin.write(json.dumps(dict(app='pdf',action='reduce',paths=[str(self.source)],options={})));process.stdin.close();process.stdin=None
        deadline=time.monotonic()+10
        while not pid_file.exists():
            if time.monotonic()>deadline:process.kill();self.fail('PDF converter child did not start')
            time.sleep(.01)
        pid=int(pid_file.read_text());process.terminate();stdout,stderr=process.communicate(timeout=8)
        self.assertIn('cancelled',stdout,stderr)
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)
        self.assertFalse(list(self.root.glob('.file-tools-*')))
        self.assertFalse(list(self.root.glob('*[[]reduce[]].pdf')))
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_existing_pdf_output_is_never_overwritten(self):
        target=self.root/(self.source.stem+' [rotate].pdf');target.write_text('keep')
        result,events=job('pdf','rotate',[self.source])
        self.assertTrue(any(event.get('error') for event in events));self.assertEqual(target.read_text(),'keep')


@unittest.skipUnless(shutil.which('gpg'),'GnuPG required')
class EncryptionToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name);cls.home=cls.root/'gnupg';cls.home.mkdir(mode=0o700)
        cls.env=dict(ENV,GNUPGHOME=str(cls.home))
        def gpg(*args):return subprocess.check_output(['gpg','--batch','--pinentry-mode','loopback','--passphrase','',*args],env=cls.env,stderr=subprocess.DEVNULL)
        gpg('--quick-generate-key','Tools fixture <tools@example.invalid>','ed25519','sign','0')
        output=gpg('--with-colons','--list-keys').decode();cls.fingerprint=next(line.split(':')[9] for line in output.splitlines() if line.startswith('fpr:'))
        gpg('--quick-add-key',cls.fingerprint,'cv25519','encr','0')

    @classmethod
    def tearDownClass(cls):
        subprocess.run(['gpgconf','--kill','gpg-agent'],env=cls.env,capture_output=True)
        cls.temp.cleanup()

    def test_encrypt_decrypt_sign_verify_and_read_keys(self):
        folder=self.root/'jobs';folder.mkdir(exist_ok=True)
        source=folder/"User's $(touch UNEXPECTED).txt";source.write_text('original secret')
        options={'recipients':[self.fingerprint],'signer':self.fingerprint}
        result,events=job('encryption','keys',[],env=self.env);successful(self,result,events)
        self.assertTrue(next(event['keys'] for event in events if event['type']=='keys')[0]['secret'])
        result,events=job('encryption','sign-encrypt',[source],options,env=self.env);successful(self,result,events)
        encrypted=source.with_name(source.name+'.gpg');restore=folder/'restored';restore.mkdir()
        result,events=job('encryption','decrypt',[encrypted],{'output':str(restore)},env=self.env);successful(self,result,events)
        self.assertEqual((restore/source.name).read_text(),'original secret')
        result,events=job('encryption','sign',[source],dict(options,signature='detached'),env=self.env);successful(self,result,events)
        signature=source.with_name(source.name+'.sig')
        result,events=job('encryption','verify',[signature],{'original':str(source)},env=self.env);successful(self,result,events)
        source.write_text('tampered')
        result,events=job('encryption','verify',[signature],{'original':str(source)},env=self.env)
        self.assertTrue(any(event.get('error') for event in events))
        self.assertFalse((folder/'UNEXPECTED').exists())

    def test_key_import_does_not_grant_owner_trust(self):
        public=self.root/'public.asc'
        public.write_bytes(subprocess.check_output(['gpg','--armor','--export',self.fingerprint],env=self.env))
        other=self.root/'imported';other.mkdir(mode=0o700);env=dict(ENV,GNUPGHOME=str(other))
        try:
            result,events=job('encryption','import',[public],env=env);successful(self,result,events)
            trust=subprocess.check_output(['gpg','--export-ownertrust'],env=env,stderr=subprocess.DEVNULL).decode()
            self.assertNotIn(self.fingerprint+':6:',trust)
        finally:subprocess.run(['gpgconf','--kill','gpg-agent'],env=env,capture_output=True)


if __name__=='__main__':unittest.main()
