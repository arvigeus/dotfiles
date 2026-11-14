"""MPRIS Player interface for Music's QML-owned queue."""

import logging
import threading
import urllib.parse

from gi.repository import Gio, GLib

LOG = logging.getLogger(__name__)
BUS_NAME = 'org.mpris.MediaPlayer2.music'
OBJECT_PATH = '/org/mpris/MediaPlayer2'
ROOT = 'org.mpris.MediaPlayer2'
PLAYER = 'org.mpris.MediaPlayer2.Player'
NO_TRACK = '/org/mpris/MediaPlayer2/TrackList/NoTrack'

INTROSPECTION = """<node>
<interface name="org.mpris.MediaPlayer2">
 <method name="Raise"/><method name="Quit"/>
 <property name="CanQuit" type="b" access="read"/>
 <property name="Fullscreen" type="b" access="readwrite"/>
 <property name="CanSetFullscreen" type="b" access="read"/>
 <property name="CanRaise" type="b" access="read"/>
 <property name="HasTrackList" type="b" access="read"/>
 <property name="Identity" type="s" access="read"/>
 <property name="DesktopEntry" type="s" access="read"/>
 <property name="SupportedUriSchemes" type="as" access="read"/>
 <property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
 <method name="Next"/><method name="Previous"/><method name="Pause"/>
 <method name="PlayPause"/><method name="Stop"/><method name="Play"/>
 <method name="Seek"><arg name="Offset" type="x" direction="in"/></method>
 <method name="SetPosition"><arg name="TrackId" type="o" direction="in"/><arg name="Position" type="x" direction="in"/></method>
 <method name="OpenUri"><arg name="Uri" type="s" direction="in"/></method>
 <signal name="Seeked"><arg name="Position" type="x"/></signal>
 <property name="PlaybackStatus" type="s" access="read"/>
 <property name="LoopStatus" type="s" access="readwrite"/>
 <property name="Rate" type="d" access="readwrite"/>
 <property name="Shuffle" type="b" access="readwrite"/>
 <property name="Metadata" type="a{sv}" access="read"/>
 <property name="Volume" type="d" access="readwrite"/>
 <property name="Position" type="x" access="read"/>
 <property name="MinimumRate" type="d" access="read"/>
 <property name="MaximumRate" type="d" access="read"/>
 <property name="CanGoNext" type="b" access="read"/>
 <property name="CanGoPrevious" type="b" access="read"/>
 <property name="CanPlay" type="b" access="read"/>
 <property name="CanPause" type="b" access="read"/>
 <property name="CanSeek" type="b" access="read"/>
 <property name="CanControl" type="b" access="read"/>
</interface>
</node>"""


def variant(signature, value):
    return GLib.Variant(signature, value)


