"""Audit saved plan metadata; optionally recalculate yesterday's unplanned share."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from capture_plan import in_capture_window
from calculate_metrics import calculate
from audit_sources import audit
from enrich_slots import atomic_json
from proxy_config import configured_proxy

PRIVATE = Path('/opt/courier-analytics/private')


def load_plan(path, day):
    if not path.is_file():
        return None
    plan = json.loads(path.read_text())
    started, completed = (datetime.fromisoformat(plan[k]) for k in ('started_at', 'completed_at'))
    if (plan.get('verified') is not True or plan.get('date') != day or
        started.tzinfo is None or completed.tzinfo is None or completed < started or
        not in_capture_window(started, day) or not in_capture_window(completed, day)):
        raise ValueError('Invalid frozen plan metadata')
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair-yesterday', action='store_true')
    args = parser.parse_args()
    today = datetime.now(ZoneInfo('Europe/Moscow')).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    plan = None
    for day in (yesterday, today.isoformat(), (today + timedelta(days=1)).isoformat()):
        saved = load_plan(PRIVATE/'plans'/('plan-'+day+'.json'), day)
        print(json.dumps({'date': day, 'frozen_plan_exists': saved is not None,
            'shops': [s['shop_id'] for s in saved['shops']] if saved else []}), flush=True)
        if day == yesterday:
            plan = saved
    if not args.repair_yesterday:
        return
    if not plan:
        print('Yesterday: no verified 23:59 snapshot. No percentage invented; future capture enabled separately.')
        return
    feed_path = Path('/opt/courier-analytics/current-site/data/dashboard.json')
    public = json.loads(feed_path.read_text())
    token = json.loads(Path('/root/curator-session.json').read_text())['token']
    with tempfile.TemporaryDirectory(prefix='.plan-check-', dir=PRIVATE) as directory:
        folder = Path(directory)
        audit(yesterday, token, configured_proxy(), folder, extra_details=False)
        observations = json.loads((folder/'all-shops-observations.json').read_text())
        updated = []
        for shop in observations['shops']:
            identity = shop['shop_id']
            source_plan = next((s for s in plan['shops'] if s['shop_id'] == identity), None)
            if source_plan is None:
                continue
            row = next((r for r in public['records'] if r['date'] == yesterday and r['shop_id'] == identity), None)
            if row is None:
                continue
            metric = calculate(shop['slots'], yesterday, plan={
                'verified': True, 'date': yesterday, 'slots': source_plan['slots']})['unplanned_work']
            row.setdefault('metrics', {})['unplanned_work'] = metric
            row['reported_at'] = datetime.now(timezone.utc).isoformat()
            updated.append({'shop_id': identity, **metric})
        if not updated:
            raise ValueError('No matching saved plan and public DS/date')
        candidate = PRIVATE/'unplanned-repaired-feed.json'
        atomic_json(candidate, public)
        print('Yesterday comparison: '+json.dumps(updated, ensure_ascii=False), flush=True)
        # The caller holds refresh.lock and serializes publication separately.
        import subprocess
        result = subprocess.run(['flock', '-w', '120', '/opt/courier-analytics/publish.lock',
            '/opt/courier-analytics/import-venv/bin/python', str(Path(__file__).with_name('publish_dashboard.py')),
            '--feed', str(candidate)], check=True)
        atomic_json(feed_path, public)
        feed_path.chmod(0o644)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError):
        raise SystemExit('Plan check failed validation; private details hidden.')
