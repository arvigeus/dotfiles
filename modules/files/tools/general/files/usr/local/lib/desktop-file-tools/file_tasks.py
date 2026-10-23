"""File discovery, checksum manifests, link creation and reviewed renaming."""
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import unicodedata

from tool_jobs import Output, batch, digest, emit, files, identity, rename_noreplace, row, walk
from tool_specs import action, option

ALGORITHMS = [('SHA-256','sha256'),('SHA-512','sha512'),('SHA-1','sha1'),('MD5','md5')]
RENAMES = [('Title case','title'),('Sentence case','sentence'),('Remove accents','accents'),
           ('Remove parentheses blocks','parentheses'),('Spaces to dashes','dashes'),('Dashes and underscores to spaces','spaces')]
ACTIONS = [
 action('rename','Rename files','Rename',[option('transform','Change','choice','title',RENAMES)],output=False,preview=True),
 action('hash','Generate checksum manifests','Checksums',[option('algorithm','Algorithm','choice','sha256',ALGORITHMS)],output=False,
        description='Manifests are saved beside selected files or inside selected folders.'),
 action('verify','Verify checksum manifests','Checksums',[option('algorithm','Algorithm','choice','sha256',ALGORITHMS)],output=False),
 action('find','Find files and links','Find',[option('kind','Find','choice','duplicates',[
     ('Duplicate files','duplicates'),('Empty files','empty-files'),('Empty directories','empty-directories'),
     ('Broken symbolic links','broken'),('Symbolic links','symbolic'),('Hard links','hard')])],output=False),
 action('hardlink','Create hard links','Links',[option('destination','Destination folder','folder')],output=False),
 action('clipboard','Copy file contents','Clipboard',output=False,description='Copy one image or the combined contents of selected UTF-8 text files.'),
]


def renamed(path, transform):
    name = path.name
    stem,suffix = (name,'') if path.is_dir() else (path.stem,path.suffix)
    if transform == 'title': stem = stem.title()
    elif transform == 'sentence': stem = stem[:1].upper()+stem[1:].lower()
    elif transform == 'accents': stem = ''.join(c for c in unicodedata.normalize('NFKD',stem) if not unicodedata.combining(c))
    elif transform == 'parentheses':
        while re.search(r'\([^()]*\)',stem): stem = re.sub(r'\([^()]*\)','',stem)
        stem = re.sub(r'\s+',' ',stem).strip()
    elif transform == 'dashes': stem = re.sub(r'\s+','-',stem)
    elif transform == 'spaces': stem = re.sub(r'[-_\t]+',' ',stem)
    else: raise ValueError('Choose a rename operation.')
    result = stem+suffix
    if not stem or result in ('.','..') or '/' in result: raise ValueError(f'Invalid resulting name: {name}')
    return path.with_name(result)


def rename_plan(paths, transform):
    sources = [Path(value).absolute() for value in paths]
    if len(set(sources)) != len(sources): raise ValueError('The selection contains repeated paths.')
    if any(source in other.parents for source in sources for other in sources):
        raise ValueError('Rename a folder and its contents in separate operations.')
    plan = []
    for source in sources:
        target = renamed(source,transform)
        if source == target: continue
        if os.path.lexists(target): raise FileExistsError(f'Target already exists: {target}')
        plan.append(dict(source=str(source),target=str(target),identity=identity(source)))
    targets = [item['target'] for item in plan]
    if len(set(targets))!=len(targets): raise ValueError('Several files would have the same name.')
    return plan


def manifest_line(checksum, name):
    escaped = any(character in name for character in '\\\n\r')
    name = name.replace('\\','\\\\').replace('\n','\\n').replace('\r','\\r')
    return ('\\' if escaped else '') + checksum+'  '+name+'\n'


def manifest_entries(text, algorithm):
    length = {'md5':32,'sha1':40,'sha256':64,'sha512':128}[algorithm]
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'): continue
        match = re.fullmatch(r'(\\?)([0-9a-fA-F]{'+str(length)+r'}) [ *](.+)',line)
        if not match: raise ValueError('Invalid checksum manifest entry.')
        escaped,checksum,name = match.groups()
        if escaped:
            name = re.sub(r'\\([\\nr])',lambda m: {'\\':'\\','n':'\n','r':'\r'}[m[1]],name)
        yield checksum.lower(),name


