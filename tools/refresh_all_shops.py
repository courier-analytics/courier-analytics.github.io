"""Collect all three DS using the same catalogue rules as the source website."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_sources import audit
from build_dashboard_feed import build
from calculate_metrics import calculate, metric
from active_base import collect as collect_active_base, BASIS as ACTIVE_BASIS
from overnight_completion import resolve as resolve_overnight
from enrich_slots import atomic_json
from refresh_dashboard import merge_feed, private_xlsx, HEADERS


def refresh(day, token, proxy, private_dir, feed_path, active_base=False):
    folder = private_dir/'all-shops'
    audit_summary = audit(day, token, proxy, folder, extra_details=False)
    observations = json.loads((folder/'all-shops-observations.json').read_text())
    plan_path = private_dir/'plans'/('plan-'+day+'.json')
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else None
    rosters, roster_errors = {}, {}
    if Path('/etc/courier-analytics/roster-enabled.json').exists():
        from roster_client import get_rosters, RosterError
        try:
            rosters, roster_errors = get_rosters(token, proxy, private_dir/'one-c-session.json')
        except RosterError as error:
            roster_errors = {s['shop_id']: str(error) for s in observations['shops']}
    summaries = []
    for shop in observations['shops']:
        identity = shop['shop_id']
        shop['slots'], shop['overnight_completion'] = resolve_overnight(shop['slots'], token, proxy)
        source_plan = next((p for p in (plan or {}).get('shops', []) if p['shop_id'] == identity), None)
        daily_plan = {'verified': True, 'date': day, 'slots': source_plan['slots']} if (
            source_plan and plan.get('verified') is True and plan.get('date') == day) else None
        metrics = calculate(shop['slots'], day, roster=rosters.get(identity), plan=daily_plan)
        if active_base:
            try:
                metrics['shift_marked'] = collect_active_base(day, identity, shop['slots'], token, proxy)
            except (RuntimeError, ValueError, KeyError, TypeError):
                metrics['shift_marked'] = metric(reason='active_base_incomplete', basis=ACTIVE_BASIS)
        fill = metrics['slot_fill']
        summaries.append({'date': day, 'shop_id': identity, 'slot_type': 'limited',
                          'booked_places': fill['numerator'], 'capacity': fill['denominator'],
                          'fill_percent': fill['value'], 'metrics': metrics})
    if not summaries:
        raise ValueError('None of the requested DS is available; previous feed preserved')
    atomic_json(folder/'all-shops-observations.json', observations)
    report = {'schema_version': 1, 'snapshot_consistent': True, 'issues': [],
              'generated_at': datetime.now(timezone.utc).isoformat(), 'summaries': summaries}
    fresh = build([report])
    previous = json.loads(feed_path.read_text()) if feed_path.exists() else None
    combined = merge_feed(previous, fresh)
    atomic_json(private_dir/('metrics-'+day+'.json'), report)
    export_rows = []
    for shop in observations['shops']:
        for slot in shop['slots']:
            people = slot['couriers']
            one = people[0] if len(people) == 1 else {}
            capacity = slot['capacity'] if slot['slot_type'] == 'limited' else max(slot['capacity'] or 0, 1)
            export_rows.append([day, str(shop['shop_id']),
                str(slot['scope_id']) if slot['scope_kind'] == 'cluster_id' else '',
                slot['slot_id'], 'Лимитированный' if slot['slot_type'] == 'limited' else 'Ручной',
                slot['time_from'], slot['time_to'], f'{len(people)} из {capacity}',
                ', '.join(c['courier_id'] for c in people), one.get('shift_status') or '',
                one.get('shift_start') or '', one.get('shift_end') or ''])
    private_xlsx(private_dir/('all-shops-'+day+'.xlsx'), export_rows)
    atomic_json(feed_path, combined)
    feed_path.chmod(0o644)
    return {'scope_summary': audit_summary, 'roster_errors': roster_errors,
            'overnight_completion': {s['shop_id']: s['overnight_completion'] for s in observations['shops']},
            'report': report}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--session', type=Path, default=Path('/root/curator-session.json'))
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    parser.add_argument('--private-dir', type=Path, default=Path('/opt/courier-analytics/private'))
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat())
    parser.add_argument('--active-base', action='store_true')
    args = parser.parse_args()
    try:
        from datetime import date
        date.fromisoformat(args.date)
        token = json.loads(args.session.read_text())['token']
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise ValueError('Invalid session')
        args.private_dir.mkdir(parents=True, exist_ok=True)
        args.private_dir.chmod(0o700)
        enabled = args.active_base or Path('/etc/courier-analytics/active-base-enabled.json').exists()
        print(json.dumps(refresh(args.date, token, args.proxy, args.private_dir, args.feed, active_base=enabled), ensure_ascii=False, indent=2))
    except RuntimeError as error:
        raise SystemExit(str(error))
    except (ValueError, KeyError, OSError, TypeError) as error:
        import traceback
        frame = traceback.extract_tb(error.__traceback__)[-1]
        raise SystemExit('All-DS refresh failed validation; existing public feed preserved. '
                         f'{type(error).__name__} at {frame.name}:{frame.lineno}')
