#!/usr/bin/env python3
"""Private location inventory, timezone clocks and cached Open-Meteo forecasts."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from collections import Counter
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TTL = 30 * 60


class LocationError(RuntimeError):
    pass


def config_dir():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'quickshell/desktop'


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def number(value, lower=-math.inf, upper=math.inf):
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def locations():
    data = read_json(config_dir() / 'weather.json', {})
    if not isinstance(data, dict) or not isinstance(data.get('locations', []), list):
        raise ValueError('Invalid weather.json: expected a locations list.')
    rows = data.get('locations', [])
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not row[key].strip()
                                           for key in ('id', 'name', 'timezone')):
            raise ValueError('Each location needs an id, name and timezone.')
        if row['id'] in ids or not number(row.get('latitude'), -90, 90) or not number(row.get('longitude'), -180, 180):
            raise ValueError('Locations need unique ids and valid coordinates.')
        if not isinstance(row.get('detail', ''), str):
            raise ValueError('Location detail must be text.')
        ZoneInfo(row['timezone'])
        ids.add(row['id'])
    return rows


def current_location(rows):
    config = read_json(config_dir() / 'weather.json', {})
    selected = config.get('islandLocation', '')
    return next((row['id'] for row in rows if row['id'] == selected), rows[0]['id'] if rows else '')


def timezone_command(*arguments):
    try:
        result = subprocess.run(['timedatectl', '--no-ask-password', *arguments], capture_output=True,
                                text=True, timeout=12, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise LocationError('Could not apply the system timezone without authentication. Check desktop timezone permissions.') from error


def system_timezone():
    zone = timezone_command('show', '--property=Timezone', '--value')
    if not zone:
        raise LocationError('Could not read the system timezone.')
    ZoneInfo(zone)
    return zone


def change_timezone(zone):
    timezone_command('set-timezone', zone)
    if system_timezone() != zone:
        raise LocationError('The system did not apply the selected timezone.')


def set_current(selected):
    rows = locations()
    location = next((row for row in rows if row['id'] == selected), None)
    if location is None:
        raise ValueError('Location is no longer configured.')
    path = config_dir() / 'weather.json'
    config = read_json(path)
    previous = system_timezone()
    changed = previous != location['timezone']
    if changed:
        try:
            change_timezone(location['timezone'])
        except LocationError:
            try:
                if system_timezone() != previous:
                    change_timezone(previous)
            except LocationError as rollback_error:
                raise LocationError('Could not confirm the selected timezone or restore the previous timezone.') from rollback_error
            raise
    config['islandLocation'] = selected
    try:
        atomic_json(path, config)
    except (OSError, ValueError) as error:
        if changed:
            try:
                change_timezone(previous)
            except LocationError as rollback_error:
                raise LocationError('System timezone changed, but saving the location and restoring the previous timezone failed.') from rollback_error
        raise LocationError('Could not save the current location. The previous system timezone is unchanged.') from error


def daily_outlook(rows):
    """One short model-based outlook, inspired by zephyrus-shell's daily summary."""
    daylight = [row for row in rows if row['day']]
    if len(rows) < 18 or not daylight:
        return ''
    def group(code):
        if code in (0, 1): return 'sun'
        if code == 2: return 'mixed'
        if code == 3: return 'cloud'
        if code in (45, 48): return 'fog'
        if code in (56, 57, 66, 67): return 'freezing'
        if code in (51, 53, 55): return 'drizzle'
        if code in (61, 63, 65, 80, 81, 82): return 'rain'
        if code in (71, 73, 75, 77, 85, 86): return 'snow'
        if code in (95, 96, 99): return 'storm'
        return 'unknown'
    counts = Counter(group(row['code']) for row in rows)
    day_counts = Counter(group(row['code']) for row in daylight)
    wet_groups = ('storm', 'freezing', 'snow', 'rain', 'drizzle')
    wet = sum(counts[key] for key in wet_groups)
    if wet >= len(rows) / 2 or sum(day_counts[key] for key in wet_groups) >= len(daylight) / 2:
        primary = max(wet_groups, key=lambda key: counts[key])
    else:
        primary = day_counts.most_common(1)[0][0]
        if primary in wet_groups or day_counts[primary] < len(daylight) * 0.6:
            primary = 'mixed' if day_counts['sun'] + day_counts['mixed'] else 'cloud'
    descriptions = dict(sun='Mostly sunny', mixed='A mix of sun and cloud', cloud='Mostly cloudy', fog='Mostly foggy',
                        drizzle='Drizzle for much of the day', rain='Rain for much of the day',
                        snow='Snow for much of the day', storm='Thunderstorms for much of the day',
                        freezing='Freezing rain for much of the day')
    if primary not in descriptions:
        return ''
    text = descriptions[primary]
    secondary = next((key for key in (*wet_groups, 'fog') if key != primary and counts[key]), None)
    if secondary:
        periods = {('overnight' if row['hour'] < 6 or row['hour'] >= 22 else 'in the morning' if row['hour'] < 12
                    else 'in the afternoon' if row['hour'] < 18 else 'in the evening')
                   for row in rows if group(row['code']) == secondary}
        name = dict(storm='thunderstorms', freezing='freezing rain', snow='snow', rain='rain', drizzle='drizzle', fog='fog')[secondary]
        text += ', with ' + name + ' ' + (next(iter(periods)) if len(periods) == 1 else 'at times')
    elif primary in wet_groups and day_counts['sun']:
        text += ', with sunny breaks'
    elif primary == 'sun' and day_counts['cloud']:
        text += ', with cloudy spells'
    return text + '.'