class MprisService:
    """Own one session-bus player and forward controls to the QML owner."""

    def __init__(self):
        self._lock = threading.RLock()
        self._state = self._empty_state()
        self._event_sink = None
        self._track_serial = 0
        self._connection = None
        self._loop = None
        self._thread = None
        self._registrations = []
        self._ready = threading.Event()

    @staticmethod
    def _empty_state():
        return {
            'track': None,
            'track_key': '',
            'track_id': NO_TRACK,
            'art_url': '',
            'playing': False,
            'paused': False,
            'preparing': False,
            'active': False,
            'position': 0.0,
            'duration': 0.0,
            'volume': 70.0,
            'shuffle': False,
            'repeat': False,
            'can_next': False,
            'can_previous': False,
            'can_seek': False,
        }

    def start(self, event_sink):
        self._event_sink = event_sink
        self._thread = threading.Thread(
            target=self._run, name='music-mpris', daemon=True
        )
        self._thread.start()
        if not self._ready.wait(3):
            LOG.warning('Music MPRIS service did not start in time')

    def _run(self):
        context = GLib.MainContext.new()
        context.push_thread_default()
        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
            self._connection = connection
            self._loop = GLib.MainLoop.new(context, False)
            for interface in info.interfaces:
                registration = connection.register_object(
                    OBJECT_PATH,
                    interface,
                    self._method_call,
                    self._get_property,
                    self._set_property,
                )
                self._registrations.append(registration)
            Gio.bus_own_name_on_connection(
                connection,
                BUS_NAME,
                Gio.BusNameOwnerFlags.NONE,
                self._name_acquired,
                self._name_lost,
            )
            self._ready.set()
            self._loop.run()
        except Exception:
            LOG.warning('Could not export Music over MPRIS', exc_info=True)
            self._ready.set()
        finally:
            context.pop_thread_default()

    @staticmethod
    def _name_acquired(_connection, _name):
        LOG.info('Music MPRIS service is available')

    @staticmethod
    def _name_lost(_connection, _name):
        LOG.warning('Music MPRIS service name was lost')

    def _snapshot(self):
        with self._lock:
            return dict(self._state)

    def _metadata(self, state):
        track = state['track']
        if not track:
            return variant('a{sv}', {})
        values = {'mpris:trackid': variant('o', state['track_id'])}
        title = str(track.get('title') or track.get('name') or '')[:1024]
        artist = track.get('artistNames') or track.get('artist') or ''
        artists = artist if isinstance(artist, list) else [artist]
        artists = [str(value)[:256] for value in artists if value]
        album = str(track.get('album') or '')[:512]
        length = max(0, int(state['duration'] * 1_000_000))
        if title:
            values['xesam:title'] = variant('s', title)
        if artists:
            values['xesam:artist'] = variant('as', artists)
        if album:
            values['xesam:album'] = variant('s', album)
        if length:
            values['mpris:length'] = variant('x', length)
        if state['art_url']:
            values['mpris:artUrl'] = variant('s', state['art_url'][:4096])
        return variant('a{sv}', values)

    def _property(self, name, state):
        values = {
            'PlaybackStatus': (
                's',
                'Playing'
                if state['playing']
                else 'Paused'
                if state['active'] and state['paused'] and not state['preparing']
                else 'Stopped',
            ),
            'LoopStatus': ('s', 'Playlist' if state['repeat'] else 'None'),
            'Rate': ('d', 1.0),
            'Shuffle': ('b', state['shuffle']),
            'Volume': ('d', max(0.0, min(1.0, state['volume'] / 100.0))),
            'Position': ('x', max(0, int(state['position'] * 1_000_000))),
            'MinimumRate': ('d', 1.0),
            'MaximumRate': ('d', 1.0),
            'CanGoNext': ('b', state['can_next']),
            'CanGoPrevious': ('b', state['can_previous']),
            'CanPlay': ('b', bool(state['track'])),
            'CanPause': ('b', state['active']),
            'CanSeek': ('b', state['can_seek']),
            'CanControl': ('b', True),
        }
        if name == 'Metadata':
            return self._metadata(state)
        if name in values:
            signature, value = values[name]
            return variant(signature, value)
        root_values = {
            'CanQuit': ('b', False),
            'Fullscreen': ('b', False),
            'CanSetFullscreen': ('b', False),
            'CanRaise': ('b', False),
            'HasTrackList': ('b', False),
            'Identity': ('s', 'Music'),
            'DesktopEntry': ('s', 'mpv'),
            'SupportedUriSchemes': ('as', ['file', 'http', 'https']),
            'SupportedMimeTypes': (
                'as',
                [
                    'application/ogg',
                    'audio/aac',
                    'audio/flac',
                    'audio/mp4',
                    'audio/mpeg',
                    'audio/ogg',
                    'audio/opus',
                    'audio/wav',
                ],
            ),
        }
        if name in root_values:
            signature, value = root_values[name]
            return variant(signature, value)
        return None

    def _get_property(self, _connection, _sender, _path, _interface, property_name):
        return self._property(property_name, self._snapshot())

    def _set_property(
        self,
        _connection,
        _sender,
        _path,
        interface_name,
        property_name,
        value,
    ):
        if interface_name != PLAYER:
            return False
        try:
            unpacked = value.unpack()
            if property_name == 'Shuffle':
                self._change_setting('shuffle', bool(unpacked), 'shuffle')
            elif property_name == 'LoopStatus' and unpacked in ('None', 'Playlist'):
                self._change_setting('repeat', unpacked == 'Playlist', 'repeat')
            elif property_name == 'Volume':
                self._change_setting(
                    'volume', max(0.0, min(1.0, float(unpacked))) * 100.0, 'volume'
                )
            elif property_name == 'Rate' and float(unpacked) == 1.0:
                return True
            else:
                return False
            return True
        except (TypeError, ValueError):
            return False

    def _change_setting(self, key, value, command):
        with self._lock:
            self._state[key] = value
        self._emit_properties()
        self._send_event(command, value=value)

    def _method_call(
        self,
        _connection,
        _sender,
        _path,
        interface_name,
        method_name,
        parameters,
        invocation,
    ):
        if interface_name == ROOT and method_name in ('Raise', 'Quit'):
            invocation.return_value(variant('()', ()))
            return
        if interface_name != PLAYER:
            invocation.return_dbus_error(
                'org.freedesktop.DBus.Error.UnknownMethod', 'Unknown MPRIS method.'
            )
            return

        state = self._snapshot()
        if method_name == 'Next':
            if state['can_next']:
                self._send_event('next')
        elif method_name == 'Previous':
            if state['can_previous']:
                self._send_event('previous')
        elif method_name == 'Pause':
            if state['track'] and state['playing']:
                self._send_event('pause')
        elif method_name == 'Play':
            if state['track'] and not state['playing']:
                self._send_event('play')
        elif method_name == 'PlayPause':
            if state['track']:
                self._send_event('toggle')
        elif method_name == 'Stop':
            if state['track']:
                self._send_event('stop')
        elif method_name == 'Seek':
            if state['can_seek']:
                offset = parameters.unpack()[0] / 1_000_000.0
                position = self._bounded_position(state, state['position'] + offset)
                self._send_event('seek-to', value=position)
                self._emit_seeked(position)
        elif method_name == 'SetPosition':
            track_id, position = parameters.unpack()
            if track_id == state['track_id'] and state['can_seek']:
                position = self._bounded_position(state, position / 1_000_000.0)
                self._send_event('seek-to', value=position)
                self._emit_seeked(position)
        elif method_name == 'OpenUri':
            uri = parameters.unpack()[0]
            parsed = urllib.parse.urlsplit(uri)
            scheme = parsed.scheme.lower()
            if scheme not in ('file', 'http', 'https') or (
                scheme == 'file' and parsed.netloc not in ('', 'localhost')
            ):
                invocation.return_dbus_error(
                    'org.mpris.MediaPlayer2.Player.Error.NotSupported',
                    'Music supports local files and HTTP(S) URIs.',
                )
                return
            self._send_event('open-uri', value=uri)
        else:
            invocation.return_dbus_error(
                'org.freedesktop.DBus.Error.UnknownMethod', 'Unknown MPRIS method.'
            )
            return
        invocation.return_value(variant('()', ()))

    def _send_event(self, command, **values):
        sink = self._event_sink
        if sink:
            sink({'source': 'mpris', 'command': command, **values})

    @staticmethod
    def _bounded_position(state, position):
        position = max(0.0, float(position))
        return min(position, state['duration']) if state['duration'] > 0 else position

    def _emit_seeked(self, position):
        connection = self._connection
        if not connection:
            return
        try:
            connection.emit_signal(
                None,
                OBJECT_PATH,
                PLAYER,
                'Seeked',
                variant('(x)', (max(0, int(position * 1_000_000)),)),
            )
        except GLib.Error:
            LOG.debug('Could not publish Music MPRIS seek position', exc_info=True)

    def update(self, value):
        if not isinstance(value, dict):
            return
        with self._lock:
            previous = self._state
            track = value.get('track')
            track = track if isinstance(track, dict) else None
            track_key = str(value.get('trackKey') or '')
            track_id = previous['track_id']
            if track and track_key != previous['track_key']:
                self._track_serial += 1
                track_id = f'/org/mpris/MediaPlayer2/Track/t{self._track_serial}'
            elif not track:
                track_id = NO_TRACK
            state = {
                'track': track,
                'track_key': track_key if track else '',
                'track_id': track_id,
                'art_url': str(value.get('artUrl') or '')[:4096],
                'playing': bool(value.get('playing')),
                'paused': bool(value.get('paused')),
                'preparing': bool(value.get('preparing')),
                'active': bool(value.get('active')),
                'position': max(0.0, float(value.get('position') or 0)),
                'duration': max(0.0, float(value.get('duration') or 0)),
                'volume': max(0.0, min(100.0, float(value.get('volume') or 0))),
                'shuffle': bool(value.get('shuffleEnabled')),
                'repeat': bool(value.get('repeatAllEnabled')),
                'can_next': bool(value.get('canNext')),
                'can_previous': bool(value.get('canPrevious')),
                'can_seek': bool(value.get('canSeek')),
            }
            changed = any(
                (
                    previous['track_key'] != state['track_key'],
                    previous['track'] != state['track'],
                    previous['art_url'] != state['art_url'],
                    previous['playing'] != state['playing'],
                    previous['paused'] != state['paused'],
                    previous['preparing'] != state['preparing'],
                    previous['active'] != state['active'],
                    previous['duration'] != state['duration'],
                    previous['volume'] != state['volume'],
                    previous['shuffle'] != state['shuffle'],
                    previous['repeat'] != state['repeat'],
                    previous['can_next'] != state['can_next'],
                    previous['can_previous'] != state['can_previous'],
                    previous['can_seek'] != state['can_seek'],
                )
            )
            self._state = state
        if changed:
            self._emit_properties()

    def _emit_properties(self):
        connection = self._connection
        if not connection:
            return
        state = self._snapshot()
        changed = {
            'PlaybackStatus': self._property('PlaybackStatus', state),
            'LoopStatus': self._property('LoopStatus', state),
            'Shuffle': self._property('Shuffle', state),
            'Metadata': self._property('Metadata', state),
            'Volume': self._property('Volume', state),
            'CanGoNext': self._property('CanGoNext', state),
            'CanGoPrevious': self._property('CanGoPrevious', state),
            'CanPlay': self._property('CanPlay', state),
            'CanPause': self._property('CanPause', state),
            'CanSeek': self._property('CanSeek', state),
        }
        try:
            connection.emit_signal(
                None,
                OBJECT_PATH,
                'org.freedesktop.DBus.Properties',
                'PropertiesChanged',
                variant('(sa{sv}as)', (PLAYER, changed, [])),
            )
        except GLib.Error:
            LOG.debug('Could not publish Music MPRIS state', exc_info=True)
