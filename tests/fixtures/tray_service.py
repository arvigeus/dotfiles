"""A test-only SNI/DBusMenu publisher, intended for a private dbus-run-session."""

import json
import sys
from gi.repository import Gio, GLib

ITEM = """<node><interface name="org.kde.StatusNotifierItem">
<property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/>
<property name="Status" type="s" access="read"/>
<property name="Category" type="s" access="read"/>
<property name="WindowId" type="i" access="read"/>
<property name="IconThemePath" type="s" access="read"/>
<property name="IconName" type="s" access="read"/>
<property name="IconPixmap" type="a(iiay)" access="read"/>
<property name="OverlayIconName" type="s" access="read"/>
<property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionIconName" type="s" access="read"/>
<property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
<property name="AttentionMovieName" type="s" access="read"/>
<property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
<property name="ItemIsMenu" type="b" access="read"/>
<property name="Menu" type="o" access="read"/>
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<signal name="NewStatus"><arg type="s"/></signal>
<signal name="NewMenu"/>
</interface></node>"""
MENU = """<node><interface name="com.canonical.dbusmenu">
<property name="Version" type="u" access="read"/>
<property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/>
<property name="IconThemePath" type="as" access="read"/>
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
</interface></node>"""


def emit(**record):
    print(json.dumps(record), flush=True)


def properties(**values):
    return {
        key.replace('_', '-'): GLib.Variant(
            'b' if isinstance(value, bool) else 'i' if isinstance(value, int) else 's',
            value,
        )
        for key, value in values.items()
    }


entries = {
    0: properties(children_display='submenu'),
    1: properties(
        label='_Open', enabled=True, visible=True, icon_name='edit-find-symbolic'
    ),
    2: properties(
        label='Keep running',
        enabled=True,
        visible=True,
        toggle_type='checkmark',
        toggle_state=1,
    ),
    3: properties(type='separator'),
    4: properties(label='More', enabled=True, visible=True, children_display='submenu'),
    5: properties(label='Nested action', enabled=True, visible=True),
    6: properties(label='Unavailable action', enabled=False, visible=True),
}
children = {0: [1, 2, 3, 4, 6], 4: [5]}


def layout(identifier):
    return GLib.Variant(
        '(ia{sv}av)',
        (
            identifier,
            entries[identifier],
            [layout(child) for child in children.get(identifier, [])],
        ),
    )


bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
loop = GLib.MainLoop()
status = 'Active'


def get_property(connection, sender, path, interface, name):
    if interface == 'com.canonical.dbusmenu':
        return {
            'Version': GLib.Variant('u', 4),
            'TextDirection': GLib.Variant('s', 'ltr'),
            'Status': GLib.Variant('s', 'normal'),
            'IconThemePath': GLib.Variant('as', []),
        }[name]
    if name.endswith('Pixmap'):
        return GLib.Variant('a(iiay)', [])
    return {
        'Id': GLib.Variant('s', 'fixture-app'),
        'Title': GLib.Variant('s', 'Tray fixture'),
        'Status': GLib.Variant('s', status),
        'Category': GLib.Variant('s', 'ApplicationStatus'),
        'WindowId': GLib.Variant('i', 0),
        'IconThemePath': GLib.Variant('s', ''),
        'IconName': GLib.Variant('s', 'folder'),
        'OverlayIconName': GLib.Variant('s', ''),
        'AttentionIconName': GLib.Variant('s', ''),
        'AttentionMovieName': GLib.Variant('s', ''),
        'ToolTip': GLib.Variant(
            '(sa(iiay)ss)', ('', [], 'Tray fixture', 'Native app menu')
        ),
        'ItemIsMenu': GLib.Variant('b', False),
        'Menu': GLib.Variant('o', '/Menu'),
    }[name]


def method(connection, sender, path, interface, name, parameters, invocation):
    args = parameters.unpack()
    if interface == 'com.canonical.dbusmenu':
        if name == 'GetLayout':
            invocation.return_value(
                GLib.Variant(
                    '(u(ia{sv}av))',
                    (
                        1,
                        (
                            args[0],
                            entries[args[0]],
                            [layout(child) for child in children.get(args[0], [])],
                        ),
                    ),
                )
            )
            return
        if name == 'GetGroupProperties':
            invocation.return_value(
                GLib.Variant('(a(ia{sv}))', ([(i, entries[i]) for i in args[0]],))
            )
            return
        if name == 'AboutToShow':
            invocation.return_value(GLib.Variant('(b)', (False,)))
            return
        if name == 'Event':
            emit(action='menu', identifier=args[0], event=args[1])
    else:
        emit(action=name, args=args)
    invocation.return_value(None)


for path, xml in (('/StatusNotifierItem', ITEM), ('/Menu', MENU)):
    bus.register_object(
        path,
        Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0],
        method,
        get_property,
        None,
    )


def appeared(connection, name, owner):
    def registered(connection, result):
        try:
            connection.call_finish(result)
            emit(action='registered')
        except GLib.Error as error:
            emit(error=str(error))

    connection.call(
        name,
        '/StatusNotifierWatcher',
        'org.kde.StatusNotifierWatcher',
        'RegisterStatusNotifierItem',
        GLib.Variant('(s)', (bus.get_unique_name(),)),
        None,
        Gio.DBusCallFlags.NONE,
        5000,
        None,
        registered,
    )


Gio.bus_watch_name_on_connection(
    bus, 'org.kde.StatusNotifierWatcher', Gio.BusNameWatcherFlags.NONE, appeared, None
)


def command(stream, condition):
    global status
    line = stream.readline()
    if not line:
        loop.quit()
        return False
    request = json.loads(line)
    if request['op'] == 'status':
        status = request['value']
        bus.emit_signal(
            None,
            '/StatusNotifierItem',
            'org.kde.StatusNotifierItem',
            'NewStatus',
            GLib.Variant('(s)', (status,)),
        )
    elif request['op'] == 'exit':
        loop.quit()
        return False
    return True


GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, command)
loop.run()
