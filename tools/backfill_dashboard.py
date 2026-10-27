"""Fill missing API-backed dates while preserving existing manual history."""
import argparse
from proxy_config import configured_proxy
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import tempfile
import traceback
from zoneinfo import ZoneInfo

from enrich_slots import atomic_json
from refresh_all_shops import refresh
from refresh_dashboard import merge_feed
from completion_reporting import BASIS as COMPLETION_BASIS
from dashboard_shops import SHOPS, TOOL_START
from verify_server_proxy import error_code

PAGES = {shop: config['page'] for shop, config in SHOPS.items()}
INDEXES = {'shift_marked': 1, 'slot_fill': 2, 'planned_attendance': 3,
           'planned_late': 4, 'unplanned_work': 5, 'planned_completion': 6}
BASE = 'direct_shop_scheduled_unique_5d_including_day'
REFRESHABLE = {'shift_marked', 'slot_fill', 'planned_attendance', 'planned_late', 'planned_completion'}


class BackfillCheckError(ValueError):
    def __init__(self, details):
        self.details = details
        super().__init__('Historical candidate validation failed')


def safe_failure(error, stage, day=None):
    frame = traceback.extract_tb(error.__traceback__)[-1] if error.__traceback__ else None
    known = {
        'API returned a different scope': 'source_scope_mismatch',
        'API returned a different day': 'source_date_mismatch',
        'Repeated slot across scopes': 'duplicate_slot_across_scopes',
        'Occupied count differs from limited-slot courier list': 'occupied_count_differs_from_courier_details',
        'Invalid limited-slot capacity': 'invalid_limited_capacity',
        'Unknown slot list format': 'unknown_slot_list_format',
        'Unrecognized slot type': 'unknown_slot_type',
        'Duplicate courier in one slot': 'duplicate_courier_in_slot',
        'Invalid courier identity': 'invalid_courier_identity',
        'Slot courier details absent': 'courier_details_absent',
    }
    info = {'stage': stage, 'date': day, 'type': type(error).__name__,
            'code': known.get(str(error), error_code(error))}
    if frame:
        info.update(function=frame.name, line=frame.lineno)
    if isinstance(error, BackfillCheckError):
        info['checks'] = error.details
    return info


def work_for_date(manual, day):
    date.fromisoformat(day)
    work = {}
    for shop in PAGES:
        days = [d for s, d in manual if s == shop]
        if days and day >= min(days):
            keys = REFRESHABLE-manual.get((shop, day), set())
            if keys:
                work[shop, day] = keys
    return work


def manual_history(root):
    result = {}
    for shop, page in PAGES.items():
        text = (root/page).read_text()
        dates = json.loads(re.search(r'const dates\s*=\s*(\[[^;]+\]);', text).group(1))
        arrays = [json.loads(v) for v in re.findall(r'values:(\[[^\]]*\])', text)]
        if len(arrays) != 10 or any(len(v) != len(dates) for v in arrays):
            raise ValueError('Unknown manual history format')
        for i, day in enumerate(dates):
            iso = '2026-'+day[3:5]+'-'+day[:2]
            result[shop, iso] = {key for key, index in INDEXES.items() if arrays[index][i] is not None}
    return result


def needed(previous, manual, until):
    indexed = {(r['shop_id'], r['date']): r for r in previous['records']}
    output = {}
    for shop in PAGES:
        if not any(s == shop for s, _ in manual):
            continue
        first = min(d for s, d in manual if s == shop)
        current = date.fromisoformat(first)
        while current <= date.fromisoformat(until):
            day = current.isoformat()
            row = indexed.get((shop, day), {})
            known = manual.get((shop, day), set())
            wanted = set()
            for key in ('shift_marked', 'slot_fill', 'planned_attendance', 'planned_late', 'planned_completion'):
                if key in known:
                    continue
                metric = row.get('metrics', {}).get(key)
                complete = metric and (
                    metric.get('value') is not None or metric.get('reason') == 'zero_denominator')
                if key == 'shift_marked' and metric and metric.get('basis') != BASE:
                    complete = False
                if key == 'planned_completion' and metric and metric.get('basis') != COMPLETION_BASIS:
                    complete = False
                if key == 'slot_fill' and row and 'metrics' not in row:
                    complete = True  # An earlier validated slot-fill import.
                if not complete:
                    wanted.add(key)
            if wanted:
                output[shop, day] = wanted
            current += timedelta(days=1)
    return output


