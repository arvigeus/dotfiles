"""Isolated thumbnail reads: slow artwork must never queue ahead of music browsing or saves."""
from functools import lru_cache
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from integrations.subsonic import MusicError as CloudError
from spaces.movies.image_cache import ArtworkCache,ImageError
from spaces.music import local_files
from spaces.music.cloud import CloudLibrary
from spaces.music.records import MusicError


@lru_cache(maxsize=1)
def public_cache():
    return ArtworkCache()


def handle(args):
    if args.get('op')!='cover':raise MusicError('Unknown artwork operation.')
    item=args.get('item') or {}
    if item.get('localPath'):
        try:
            if file:=local_files.cover(item):return file
        except (MusicError,ValueError,OSError):
            if item.get('source')!='nextcloud':return ''
    if item.get('source')=='nextcloud':return CloudLibrary().cover(item)
    if item.get('cover'):return public_cache().fetch(item['cover'])
    return ''


if __name__=='__main__':
    from spaces.movies.worker import own_process_group,serve
    own_process_group(local_files.shutdown)
    serve(handle,errors=(MusicError,CloudError,ImageError,ValueError),workers=3)
