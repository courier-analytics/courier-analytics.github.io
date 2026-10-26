"""Fill missing API-backed dates while preserving existing manual history."""
import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo

from enrich_slots import atomic_json
from refresh_all_shops import refresh
from refresh_dashboard import merge_feed

PAGES = {5818: 'index.html', 7745: '7745.html', 4747: '4747.html'}
INDEXES = {'shift_marked': 1, 'slot_fill': 2, 'planned_attendance': 3,
           'planned_late': 4, 'unplanned_work': 5, 'planned_completion': 6}
BASE = 'direct_shop_scheduled_unique_5d_including_day'


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
        if any(row['metrics'][m]['reason'] not in (
            (None, 'zero_denominator', 'shift_end_or_final_status_missing', 'unknown_shift_status')
            if m == 'planned_completion' else (None, 'zero_denominator')) for m in work[key]):
            raise ValueError('Incomplete required historical source; candidate not published')
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
        raise ValueError('A required DS is unavailable; candidate not published')
    return {'schema_version': 1, 'records': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True, help='Private candidate feed, not the active site')
    parser.add_argument('--until', default=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat())
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    args = parser.parse_args()
    try:
        date.fromisoformat(args.until)
        if args.until > datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat():
            raise ValueError('Future dates cannot be backfilled')
        root = Path(__file__).resolve().parents[1]
        manual = manual_history(root)
        public = json.loads(args.feed.read_text())
        work = needed(public, manual, args.until)
        print('Missing DS/dates: '+str(len(work)), flush=True)
        token = json.loads(Path('/root/curator-session.json').read_text())['token']
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise ValueError('Invalid session')
        private = Path('/opt/courier-analytics/private/backfill')
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(prefix='.daily-', dir=private) as temporary:
            for day in sorted({d for _, d in work}):
                print('Collecting '+day+'...', flush=True)
                daily = Path(temporary)/'feed.json'
                atomic_json(daily, {'schema_version': 1, 'records': []})
                result = refresh(day, token, args.proxy, private/day, daily, active_base=True)
                print('Overnight end check: '+json.dumps(result.get('overnight_completion', {})), flush=True)
                selected = select_rows(json.loads(daily.read_text()), public, manual, work, day)
                public = merge_feed(public, selected)
                atomic_json(args.feed, public)
                for row in selected['records']:
                    m = row['metrics'].get('shift_marked')
                    arrival = row['metrics'].get('planned_attendance', {}).get('value', 'manual history')
                    late = row['metrics'].get('planned_late', {}).get('value', 'manual history')
                    completion = row['metrics'].get('planned_completion', {})
                    print(f"{day} DS {row['shop_id']}: fill={row['fill_percent']}; active booking share={m['value'] if m else 'manual history'}; arrived={arrival}; late={late}; completed={completion.get('value', 'manual history')} ({completion.get('reason') or 'ready'})", flush=True)
        print('Candidate complete. Manual history preserved. Missing frozen plans remain unavailable.', flush=True)
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        raise SystemExit('Backfill incomplete; active site unchanged. Private responses hidden.')
