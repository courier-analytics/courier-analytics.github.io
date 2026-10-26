"""Check the site's 1C assigned-courier register using the existing own session."""
import argparse
import json
import os
from pathlib import Path

from enrich_slots import atomic_json
from roster_client import RosterError, get_rosters


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    parser.add_argument('--enable', action='store_true')
    args = parser.parse_args()
    private = Path('/opt/courier-analytics/private')
    try:
        primary = json.loads(Path('/root/curator-session.json').read_text())['token']
        if not isinstance(primary, str) or not primary or '\r' in primary or '\n' in primary:
            raise RosterError('invalid_primary_session')
        rosters, errors = get_rosters(primary, args.proxy, private/'one-c-session.json')
        observations = json.loads((private/'all-shops/all-shops-observations.json').read_text())
        summaries = []
        for shop in (5818, 7745, 4747):
            roster = rosters.get(shop)
            if roster is None:
                summaries.append({'shop_id': shop, 'roster_verified': False, 'reason': errors.get(shop)})
                continue
            assigned = set(roster['courier_ids'])
            slots = next((s['slots'] for s in observations['shops'] if s['shop_id'] == shop), None)
            booked = {c['courier_id'] for s in slots for c in s['couriers']} if slots is not None else None
            summaries.append({'shop_id': shop, 'roster_verified': True, 'assigned_unique': len(assigned),
                'assigned_with_slot': len(assigned & booked) if booked is not None else None,
                'assigned_without_slot': len(assigned-booked) if booked is not None else None,
                'booked_not_assigned_here': len(booked-assigned) if booked is not None else None,
                'source_rows': roster['raw_rows'], 'duplicate_rows': roster['duplicate_rows']})
        atomic_json(private/'assigned-rosters.json', {'shops': {str(k): v for k, v in rosters.items()}})
        print(json.dumps({'rosters': summaries}, ensure_ascii=False, indent=2))
        if args.enable:
            if not rosters:
                raise RosterError('no_verified_rosters_to_enable')
            folder = Path('/etc/courier-analytics')
            folder.mkdir(parents=True, exist_ok=True)
            atomic_json(folder/'roster-enabled.json', {'enabled': True})
            print('Assigned-roster lookup enabled for future refreshes. Secrets not printed.')
    except RosterError as error:
        raise SystemExit('Roster lookup unavailable: '+str(error))
    except (ValueError, KeyError, OSError, TypeError):
        raise SystemExit('Roster check failed validation; no private response printed.')