def cache_path(location):
    identity = [location[key] for key in ('latitude', 'longitude', 'timezone')]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'quickshell/desktop/weather' / (key + '.json')


def cached(location):
    try:
        data = read_json(cache_path(location))
        if isinstance(data, dict) and number(data.get('fetchedAt'), 0) and isinstance(data.get('data'), dict):
            # Validate cached payloads too; a broken cache must not break the clock.
            forecast(data['data'], location, time.time())
            return data
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        pass
    return None


def forecast(data, location, now):
    zone = ZoneInfo(location['timezone'])
    today = datetime.fromtimestamp(now, zone).date()
    current = data['current']
    if not isinstance(current, dict) or not number(current.get('temperature_2m')) or not number(current.get('weather_code')) or not number(current.get('time')):
        raise ValueError('Incomplete weather response.')
    def value(record, key):
        result = record.get(key)
        return result if number(result) else None
    def records(key, fields):
        table = data[key]
        times = table['time']
        if not isinstance(times, list) or not times:
            raise ValueError('Incomplete forecast response.')
        if any(not isinstance(table.get(field), list) or len(table[field]) != len(times) for field in fields):
            raise ValueError('Incomplete forecast response.')
        for index, stamp in enumerate(times):
            if not number(stamp):
                raise ValueError('Invalid forecast time.')
            yield datetime.fromtimestamp(stamp, zone), {field: value({field: table[field][index]}, field) for field in fields}
    hours = []
    daily_rows = {}
    for stamp, row in records('hourly', ['temperature_2m', 'precipitation_probability', 'weather_code', 'is_day']):
        if row['weather_code'] is not None and row['is_day'] in (0, 1):
            daily_rows.setdefault(stamp.date(), []).append(dict(hour=stamp.hour, code=row['weather_code'], day=row['is_day'] == 1))
        if stamp.timestamp() >= now and len(hours) < 6:
            hours.append(dict(time=stamp.timestamp(), label=stamp.strftime('%H:%M'), temperature=row['temperature_2m'],
                              rain=row['precipitation_probability'], code=row['weather_code'], isDay=row['is_day'] == 1))
    outlooks = {day: daily_outlook(rows) for day, rows in daily_rows.items()}
    days = []
    # Daily UNIX timestamps use the API's fixed offset for their calendar date.
    offset = data['utc_offset_seconds']
    if not number(offset, -86400, 86400):
        raise ValueError('Invalid forecast timezone.')
    for stamp, row in records('daily', ['temperature_2m_max', 'temperature_2m_min', 'precipitation_probability_max', 'weather_code']):
        day = datetime.fromtimestamp(stamp.timestamp() + offset, ZoneInfo('UTC')).date()
        if day < today:
            continue
        days.append(dict(date=day.isoformat(), today=day == today, high=row['temperature_2m_max'],
                         low=row['temperature_2m_min'], rain=row['precipitation_probability_max'], code=row['weather_code'],
                         outlook=outlooks.get(day, '')))
    return dict(current=dict(temperature=current['temperature_2m'], feelsLike=value(current, 'apparent_temperature'),
                             humidity=value(current, 'relative_humidity_2m'), wind=value(current, 'wind_speed_10m'),
                             code=current['weather_code'], isDay=current.get('is_day') == 1),
                hourly=hours, daily=days[:5], outlook=outlooks.get(today, ''))


