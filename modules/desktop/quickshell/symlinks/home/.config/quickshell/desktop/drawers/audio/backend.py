"""Audio inventory and explicit actions over PipeWire's PulseAudio interface."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time


CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'devices/audio'


def command(*args):
    result = subprocess.run(['pactl', *map(str, args)], capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise ValueError('Audio service unavailable or the device changed. Refresh and try again.')
    return result.stdout


def read(kind):
    return json.loads(command('-f', 'json', 'list', kind))


def entries(value):
    if isinstance(value, dict):
        return [dict(v, name=k) for k, v in value.items()]
    return value or []


def available(value):
    return value not in (False, 'no', 'not available')


def read_config(path):
    config = json.loads(path.read_text())
    if not isinstance(config, dict) or not isinstance(config.get('rules', []), list):
        raise ValueError('expected an object containing rules')
    profiles = config.get('profiles', {})
    if not isinstance(profiles, dict) or any(not isinstance(label, str) or not label.strip() for label in profiles.values()):
        raise ValueError('profile names must be non-empty strings')
    for rule in config.get('rules', []):
        if not isinstance(rule, dict) or not isinstance(rule.get('label'), str) or not rule['label'].strip():
            raise ValueError('each rule needs a label')
        if 'deviceLabel' in rule and (not isinstance(rule['deviceLabel'], str) or not rule['deviceLabel'].strip()):
            raise ValueError('deviceLabel must be a non-empty string')
        if not rule.get('match') and not rule.get('contains'):
            raise ValueError('each rule needs match or contains properties')
        for key in ('match', 'contains'):
            if not isinstance(rule.get(key, {}), dict) or any(not isinstance(v, str) for v in rule.get(key, {}).values()):
                raise ValueError('matching values must be strings')
        if rule.get('icon', 'volume-2') not in ('volume-2', 'headphones', 'monitor', 'bluetooth', 'speaker', 'mic', 'mic-off'):
            raise ValueError('unknown device icon')
        limit = rule.get('maxVolume', 150)
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or not 1 <= limit <= 150:
            raise ValueError('maxVolume must be between 1 and 150')
        priority = rule.get('priority', 0)
        if isinstance(priority, bool) or not isinstance(priority, (int, float)) or not math.isfinite(priority):
            raise ValueError('rule priority must be a finite number')
    return config


def load_config(directory=CONFIG_DIR):
    config = {'rules': [], 'profiles': {}}
    warnings = []
    try:
        paths = sorted(p for p in directory.iterdir() if p.suffix == '.json' and p.is_file())
    except FileNotFoundError:
        return config, ''
    except OSError as error:
        return config, f'Could not read {directory}: {error}. Using reported device names.'
    for path in paths:
        try:
            fragment = read_config(path)
            profiles = fragment.get('profiles', {})
            conflicts = [name for name, label in profiles.items()
                         if name in config['profiles'] and config['profiles'][name] != label]
            if conflicts:
                raise ValueError('conflicting profile labels: ' + ', '.join(conflicts))
            config['rules'].extend(fragment.get('rules', []))
            config['profiles'].update(profiles)
        except (OSError, ValueError, TypeError) as error:
            warnings.append(f'Could not load {path.name}: {error}. Skipping this file.')
    return config, '\n'.join(warnings)


def identity(sink, port):
    return {**sink.get('properties', {}), **port.get('properties', {}),
            'node.name': sink['name'], 'node.description': sink.get('description', ''),
            'port.name': port.get('name', ''), 'port.description': port.get('description', '')}


def matching_rules(node, port, config):
    props = identity(node, port)
    rules = sorted(config.get('rules', []), key=lambda rule: rule.get('priority', 0), reverse=True)
    return [r for r in rules if all(str(props.get(k, '')) == v for k, v in r.get('match', {}).items())
            and all(v in str(props.get(k, '')) for k, v in r.get('contains', {}).items())]


def describe(sink, port, config):
    props = identity(sink, port)
    rule = next(iter(matching_rules(sink, port, config)), {})
    description = sink.get('description') or sink['name']
    port_name = port.get('description', '')
    if port.get('name', '').startswith('hdmi-output-') and port['name'].rsplit('-', 1)[-1].isdigit():
        connection = 'Display connection ' + str(int(port['name'].rsplit('-', 1)[-1]) + 1)
    elif sink['name'].rsplit('.', 1)[-1].startswith('pro-output-'):
        connection = sink['name'].rsplit('.', 1)[-1].replace('pro-output-', 'Hardware output ')
    else:
        connection = port_name or sink.get('properties', {}).get('device.profile.description') or sink['name'].rsplit('.', 1)[-1].replace('-', ' ')
    label = rule.get('label', '').replace('{port}', connection) or (f'{description} · {port_name}' if port_name and port_name.lower() not in description.lower() else description)
    kind = str(port.get('type', '')).lower()
    icon = rule.get('icon') or ('headphones' if kind in ('headphones', 'headset') else 'monitor' if kind in ('hdmi', 'displayport')
                               else 'mic' if props.get('media.class') == 'Audio/Source' or kind in ('mic', 'microphone')
                               else 'bluetooth' if sink['name'].startswith('bluez_') else 'speaker')
    return dict(label=label, icon=icon, maxVolume=rule.get('maxVolume', 150), properties=props)


def gain(node):
    return max((channel.get('value', 0) for channel in node.get('volume', {}).values()), default=0) / 65536 * 100


def volume(node):
    return round(gain(node))


def limit_volume(kind, node, ceiling):
    """Lower gain without changing channel balance, mute, defaults or routing."""
    levels = [channel.get('value', 0) for channel in node.get('volume', {}).values()]
    peak = max(levels, default=0)
    cap = int(ceiling * 65536 / 100)
    if peak > cap:
        command('set-' + kind + '-volume', node['name'] if kind == 'sink' else node['index'],
                *(value * cap // peak for value in levels))


def stream_token(stream):
    # Pulse indices may be reused after an app exits; include the PipeWire serial.
    return str(stream.get('properties', {}).get('object.serial', stream['index']))


def card_for(node, cards):
    props = node.get('properties', {})
    return next((card for card in cards if card['name'] == props.get('device.name')
                 or str(card['index']) == str(node.get('card', props.get('device.id')))), None)


def capture_source(node):
    return node.get('properties', {}).get('device.class') != 'monitor' and not node['name'].endswith('.monitor')


def profile_parts(profile):
    parts = profile['name'].split('+')
    if all(part.startswith(('output:', 'input:')) for part in parts):
        return tuple(sorted(p for p in parts if p.startswith('output:'))), tuple(sorted(p for p in parts if p.startswith('input:')))
    return ((profile['name'],) if profile.get('sinks', 0) else ()), ()


def current_profile(card):
    return next((p for p in entries(card.get('profiles', {})) if p['name'] == card.get('active_profile')), {})


def resolve_profile(card, playback=None, capture=None, port=None):
    current = current_profile(card)
    if not current:
        return None
    outputs, inputs = profile_parts(current)
    playback = outputs if playback is None else playback
    capture = bool(current.get('sources', 0)) if capture is None else capture
    candidates = [p for p in entries(card.get('profiles', {}))
                  if available(p.get('available')) and profile_parts(p)[0] == playback
                  and bool(p.get('sources', 0)) == capture]
    route = next((p for p in entries(card.get('ports', {})) if p['name'] == port), None)
    if route and route.get('profiles'):
        candidates = [p for p in candidates if p['name'] in route['profiles']]
    return max(candidates, key=lambda p: (p['name'] == current['name'], profile_parts(p)[1] == inputs,
                                         p.get('priority', 0)), default=None)


def playback_profiles(card, config, port=None):
    active = current_profile(card)
    if not active:
        return []
    modes = {}
    for profile in entries(card.get('profiles', {})):
        if not available(profile.get('available')) or not profile.get('sinks'):
            continue
        outputs, _ = profile_parts(profile)
        name = '+'.join(outputs)
        if name in modes:
            continue
        target = resolve_profile(card, outputs, port=port)
        label = config.get('profiles', {}).get(name, profile.get('description', name).split(' + ')[0])
        modes[name] = dict(name=name, label=label, selected=profile_parts(active)[0] == outputs,
                           enabled=target is not None, description=profile.get('description', name),
                           reason='' if target else 'This mode cannot preserve the current microphone or output connection.')
    return list(modes.values())


def endpoint_match(old, candidates, allow_fallback=True):
    exact = [n for n in candidates if n['name'] == old['name']]
    if exact:
        return exact[0]
    device = old.get('properties', {}).get('alsa.device')
    same_device = [n for n in candidates if device is not None and n.get('properties', {}).get('alsa.device') == device]
    if len(same_device) == 1:
        return same_device[0]
    return candidates[0] if allow_fallback and len(candidates) == 1 else None


def select_port(direction, node, port):
    """Wait for session policy to restore the route before overriding its state."""
    command('set-' + direction + '-port', node['name'], port)
    deadline = time.monotonic() + 2
    previous, stable_since = None, None
    while True:
        updated = next((n for n in read(direction + 's') if n['name'] == node['name']), None)
        if not updated:
            raise ValueError('The audio device was disconnected while changing connections.')
        now = time.monotonic()
        # WirePlumber restores route properties asynchronously. Require a quiet
        # interval on the requested route before applying volume/mute overrides.
        levels = tuple(sorted((name, channel.get('value')) for name, channel in updated.get('volume', {}).items()))
        state = (updated.get('active_port'), updated.get('mute'), levels)
        if updated.get('active_port') != port or state != previous:
            stable_since = None
        elif stable_since is None:
            stable_since = now
        elif now - stable_since >= 0.12:
            return updated
        if now >= deadline:
            raise ValueError('The audio connection did not finish changing. Refresh to retry.')
        previous = state
        time.sleep(0.04)


def change_profile(card, target):
    """One card transition, preserving routes and levels on recreated endpoints."""
    if target['name'] == card['active_profile']:
        return
    info = json.loads(command('-f', 'json', 'info'))
    before = {kind: [n for n in read(kind) if card_for(n, [card]) and (kind == 'sinks' or capture_source(n))]
              for kind in ('sinks', 'sources')}
    streams = {kind: read(kind) for kind in ('sink-inputs', 'source-outputs')}

    def restore(profile):
        deadline = time.monotonic() + 2
        while True:
            after = {kind: [n for n in read(kind) if card_for(n, [card]) and (kind == 'sinks' or capture_source(n))]
                     for kind in ('sinks', 'sources')}
            if len(after['sinks']) >= profile.get('sinks', 0) and len(after['sources']) >= profile.get('sources', 0):
                break
            if time.monotonic() >= deadline:
                raise ValueError('The audio device did not finish changing mode.')
            time.sleep(0.04)
        for kind, direction, stream_kind in (('sinks', 'sink', 'sink-inputs'), ('sources', 'source', 'source-outputs')):
            restored = set()
            for old in before[kind]:
                node = endpoint_match(old, [n for n in after[kind] if n['name'] not in restored],
                                      allow_fallback=len(before[kind]) == 1)
                if not node:
                    continue
                restored.add(node['name'])
                port = old.get('active_port')
                if port and any(p['name'] == port and available(p.get('availability')) for p in entries(node.get('ports'))):
                    node = select_port(direction, node, port)
                levels = [v['value'] for v in old.get('volume', {}).values()]
                if levels:
                    levels = levels if len(levels) == len(node.get('volume', {})) else [str(volume(old)) + '%']
                    command('set-' + direction + '-volume', node['name'], *levels)
                command('set-' + direction + '-mute', node['name'], '1' if old.get('mute') else '0')
                if old['name'] == info.get('default_' + direction + '_name'):
                    command('set-default-' + direction, node['name'])
                live = read(stream_kind)
                for stream in streams[stream_kind]:
                    if stream.get(direction) == old['index'] and any(s['index'] == stream['index'] and stream_token(s) == stream_token(stream) for s in live):
                        command('move-' + stream_kind[:-1], stream['index'], node['name'])
            if kind == 'sources':
                for node in after[kind]:
                    if node['name'] not in restored:
                        port = next((p for p in entries(node.get('ports')) if p['name'] == node.get('active_port')
                                     and available(p.get('availability'))), None)
                        if port:
                            select_port('source', node, port['name'])
                        command('set-source-mute', node['name'], '1')
        # An unaffected default (for example a monitor) must also survive policy
        # reacting to newly created nodes on this card.
        for kind, direction in (('sinks', 'sink'), ('sources', 'source')):
            wanted = info.get('default_' + direction + '_name')
            if any(n['name'] == wanted and (kind == 'sinks' or capture_source(n)) for n in read(kind)):
                command('set-default-' + direction, wanted)
        return after

    command('set-card-profile', card['name'], target['name'])
    try:
        restore(target)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        try:
            command('set-card-profile', card['name'], card['active_profile'])
            restore(current_profile(card))
        except (ValueError, OSError, subprocess.SubprocessError):
            raise ValueError('The audio mode change failed and could not be restored. Refresh the devices.') from error
        raise ValueError('The audio mode change failed; the previous mode was restored.') from error


def stream_records(streams, direction):
    result = []
    for stream in streams:
        props = stream.get('properties', {})
        if props.get('application.id') == 'dotfiles.audio-test':
            continue
        result.append(dict(key=str(stream['index']) + ':' + stream_token(stream), index=stream['index'], token=stream_token(stream),
                           label=props.get('application.name') or props.get('media.name') or stream.get('name') or 'Audio application',
                           detail=props.get('media.name', ''), icon=props.get('application.icon_name', ''),
                           applicationId=props.get('application.id', ''), applicationBinary=props.get('application.process.binary', ''),
                           **{direction: stream.get(direction)}, volume=volume(stream), muted=bool(stream.get('mute')),
                           recording=not stream.get('corked', False),
                           hasVolume=stream.get('has_volume', True), canVolume=stream.get('volume_writable', True)))
    return sorted(result, key=lambda app: (app['label'].lower(), app['key']))


def capture_ports(card):
    """Card ports are connections, not independent capture endpoints."""
    return [p for p in entries(card.get('ports')) if p.get('direction') in ('input', 2)
            or p.get('type') in ('Mic', 'Microphone')
            or p['name'].startswith(('analog-input-', 'input:', 'headset-input', 'handsfree-input'))]


def input_inventory(sources, cards, config, default):
    inputs, devices = [], []
    for source in sources:
        card = card_for(source, cards)
        ports = entries(source.get('ports'))
        active_port = next((p for p in ports if p['name'] == source.get('active_port')), {})
        routes = [dict(name=p['name'], label=describe(source, p, config)['label'],
                       selected=p['name'] == source.get('active_port'))
                  for p in ports if available(p.get('availability'))]
        inputs.append(dict(key=source['name'], name=source['name'], index=source['index'],
                           deviceKey=card['name'] if card else source['name'],
                           port=source.get('active_port', ''), routes=routes,
                           portLabel=active_port.get('description', ''),
                           available=not ports or bool(routes), selected=source['name'] == default,
                           muted=bool(source.get('mute')), volume=volume(source),
                           **describe(source, active_port, config)))
    for card in cards:
        owned = [n for n in inputs if n['deviceKey'] == card['name']]
        if not owned and not any(p.get('sources', 0) for p in entries(card.get('profiles'))):
            continue
        ports = capture_ports(card)
        connected = sorted((p for p in ports if available(p.get('availability'))),
                           key=lambda p: -p.get('priority', 0))
        enabled = bool(current_profile(card).get('sources', 0)) or bool(owned)
        # Disabled devices have no source yet; keep hardware availability separate.
        target = resolve_profile(card, capture=not enabled)
        port = next((p['name'] for p in connected if resolve_profile(card, capture=True, port=p['name'])), '') if not enabled else ''
        if not enabled and ports and not port:
            target = None
        node = dict(name=card['name'], description=card.get('properties', {}).get('device.description', card['name']),
                    properties={**card.get('properties', {}), 'device.name': card['name'], 'media.class': 'Audio/Source'})
        # Presentation slots reserve input rows while capture is disabled. They
        # contain no live endpoint identity and cannot be used for audio actions.
        capture = resolve_profile(card, capture=True, port=port)
        if not capture:
            capture = max((p for p in entries(card.get('profiles')) if p.get('sources', 0) and available(p.get('available'))),
                          key=lambda p: p.get('priority', 0), default={})
        routes = [dict(name=p['name'], label=describe(node, p, config)['label'], selected=p['name'] == port)
                  for p in connected]
        slot_count = max(1, capture.get('sources', 0))
        slots = [dict(key=card['name'] + '/input/' + str(i),
                      label=describe(node, next((p for p in connected if p['name'] == port), {}), config)['label'] if slot_count == 1 else 'Input ' + str(i + 1),
                      routes=routes if slot_count == 1 else []) for i in range(slot_count)]
        device = dict(key=card['name'], card=card['name'], profile=card.get('active_profile', ''),
                      label=describe(node, {}, config)['label'], port=port, enabled=enabled,
                      available=any(n['available'] for n in owned) or not ports or bool(connected),
                      canToggle=target is not None, inputSlots=slots,
                      toggleReason='' if target else 'Changing microphone availability requires a different playback mode. Use mute or advanced settings.')
        devices.append(device)
    for source in inputs:
        if any(d['key'] == source['deviceKey'] for d in devices):
            continue
        devices.append(dict(key=source['deviceKey'], card='', profile='', label=source['label'], port='',
                            enabled=True, available=source['available'], canToggle=False, inputSlots=[],
                            toggleReason='This input does not support disabling. Use mute instead.'))
    # Stable device order: making a default must not move the slider under a pointer.
    devices.sort(key=lambda d: (d['label'].lower(), d['key']))
    inputs.sort(key=lambda n: (n['label'].lower(), n['key']))
    return inputs, devices


def output_inventory(sinks, cards, config, default):
    outputs, devices = [], []
    for sink in sinks:
        card = card_for(sink, cards)
        ports = entries(sink.get('ports'))
        active = next((p for p in ports if p['name'] == sink.get('active_port')), {})
        routes = [dict(name=p['name'], label=describe(sink, p, config)['label'],
                       selected=p['name'] == sink.get('active_port'))
                  for p in ports if available(p.get('availability'))]
        outputs.append(dict(key=sink['name'], name=sink['name'], index=sink['index'],
                            deviceKey=card['name'] if card else sink['name'],
                            port=sink.get('active_port', ''), portLabel=active.get('description', ''), routes=routes,
                            available=not ports or bool(routes), selected=sink['name'] == default,
                            muted=bool(sink.get('mute')), volume=volume(sink), **describe(sink, active, config)))
    for output in outputs:
        if any(d['key'] == output['deviceKey'] for d in devices):
            continue
        card = next((c for c in cards if c['name'] == output['deviceKey']), None)
        if card:
            node = dict(name=card['name'], properties={**card.get('properties', {}), 'device.name': card['name']})
            label = next((r['deviceLabel'] for r in matching_rules(node, {}, config) if 'deviceLabel' in r),
                         card.get('properties', {}).get('device.description', card['name']))
            owned = [o for o in outputs if o['deviceKey'] == card['name']]
            modes = playback_profiles(card, config, owned[0]['port'] if len(owned) == 1 else None)
        else:
            label, modes = output['label'], []
        devices.append(dict(key=output['deviceKey'], label=label, card=card['name'] if card else '',
                            profile=card.get('active_profile', '') if card else '', profiles=modes,
                            available=any(o['available'] for o in outputs if o['deviceKey'] == output['deviceKey'])))
    devices.sort(key=lambda d: (d['label'].lower(), d['key']))
    outputs.sort(key=lambda o: (o['label'].lower(), o['key']))
    return outputs, devices


def snapshot(config_dir=CONFIG_DIR):
    config, warning = load_config(config_dir)
    info = json.loads(command('-f', 'json', 'info'))
    sinks, cards, streams = read('sinks'), read('cards'), read('sink-inputs')
    sources = [n for n in read('sources') if capture_source(n)]
    outputs, output_devices = output_inventory(sinks, cards, config, info.get('default_sink_name'))
    inputs, input_devices = input_inventory(sources, cards, config, info.get('default_source_name'))
    return dict(available=True, outputs=outputs, outputDevices=output_devices, streams=stream_records(streams, 'sink'),
                inputs=inputs, inputDevices=input_devices, recordings=stream_records(read('source-outputs'), 'source'), warning=warning)


def control(request, config_dir=CONFIG_DIR):
    op = request.get('op', 'status')
    if op == 'status':
        return
    if op not in ('output-default', 'output-port', 'output-boost', 'volume', 'mute', 'move', 'profile', 'input-default', 'input-port', 'input-enabled'):
        raise ValueError('Unknown audio action.')
    config, _ = load_config(config_dir)
    if op == 'output-boost':
        if not isinstance(request.get('enabled'), bool):
            raise ValueError('Expected a boost enabled state.')
        cards = read('cards')
        owned = [sink for sink in read('sinks') if (card_for(sink, cards) or sink)['name'] == request.get('device')]
        if not owned:
            raise ValueError('This audio device was disconnected.')
        if not request['enabled']:
            for sink in owned:
                port = next((p for p in entries(sink.get('ports')) if p['name'] == sink.get('active_port')), {})
                limit_volume('sink', sink, min(100, describe(sink, port, config)['maxVolume']))
            indices = {sink['index'] for sink in owned}
            for stream in read('sink-inputs'):
                if stream.get('sink') in indices:
                    limit_volume('sink-input', stream, 100)
        return
    if op == 'profile':
        card = next((c for c in read('cards') if c['name'] == request.get('card')), None)
        if not card or card.get('active_profile') != request.get('previous'):
            raise ValueError('The audio profile changed. Refresh before trying again.')
        owned = [sink for sink in read('sinks') if card_for(sink, [card])]
        if not owned:
            raise ValueError('This audio device was disconnected.')
        profile = resolve_profile(card, tuple(request.get('profile', '').split('+')),
                                  port=owned[0].get('active_port') if len(owned) == 1 else None)
        if not profile or not profile.get('sinks'):
            raise ValueError('This playback profile is unavailable.')
        change_profile(card, profile)
        return
    if op in ('output-default', 'output-port'):
        sink = next((node for node in read('sinks') if node['name'] == request.get('name')), None)
        if not sink:
            raise ValueError('This output was disconnected. Choose another device.')
        ports = entries(sink.get('ports'))
        if op == 'output-port':
            port = next((p for p in ports if p['name'] == request.get('port')), None)
            if not port or not available(port.get('availability')):
                raise ValueError('This output connection is disconnected.')
            cap = min(describe(sink, port, config)['maxVolume'], 150 if request.get('boost') is True else 100)
            muted = bool(sink.get('mute'))
            limit_volume('sink', sink, cap)
            updated = select_port('sink', sink, port['name'])
            limit_volume('sink', updated, cap)
            command('set-sink-mute', sink['name'], '1' if muted else '0')
        else:
            active = next((p for p in ports if p['name'] == sink.get('active_port')), {})
            if not available(active.get('availability')):
                raise ValueError('Choose a connected output connection first.')
            command('set-default-sink', sink['name'])
        # Defaults follow session-manager policy; no forced stream migration.
        return
    if op == 'input-enabled':
        enabled = request.get('enabled')
        if not isinstance(enabled, bool):
            raise ValueError('Expected a microphone input enabled state.')
        card = next((c for c in read('cards') if c['name'] == request.get('card')), None)
        if not card or card.get('active_profile') != request.get('previous'):
            raise ValueError('The audio profile changed. Refresh before trying again.')
        port_name = request.get('port', '') if enabled else ''
        if port_name:
            port = next((p for p in capture_ports(card) if p['name'] == port_name), None)
            if not port or not available(port.get('availability')):
                raise ValueError('This microphone connection is disconnected.')
        target = resolve_profile(card, capture=enabled, port=port_name)
        if not target:
            raise ValueError('This device cannot change input availability while keeping its playback mode. Use mute or advanced settings.')
        change_profile(card, target)
        if enabled and port_name:
            candidates = [n for n in read('sources') if capture_source(n) and card_for(n, [card])]
            source = next((n for n in candidates if any(p['name'] == port_name for p in entries(n.get('ports')))), None)
            if not source:
                raise ValueError('The microphone did not become available. Refresh to retry.')
            select_port('source', source, port_name)
            command('set-source-mute', source['name'], '1')
        # Enabling availability neither unmutes nor selects a new default.
        return
    if op in ('input-default', 'input-port'):
        source = next((n for n in read('sources') if n['name'] == request.get('name') and capture_source(n)), None)
        if not source:
            raise ValueError('This microphone is disconnected.')
        ports = entries(source.get('ports'))
        if op == 'input-port':
            port = next((p for p in ports if p['name'] == request.get('port')), None)
            if not port or not available(port.get('availability')):
                raise ValueError('This microphone connection is disconnected.')
            muted = bool(source.get('mute'))
            select_port('source', source, port['name'])
            command('set-source-mute', source['name'], '1' if muted else '0')
        else:
            active = next((p for p in ports if p['name'] == source.get('active_port')), {})
            if not available(active.get('availability')):
                raise ValueError('Choose a connected microphone connection first.')
            command('set-default-source', source['name'])
            # WirePlumber decides which default-following streams move. Explicit
            # app routes are changed only by the per-application move action.
        return
    sink = None
    if request.get('kind') in ('stream', 'recording'):
        stream_kind = 'source-outputs' if request['kind'] == 'recording' else 'sink-inputs'
        node = next((s for s in read(stream_kind) if str(s['index']) == str(request.get('index'))
                     and stream_token(s) == request.get('token')), None)
        if not node:
            raise ValueError('This application stream has ended. Refresh and try again.')
        target, kind = str(node['index']), stream_kind[:-1]
    elif request.get('kind') == 'source':
        node = next((n for n in read('sources') if n['name'] == request.get('name') and capture_source(n)), None)
        if not node:
            raise ValueError('This microphone is disconnected.')
        target, kind = node['name'], 'source'
    else:
        sink = next((s for s in read('sinks') if s['name'] == request.get('name')), None)
        if not sink:
            raise ValueError('This output was disconnected. Choose another device.')
        node, target, kind = sink, sink['name'], 'sink'
    if op == 'volume':
        value = request.get('value')
        port = next((p for p in entries(node.get('ports')) if p['name'] == node.get('active_port')), {})
        limit = describe(node, port, config)['maxVolume'] if sink else 150
        allowed = 100 if kind in ('source', 'source-output') else min(limit, 150 if request.get('boost') is True else 100)
        # An externally boosted level may always be reduced without permitting
        # any further increase above the configured limit.
        ceiling = max(allowed, gain(node))
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= ceiling:
            raise ValueError(f'Volume must be between 0 and {ceiling}%.')
        if kind in ('sink-input', 'source-output') and (not node.get('has_volume', True) or not node.get('volume_writable', True)):
            raise ValueError('This application does not expose volume controls.')
        command('set-' + kind + '-volume', target, f'{value:g}%')
        # Volume and mute are independent: dragging never unexpectedly unmutes.
    elif op == 'mute':
        if not isinstance(request.get('muted'), bool):
            raise ValueError('Expected a mute state.')
        command('set-' + kind + '-mute', target, '1' if request['muted'] else '0')
    elif op == 'move':
        if kind not in ('sink-input', 'source-output'):
            raise ValueError('Choose an application stream.')
        recording = kind == 'source-output'
        destination = next((n for n in read('sources' if recording else 'sinks')
                            if n['name'] == request.get('destination') and (not recording or capture_source(n))), None)
        if not destination:
            raise ValueError('The destination was disconnected.')
        port = next((p for p in entries(destination.get('ports')) if p['name'] == destination.get('active_port')), {})
        if not available(port.get('availability')):
            raise ValueError('The destination connection is disconnected.')
        if not recording and request.get('boost') is not True:
            limit_volume('sink-input', node, 100)
        command('move-' + kind, target, destination['name'])


def main():
    try:
        request = json.loads(sys.stdin.readline())
        control(request)
        result = dict(ok=True, data=snapshot())
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        result = dict(ok=False, error=str(error) if isinstance(error, ValueError) else 'Could not contact the audio service. Refresh to retry.')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