def run(action_id, paths, options, plan=None):
    if not paths: raise ValueError('Select files or folders first.')
    if action_id == 'rename':
        current = rename_plan(paths,options.get('transform','title'))
        if plan is None:
            for item in current: row(item['source'],'Rename to',Path(item['target']).name)
            emit('preview',plan=current)
        else:
            if current != plan: raise ValueError('The rename preview is out of date. Preview again.')
            for item in current:
                rename_noreplace(item['source'],item['target']); row(item['target'],'Renamed',Path(item['source']).name)
        return
    if action_id in ('hash','verify'):
        algorithm = options.get('algorithm','sha256')
        if algorithm not in dict((value,label) for label,value in ALGORITHMS): raise ValueError('Choose a checksum algorithm.')
        def process(path):
            if action_id == 'hash':
                selected = files([path]) if path.is_dir() else [path]
                root = path if path.is_dir() else path.parent
                target = path/(algorithm.upper()+'SUMS') if path.is_dir() else path.with_name(path.name+'.'+algorithm)
                with Output(target) as output:
                    with output.path.open('w',encoding='utf-8',newline='\n') as stream:
                        for source in selected:
                            stream.write(manifest_line(digest(source,algorithm),source.relative_to(root).as_posix()))
                    output.publish()
            else:
                matched = 0
                for expected,name in manifest_entries(path.read_text(encoding='utf-8'),algorithm):
                    relative = Path(name)
                    target = path.parent / relative
                    if relative.is_absolute() or target.is_symlink() or not target.resolve().is_relative_to(path.parent.resolve()):
                        raise ValueError('Manifest filenames must stay inside the manifest folder.')
                    actual = digest(target,algorithm); matched += 1
                    row(target,'Verified' if actual==expected else 'Mismatch',path.name,error=actual!=expected)
                if not matched: raise ValueError('The manifest contains no checksums.')
        return batch([Path(value) for value in paths],process)
    if action_id == 'hardlink':
        destination = Path(options.get('destination',''))
        if not destination.is_absolute() or not destination.is_dir(): raise ValueError('Choose a destination folder.')
        def process(path):
            if not path.is_file() or path.is_symlink(): raise ValueError('Hard-link sources must be regular files.')
            target = destination/path.name; os.link(path,target,follow_symlinks=False); row(target,'Hard link created')
        return batch(paths,process)
    if action_id != 'find': raise ValueError('Unknown file operation.')
    kind = options.get('kind','duplicates'); entries = list(walk(paths)); groups = defaultdict(list)
    for index,path in enumerate(entries):
        if index % 100 == 0: emit('progress',current=index,total=len(entries),name=path.name)
        if kind == 'symbolic' and path.is_symlink(): row(path,'Symbolic link',os.readlink(path))
        elif kind == 'broken' and path.is_symlink() and not path.exists(): row(path,'Broken link',os.readlink(path))
        elif not path.is_symlink():
            stat = path.stat()
            if kind == 'empty-files' and path.is_file() and not stat.st_size: row(path,'Empty file')
            elif kind == 'empty-directories' and path.is_dir() and not any(path.iterdir()): row(path,'Empty folder')
            elif kind == 'hard' and path.is_file() and stat.st_nlink>1: groups[(stat.st_dev,stat.st_ino)].append(path)
            elif kind == 'duplicates' and path.is_file(): groups[stat.st_size].append(path)
    if kind == 'hard':
        for number,group in enumerate(groups.values(),1):
            for path in group: row(path,f'Hard-link group {number}',f'{path.stat().st_nlink} links to this file')
    elif kind == 'duplicates':
        matches = defaultdict(list)
        for group in groups.values():
            if len(group)<2: continue
            for path in group: matches[digest(path,'sha256')].append(path)
        number = 0
        for group in matches.values():
            if len(group)<2: continue
            number += 1
            for path in group: row(path,f'Duplicate group {number}',f'{len(group)} identical files')
    elif kind not in ('empty-files','empty-directories','broken','symbolic'):
        raise ValueError('Choose a file search.')
    emit('progress',current=len(entries),total=len(entries),name='')
