"""Account-scoped metadata snapshot. Audio and file synchronization are not involved."""
import json
import os
import sqlite3
import tempfile
import threading
import time
import unicodedata
from contextlib import closing
from pathlib import Path

BATCH=500
PAGE=200
SCHEMA=1


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text)).casefold() if not unicodedata.combining(c))


class CatalogueIndex:
    def __init__(self,client,root,normalize):
        self.client=client;self.account=client.account_id;self.root=Path(root);self.path=self.root/'catalogue.sqlite';self.normalize=normalize
        self.view_path=None
        self.lock=threading.RLock();self.cancelled=threading.Event();self.thread=None;self.temporary=None
        self.running=False;self.attempted=False;self.loaded=0;self.error='';self.phase='';self.star_edits={};self.song_edits={}

    def connect(self,remote=False):
        path=self.view_path if not remote and self.view_path and self.view_path.exists() else self.path
        return sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5)

    def info(self,remote=False):
        try:
            with closing(self.connect(remote)) as db:
                meta=dict(db.execute('SELECT key,value FROM metadata'))
            if meta.get('account')!=self.account or int(meta.get('schema',0))!=SCHEMA:return {}
            return {**{key:int(meta.get(key,0)) for key in ('songs','albums','artists')},'version':meta.get('version','')}
        except (sqlite3.Error,OSError,ValueError):return {}

    def status(self):
        with self.lock:
            info=self.info()
            return dict(ready=bool(info),indexing=self.running,loaded=self.loaded,phase=self.phase,indexError=self.error,**info)

    def start(self,force=False):
        with self.lock:
            if self.running or (not force and self.attempted):return
            if not force and self.info(remote=True) and time.time()-self.path.stat().st_mtime<120:return
            self.attempted=True;self.running=True;self.loaded=0;self.error='';self.phase='songs';self.cancelled.clear()
            self.star_edits={};self.song_edits={}
            self.thread=threading.Thread(target=self._build,daemon=True,name='music-catalogue')
            self.thread.start()

    def stop(self):
        with self.lock:
            self.cancelled.set()
            if self.temporary:self.temporary.unlink(missing_ok=True)

    @staticmethod
    def create(db):
        db.executescript('''
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE records(kind TEXT,id TEXT,payload TEXT,search TEXT,sort TEXT,album TEXT,disc INTEGER,track INTEGER,starred INTEGER,PRIMARY KEY(kind,id));
            CREATE TABLE artist_songs(artist TEXT,song TEXT,PRIMARY KEY(artist,song));
            CREATE TABLE album_artists(artist TEXT,album TEXT,PRIMARY KEY(artist,album));
            CREATE TABLE genres(kind TEXT,id TEXT,name TEXT,PRIMARY KEY(kind,id,name));
            CREATE INDEX record_sort ON records(kind,sort,id);
            CREATE INDEX record_album ON records(kind,album,disc,track);
            CREATE INDEX song_artists ON artist_songs(song,artist);
            CREATE INDEX albums_by_artist ON album_artists(artist,album);
            CREATE INDEX genre_names ON genres(name,kind,id);
        ''')

    def put(self,db,item):
        kind=item['kind'];identifier=str(item['id'])
        search=fold(' '.join(str(item.get(key) or '') for key in ('name','title','artist','album')))
        db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?,?,?,?)',(kind,identifier,json.dumps(item,ensure_ascii=False),search,fold(item.get('title') or item.get('name') or ''),item.get('albumId',''),int(item.get('discNumber') or 0),int(item.get('trackNumber') or 0),int(bool(item.get('starred')))))
        db.execute('DELETE FROM genres WHERE kind=? AND id=?',(kind,identifier))
        db.executemany('INSERT OR IGNORE INTO genres VALUES(?,?,?)',[(kind,identifier,name) for name in item.get('genreNames',[])])
        if kind=='song':
            db.execute('DELETE FROM artist_songs WHERE song=?',(identifier,))
            db.executemany('INSERT OR IGNORE INTO artist_songs VALUES(?,?)',[(str(artist),identifier) for artist in item.get('artistIds',[])])
        elif kind=='album':
            db.execute('DELETE FROM album_artists WHERE album=?',(identifier,))
            db.executemany('INSERT OR IGNORE INTO album_artists VALUES(?,?)',[(str(artist),identifier) for artist in item.get('artistIds',[])])

    def _build(self):
        temporary=None
        try:
            self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd,name=tempfile.mkstemp(prefix='.catalogue-',suffix='.sqlite',dir=self.root);os.close(fd)
            temporary=Path(name)
            with self.lock:self.temporary=temporary
            with closing(sqlite3.connect(temporary)) as db:
                db.execute('PRAGMA journal_mode=OFF');self.create(db)
                offsets={kind:0 for kind in ('song','album','artist')};active=set(offsets);last={}
                while active:
                    if self.cancelled.is_set():return
                    args={'query':''}
                    for kind in offsets:args.update({kind+'Count':BATCH if kind in active else 0,kind+'Offset':offsets[kind]})
                    result=self.client.request('search3',**args).get('searchResult3')
                    if not isinstance(result,dict):raise ValueError('Invalid catalogue page')
                    for kind in tuple(active):
                        values=result.get(kind,[])
                        if not isinstance(values,list):raise ValueError('Invalid catalogue items')
                        if not values:active.remove(kind);continue
                        ids=tuple(str(item.get('id')) for item in values)
                        if ids==last.get(kind):raise ValueError('Repeated catalogue page')
                        last[kind]=ids
                        for raw in values:self.put(db,self.normalize(raw,kind,self.account))
                        offsets[kind]+=len(values)
                    db.commit()
                    with self.lock:self.loaded=offsets['song'];self.phase='metadata'
                stars=self.client.request('getStarred2').get('starred2')
                if not isinstance(stars,dict):raise ValueError('Invalid starred catalogue')
                db.execute('UPDATE records SET starred=0')
                for kind in ('song','album','artist'):
                    for item in stars.get(kind,[]):db.execute('UPDATE records SET starred=1 WHERE kind=? AND id=?',(kind,str(item['id'])))
                version=time.time_ns()
                meta=dict(account=self.account,schema=str(SCHEMA),version=str(version))
                for category,kind in (('songs','song'),('albums','album'),('artists','artist')):meta[category]=str(db.execute('SELECT count(*) FROM records WHERE kind=?',(kind,)).fetchone()[0])
                db.executemany('INSERT INTO metadata VALUES(?,?)',meta.items())
                with self.lock:
                    if self.cancelled.is_set():return
                    for item in self.song_edits.values():self._put_song(db,item)
                    for (kind,identifier),starred in self.star_edits.items():db.execute('UPDATE records SET starred=? WHERE kind=? AND id=?',(int(starred),kind,identifier))
                    db.commit();os.replace(temporary,self.path)
        except Exception:
            with self.lock:self.error='The library index could not refresh. Your previous cached library is preserved.'
        finally:
            if temporary:temporary.unlink(missing_ok=True)
            with self.lock:self.running=False;self.temporary=None

    def lookup(self,kind,identifier):
        with closing(self.connect()) as db:row=db.execute('SELECT payload,starred FROM records WHERE kind=? AND id=?',(kind,str(identifier))).fetchone()
        if not row:return None
        return json.loads(row[0])|dict(starred=bool(row[1]))

    def browse(self,args,*,artist=None,album=None):
        kind={'songs':'song','albums':'album','artists':'artist'}.get(args.get('category','songs'))
        if kind is None:raise ValueError('Unknown library category')
        page_size=min(100000,max(PAGE,int(args.get('pageSize') or PAGE)))
        offset=max(0,int(args.get('offset') or 0));clauses=['r.kind=?'];params=[kind]
        for term in fold(args.get('query') or '').split():clauses.append('instr(r.search,?)>0');params.append(term)
        if args.get('pending'):clauses.append("json_extract(r.payload,'$.notUploaded')=1")
        if args.get('starred'):clauses.append('r.starred=1')
        genre=args.get('genreName') or ''
        if genre and kind=='song':clauses.append('EXISTS(SELECT 1 FROM genres g WHERE g.kind=r.kind AND g.id=r.id AND g.name=?)');params.append(genre)
        elif genre and kind=='album':
            clauses.append("r.id IN (SELECT s.album FROM records s JOIN genres g ON g.kind='song' AND g.id=s.id WHERE s.kind='song' AND g.name=?)");params.append(genre)
        if album:clauses.append('r.album=?');params.append(str(album))
        if artist:
            if kind=='song':
                clauses.append("r.id IN (SELECT song FROM artist_songs WHERE artist=? UNION SELECT s.id FROM records s JOIN album_artists a ON s.album=a.album WHERE s.kind='song' AND a.artist=?)");params.extend([str(artist),str(artist)])
            elif kind=='album':
                clauses.append("r.id IN (SELECT album FROM album_artists WHERE artist=? UNION SELECT s.album FROM records s JOIN artist_songs a ON s.id=a.song WHERE s.kind='song' AND a.artist=?)");params.extend([str(artist),str(artist)])
        where=' AND '.join(clauses)
        order='r.disc,r.track,r.sort,r.id' if album else 'r.sort,r.id'
        with closing(self.connect()) as db:
            total=db.execute('SELECT count(*) FROM records r WHERE '+where,params).fetchone()[0]
            values=db.execute('SELECT r.payload,r.starred FROM records r WHERE '+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',[*params,page_size,offset]).fetchall()
        return dict(items=[json.loads(payload)|dict(starred=bool(starred)) for payload,starred in values],total=total,limit=offset+len(values),hasMore=offset+len(values)<total,cursor='',cached=True)

    def genres(self):
        with closing(self.connect()) as db:values=db.execute("SELECT DISTINCT name FROM genres WHERE kind='song' ORDER BY name").fetchall()
        return [dict(id=name,name=name) for (name,) in values]

    def set_star(self,item,value):
        key=(item['kind'],str(item['id']))
        with self.lock:
            self.star_edits[key]=bool(value)
            if self.info():
                with closing(sqlite3.connect(self.path,timeout=5)) as db:
                    with db:db.execute('UPDATE records SET starred=? WHERE kind=? AND id=?',(int(value),*key))

    def _put_song(self,db,song):
        self.put(db,song)
        if song.get('albumId'):
            old=db.execute("SELECT payload,starred FROM records WHERE kind='album' AND id=?",(str(song['albumId']),)).fetchone()
            album=json.loads(old[0]) if old else dict(id=song['albumId'],kind='album',source='nextcloud',account=self.account,artist=song.get('artist',''),artistIds=song.get('artistIds',[]),genreNames=song.get('genreNames',[]),releaseDate=song.get('releaseDate',''))
            self.put(db,album|dict(title=song.get('album',''),starred=bool(old[1]) if old else False))
        for artist in song.get('artistIds',[]):
            if not db.execute("SELECT 1 FROM records WHERE kind='artist' AND id=?",(str(artist),)).fetchone():self.put(db,dict(id=str(artist),kind='artist',source='nextcloud',account=self.account,name=song.get('artist','')))

    def update_song(self,song):
        with self.lock:
            self.song_edits[str(song['id'])]=song
            if self.info():
                with closing(sqlite3.connect(self.path,timeout=5)) as db:
                    with db:self._put_song(db,song)
