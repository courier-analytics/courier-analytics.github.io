"""Join an XLSX snapshot to read-only API details and emit anonymous aggregates."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from import_slots import read_export, summarize

BASE = 'https://couriers-schedules.vkusvill.ru'


def source_status(value):
    """Match the display-status prefixes used by the site's jM function."""
    text = (value or '').strip().lower()
    for prefix, state in [('ожидается', 'expected'), ('не вышел', 'no_show'),
                          ('опоздал', 'late'), ('вышел раньше', 'early'),
                          ('вышел', 'on_time')]:
        if text.startswith(prefix):
            return state
    return 'unknown'


def booking_before_day(value, day):
    """Current booking observation, not proof of a complete historical plan."""
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            return None  # Do not guess the timezone of facts returned by the API.
        cutoff = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo('Europe/Moscow'))
        return timestamp < cutoff
    except (ValueError, TypeError):
        return None


def optional(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def slot_key(slot):
    return slot['date'], slot['slot_type'], slot['slot_id']


def enrich(slots, responses):
    """responses: (date, scope kind, scope ID, slot type, raw API payload)."""
    wanted = {slot_key(s): s for s in slots}
    if len(wanted) != len(slots):
        raise ValueError('Duplicate exported slot')
    index = {}
    issues = []
    for day, scope_kind, scope_id, kind, payload in responses:
        raw = payload if isinstance(payload, list) else payload.get('slots', payload.get('items'))
        if not isinstance(raw, list):
            raise ValueError('Unknown API slots format')
        for item in raw:
            identity = item.get('slot_id', item.get('limited_slot_id', item.get('id')))
            if identity is None:
                continue
            actual_kind = 'manual' if 'manual' in str(item.get('type', item.get(
                'slot_type', item.get('slotType', kind)))).lower() else 'limited'
            key = (str(item.get('date') or day)[:10], actual_kind, int(identity))
            if key not in wanted:
                continue  # New slots do not belong to the XLSX snapshot.
            target = wanted[key]
            expected_scope = ('cluster_id', target['cluster_id']) if target['cluster_id'] is not None else ('shopno', target['shop_id'])
            if (scope_kind, scope_id) != expected_scope:
                continue
            actual_scope = item.get('shopno_cluster_id', item.get('shopno', item.get('shop_id')))
            if actual_scope is not None and int(actual_scope) != scope_id:
                raise ValueError('API returned a slot belonging to another scope')
            if key in index:
                raise ValueError('Duplicate API slot')
            index[key] = item

    enriched = deepcopy(slots)
    for slot in enriched:
        key = slot_key(slot)
        raw = index.get(key)
        def issue(code):
            issues.append({'date': slot['date'], 'slot_type': slot['slot_type'],
                           'slot_id': slot['slot_id'], 'code': code})
        if raw is None:
            issue('slot_missing_from_api')
            continue
        people = raw.get('couriers')
        if not isinstance(people, list):
            issue('courier_details_missing')
            continue
        people = [p for p in people if p.get('status') != 'cancelled']
        people_by_id = {}
        for person in people:
            identity = optional(person, 'id')
            if identity is None or identity in people_by_id:
                raise ValueError('Invalid or duplicate API courier ID')
            people_by_id[identity] = person
        if set(people_by_id) != {c['courier_id'] for c in slot['couriers']}:
            issue('booking_membership_changed')
            continue  # Never join people from different snapshots.
        capacity = raw.get('capacity', raw.get('courier_limits'))
        if capacity is not None and float(capacity) != slot['capacity']:
            issue('capacity_changed')
            continue
        if any(str(raw.get(field, slot[field]))[:5] != slot[field][:5]
               for field in ('time_from', 'time_to')):
            issue('slot_times_changed')
            continue
        for courier in slot['couriers']:
            person = people_by_id[courier['courier_id']]
            # Empty facts remain unknown; do not infer no-show or completion.
            courier.update({
                'shift_status': optional(person, 'shift_status', 'shiftStatus'),
                'shift_start': optional(person, 'shift_start', 'shiftStart'),
                'shift_end': optional(person, 'shift_end', 'shiftEnd'),
                'booked_at': optional(person, 'booking_date', 'bookingDate', 'booked_at'),
                'details_source': 'api',
            })
    return enriched, issues


def scopes(slots):
    return sorted({(s['date'], 'cluster_id' if s['cluster_id'] is not None else 'shopno',
                    s['cluster_id'] if s['cluster_id'] is not None else s['shop_id'],
                    s['slot_type']) for s in slots})


def fetch(scope, token, proxy):
    day, kind, identity, slot_type = scope
    url = BASE + '/v1/schedules/slots?' + urlencode({
        'date': day, kind: identity, 'slot_type': slot_type})
    command = ['curl', '--silent', '--show-error', '--connect-timeout', '10',
               '--max-time', '45', '--max-filesize', '20000000',
               '--header', '@-', '--write-out', '\n%{http_code}']
    if proxy:
        parsed = urlsplit(proxy)
        if parsed.scheme not in ('socks5h', 'http', 'https') or parsed.username or parsed.password:
            raise ValueError('Use a proxy URL without embedded credentials')
        command += ['--proxy', proxy, '--noproxy', '']
    response = subprocess.run(command + [url],
        input='Authorization: Bearer ' + token + '\nAccept: application/json\n',
        capture_output=True, text=True, timeout=55)
    if response.returncode:
        raise RuntimeError(f'API connection failed (curl {response.returncode})')
    body, _, status = response.stdout.rpartition('\n')
    if status != '200':
        raise RuntimeError(f'API HTTP {status}; response hidden')
    return json.loads(body)


def report(slots, issues):
    aggregates = summarize(slots)
    for group in aggregates:
        rows = [s for s in slots if (s['date'], s['shop_id'], s['slot_type']) ==
                (group['date'], group['shop_id'], group['slot_type'])]
        group['records_enriched'] = sum(c['details_source'] == 'api'
                                        for s in rows for c in s['couriers'])
        group['records_missing_shift_status'] = sum(c['shift_status'] is None
                                                    for s in rows for c in s['couriers'])
        group['records_missing_booking_time'] = sum(not c.get('booked_at')
                                                   for s in rows for c in s['couriers'])
        group['source_status_counts'] = dict(Counter(
            source_status(c['shift_status']) for s in rows for c in s['couriers']))
        booking_counts = Counter(
            'before_day' if flag is True else 'during_or_after_day' if flag is False else 'unknown'
            for s in rows for c in s['couriers']
            for flag in [booking_before_day(c.get('booked_at'), s['date'])])
        group['observed_booking_time_counts'] = dict(booking_counts)
        group['historical_plan_verified'] = False
    return {'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'source': 'xlsx_with_api_details', 'snapshot_consistent': not issues,
            'issues': issues, 'summaries': aggregates,
            'attendance_metrics_ready': False,
            'note': 'Plan snapshot and attendance rules must be validated before publication.'}


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.slots-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('xlsx', type=Path)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    slots = read_export(args.xlsx)
    if not slots:
        raise ValueError('Empty export; previous output preserved')
    token = json.loads(args.session.read_text()).get('token')
    if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
        raise ValueError('Invalid session token')
    responses = [(*scope, fetch(scope, token, args.proxy)) for scope in scopes(slots)]
    enriched, issues = enrich(slots, responses)
    if issues:
        print(json.dumps({'snapshot_consistent': False, 'issues': issues}, indent=2))
        return 2  # Do not overwrite a previous valid report.
    result = report(enriched, issues)
    atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        # These messages are constructed here: never echo API bodies or tokens.
        raise SystemExit(f'Import failed; output preserved. {error}')
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        import traceback
        frame = traceback.extract_tb(error.__traceback__)[-1]
        raise SystemExit('Import failed; output preserved. '
                         f'{type(error).__name__} at {Path(frame.filename).name}:{frame.lineno}')