def select_rows(fresh, previous, manual, work, day):
    old = {(r['shop_id'], r['date']): r for r in previous['records']}
    rows = []
    for row in fresh['records']:
        key = row['shop_id'], row['date']
        if row['date'] != day or key not in work:
            continue
        failures = [{'shop_id': key[0], 'metric': m, 'reason': row['metrics'][m]['reason']}
                    for m in sorted(work[key]) if row['metrics'][m]['reason'] not in (
            (None, 'zero_denominator', 'shift_end_or_final_status_missing', 'unknown_shift_status')
            if m == 'planned_completion' else
            (None, 'zero_denominator', 'assigned_roster_not_verified')
            if m == 'shift_marked' and day < TOOL_START.get(key[0], day) else
            (None, 'zero_denominator'))]
        if failures:
            raise BackfillCheckError(failures)
        # Existing manually entered facts win over retrospective automatic facts.
        row = dict(row)
        incoming = {k: v for k, v in row['metrics'].items() if k not in manual.get(key, set())}
        old_row = old.get(key, {})
        retained = {k: v for k, v in old_row.get('metrics', {}).items()
                    if k not in work[key]}
        row['metrics'] = {**incoming, **retained}
        if old_row and 'slot_fill' not in work[key]:
            for field in ('booked_places', 'capacity', 'fill_percent'):
                row[field] = old_row[field]
            if 'slot_fill' not in retained:
                row['metrics'].pop('slot_fill', None)
        rows.append(row)
    expected = {s for s, d in work if d == day}
    if {r['shop_id'] for r in rows} != expected:
        raise BackfillCheckError([{'unavailable_shop_id': shop} for shop in sorted(expected-{r['shop_id'] for r in rows})])
    return {'schema_version': 1, 'records': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True, help='Private candidate feed, not the active site')
    parser.add_argument('--until', default=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat())
    parser.add_argument('--date', help='Recalculate available automatic metrics for exactly one date, including existing values')
    parser.add_argument('--proxy', default=configured_proxy())
    args = parser.parse_args()
    stage, collecting_day = 'load_configuration', None
    try:
        selected_day = args.date or args.until
        date.fromisoformat(selected_day)
        if selected_day > datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat():
            raise ValueError('Future dates cannot be backfilled')
        root = Path(__file__).resolve().parents[1]
        manual = manual_history(root)
        public = json.loads(args.feed.read_text())
        work = work_for_date(manual, args.date) if args.date else needed(public, manual, args.until)
        print('Missing DS/dates: '+str(len(work)), flush=True)
        token = json.loads(Path('/root/curator-session.json').read_text())['token']
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise ValueError('Invalid session')
        private = Path('/opt/courier-analytics/private/backfill')
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix='.daily-', dir=private) as temporary:
            for day in sorted({d for _, d in work}):
                stage, collecting_day = 'collect_source_data', day
                print('Collecting '+day+'...', flush=True)
                daily = Path(temporary)/'feed.json'
                atomic_json(daily, {'schema_version': 1, 'records': []})
                result = refresh(day, token, args.proxy, private/day, daily, active_base=True,
                                 completion_state_dir=private.parent)
                print('Overnight end check: '+json.dumps(result.get('overnight_completion', {})), flush=True)
                print('Completion reporting dates: '+json.dumps(result.get('completion_reporting', {})), flush=True)
                stage = 'validate_candidate'
                selected = select_rows(json.loads(daily.read_text()), public, manual, work, day)
                stage = 'merge_candidate'
                public = merge_feed(public, selected)
                atomic_json(args.feed, public)
                for row in selected['records']:
                    m = row['metrics'].get('shift_marked')
                    arrival = row['metrics'].get('planned_attendance', {}).get('value', 'manual history')
                    late = row['metrics'].get('planned_late', {}).get('value', 'manual history')
                    completion = row['metrics'].get('planned_completion', {})
                    print(f"{day} DS {row['shop_id']}: fill={row['fill_percent']}; active booking share={m['value'] if m else 'manual history'}; arrived={arrival}; late={late}; completed={completion.get('value', 'manual history')} ({completion.get('reason') or 'ready'})", flush=True)
        print('Candidate complete. Manual history preserved. Missing frozen plans remain unavailable.', flush=True)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print('Backfill diagnostic: '+json.dumps(safe_failure(error, stage, collecting_day), ensure_ascii=False), flush=True)
        raise SystemExit('Backfill incomplete; active site unchanged. Private responses hidden.')