def status(selected='', now=None, remember=True):
    now = time.time() if now is None else now
    result = dict(locations=[], location=None, currentLocation='', clock='', date='', zone='', weather=None, due=False, stale=False, updated='', error='')
    rows = locations()
    result['currentLocation'] = current_location(rows)
    result['locations'] = [dict(id=row['id'], name=row['name'], detail=row.get('detail', ''),
                                clock=datetime.fromtimestamp(now, ZoneInfo(row['timezone'])).strftime('%H:%M'),
                                zone=datetime.fromtimestamp(now, ZoneInfo(row['timezone'])).tzname()) for row in rows]
    if not rows:
        return result
    selection_path = config_dir() / 'weather-selection.json'
    if remember and not selected:
        try:
            saved = read_json(selection_path, {})
            selected = saved.get('id', '') if isinstance(saved, dict) else ''
        except (OSError, ValueError):
            selected = ''
    location = next((row for row in rows if row['id'] == selected), next(row for row in rows if row['id'] == result['currentLocation']))
    if remember and selected and location['id'] == selected:
        try:
            if read_json(selection_path, {}) != {'id': selected}:
                atomic_json(selection_path, dict(id=selected))
        except (OSError, ValueError):
            result['error'] = 'Could not save the selected location.'
    local = datetime.fromtimestamp(now, ZoneInfo(location['timezone']))
    result.update(location=dict(id=location['id'], name=location['name'], detail=location.get('detail', '')),
                  clock=local.strftime('%H:%M'), date=local.strftime('%Y-%m-%d'), zone=local.tzname())
    cache = cached(location)
    result['due'] = cache is None or not 0 <= now - cache['fetchedAt'] < TTL
    if cache:
        result['weather'] = forecast(cache['data'], location, now)
        result['stale'] = not 0 <= now - cache['fetchedAt'] < 3600
        updated = datetime.fromtimestamp(cache['fetchedAt'], ZoneInfo(location['timezone']))
        result['updated'] = updated.strftime('%H:%M') if updated.date() == local.date() else updated.strftime('%d %b %H:%M')
    return result


def island_status(now=None, refresh=False):
    # Background refreshes never follow or save the drawer selection.
    config = read_json(config_dir() / 'weather.json', {})
    selected = config.get('islandLocation', '') if isinstance(config, dict) else ''
    selected = selected if isinstance(selected, str) else ''
    result = status(selected, now, remember=False)
    if refresh and result['due'] and result['location']:
        try:
            fetch(result['location']['id'], force=False)
            result = status(selected, now, remember=False)
        except Exception:
            result['error'] = 'Weather refresh failed.'
    return result


def fetch(selected, force=True):
    location = next((row for row in locations() if row['id'] == selected), None)
    if location is None:
        raise ValueError('Location is no longer configured.')
    # The bar and the drawer share the per-place cache; skip a fetch the other
    # one already made.
    cache = cached(location)
    if not force and cache and 0 <= time.time() - cache['fetchedAt'] < TTL:
        return
    fetch_location(location)


def fetch_location(location):
    query = urlencode(dict(latitude=location['latitude'], longitude=location['longitude'], timezone=location['timezone'],
                           timeformat='unixtime', forecast_days=5, temperature_unit='celsius', wind_speed_unit='kmh',
                           current='temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code,is_day',
                           hourly='temperature_2m,precipitation_probability,weather_code,is_day',
                           daily='temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code'))
    request = Request('https://api.open-meteo.com/v1/forecast?' + query, headers={'User-Agent': 'Quickshell-Desktop-Weather/1.0'})
    with urlopen(request, timeout=18) as response:
        data = json.load(response)
    now = time.time()
    forecast(data, location, now)
    atomic_json(cache_path(location), dict(fetchedAt=now, data=data))


def main():
    try:
        request = json.loads(sys.stdin.readline())
        selected = request.get('id', '')
        if not isinstance(selected, str):
            raise ValueError('Invalid location.')
        if request.get('op') == 'island':
            result = island_status(refresh=request.get('refresh') is True)
        elif request.get('op') == 'fetch':
            fetch(selected, force=request.get('force') is True)
            result = status(selected)
        elif request.get('op') == 'status':
            result = status(selected)
        elif request.get('op') == 'current':
            set_current(selected)
            result = status(selected)
        else:
            raise ValueError('Unknown weather request.')
    except LocationError as error:
        result = dict(error=str(error))
    except Exception as error:
        # Do not expose coordinates or request URLs in UI errors or shell logs.
        result = dict(error=('Check weather.json: ' + str(error)) if isinstance(error, (ValueError, KeyError))
                      else 'Weather unavailable. Try again shortly.')
    print(json.dumps(result, ensure_ascii=False, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
