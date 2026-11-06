"""Collect configured DS using the same catalogue rules as the source website."""
import argparse
import json
import os
from proxy_config import configured_proxy
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_sources import audit
from build_dashboard_feed import build
from calculate_metrics import calculate, metric
from active_base import collect as collect_active_base, BASIS as ACTIVE_BASIS
from overnight_completion import resolve as resolve_overnight
from completion_reporting import collect as collect_completion, BASIS as COMPLETION_BASIS
from enrich_slots import atomic_json
from refresh_dashboard import merge_feed, private_xlsx, HEADERS


def refresh(day, token, proxy, private_dir, feed_path, active_base=False, completion_state_dir=None):
    folder = private_dir/'all-shops'
    audit_summary = audit(day, token, proxy, folder, extra_details=False)
    observations = json.loads((folder/'all-shops-observations.json').read_text())
    plan_path = (completion_state_dir or private_dir)/'plans'/('plan-'+day+'.json')
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else None
    rosters, roster_errors = {}, {}
    if Path('/etc/courier-analytics/roster-enabled.json').exists():
        from roster_client import get_rosters, RosterError
        try:
            rosters, roster_errors = get_rosters(token, proxy, private_dir/'one-c-session.json')
        except RosterError as error:
            roster_errors = {s['shop_id']: str(error) for s in observations['shops']}
    summaries = []
    private_details = []
    stitch_cache={}
    for shop in observations['shops']:
        identity = shop['shop_id']
        state_dir=completion_state_dir or private_dir
        native_path = state_dir/'onec-rosters'/'7745.json'
        use_native = identity == 7745 and (native_path.exists() or (native_path.parent/'by-date'/(day+'-7745.json')).exists())
        if use_native:
            from onec_roster_cache import load_for_day as load_native_roster
            rosters.pop(identity, None)
            try:
                rosters[identity] = load_native_roster(native_path.parent, day)
            except (OSError, ValueError, KeyError, TypeError):
                roster_errors[identity] = 'native_roster_stale_or_invalid'
        scope_config=next((s for s in observations.get('scope_config',{}).get('shops',[]) if s['shop_id']==identity),None)
        scopes=([('shopno',identity)]+[('cluster_id',int(c)) for c in scope_config['cluster_ids']]) if scope_config else None
        shop['slots'], shop['overnight_completion'] = resolve_overnight(shop['slots'], token, proxy, source_cache=stitch_cache,scopes=scopes)
        source_plan = next((p for p in (plan or {}).get('shops', []) if p['shop_id'] == identity), None)
        daily_plan = {'verified': True, 'date': day, 'captured_at':plan.get('completed_at'), 'slots': source_plan['slots']} if (
            source_plan and plan.get('verified') is True and plan.get('date') == day) else None
        from metric_exclusions import load as load_exclusions,views,filter_slots
        excluded=load_exclusions(state_dir,day,identity)
        if excluded:
            shop['source_slots_before_exclusions']=shop['slots']
            shop['slots'],daily_plan,adjusted_roster=views(shop['slots'],daily_plan,rosters.get(identity),excluded)
            if adjusted_roster:rosters[identity]=adjusted_roster
            shop['excluded_courier_ids']=sorted(excluded)
        from plan_cancellations import collect as collect_cancellations
        if daily_plan:
            daily_plan['cancellations']=collect_cancellations(day,identity,daily_plan,shop['slots'],token,proxy)
            shop['plan_cancellations']=daily_plan['cancellations']
        metrics = calculate(shop['slots'], day, roster=rosters.get(identity), plan=daily_plan)
        try:
            scope_config = next(s for s in observations['scope_config']['shops'] if s['shop_id'] == identity)
            metrics['planned_completion'], shop['completion_reporting'] = collect_completion(
                day, identity, scope_config, shop['slots'], token, proxy,
                completion_state_dir or private_dir,source_cache=stitch_cache)
            if excluded:
                state_path=(completion_state_dir or private_dir)/'completion-night-state'/f'{identity}.json'
                state=json.loads(state_path.read_text())
                from completion_reporting import choose
                from calculate_metrics import current_slot_completion
                history=[s for origin,saved in state.get('days',{}).items() if origin<day for s in saved['slots']]
                selected=filter_slots(choose(history+[s for s in shop['slots'] if s['slot_type']=='limited'],day),excluded)
                metrics['planned_completion']=current_slot_completion(selected)
                metrics['planned_completion']['basis']=COMPLETION_BASIS
        except (RuntimeError, ValueError, KeyError, TypeError, OSError, StopIteration):
            metrics['planned_completion'] = metric(reason='completion_history_incomplete', basis=COMPLETION_BASIS)
            shop['completion_reporting'] = {'source_complete': False}
        if active_base and not use_native:
            try:
                metrics['shift_marked'] = collect_active_base(day, identity, shop['slots'], token, proxy)
            except (RuntimeError, ValueError, KeyError, TypeError):
                metrics['shift_marked'] = metric(reason='active_base_incomplete', basis=ACTIVE_BASIS)
        from training import configured as collect_training
        training=collect_training(day,rosters.get(identity),state_dir) if identity==7745 else None
        if training:metrics['training']=training['metric']
        fill = metrics['slot_fill']
        from courier_details import build as build_details
        from completion_reporting import choose as choose_completion
        try:
            completion_slots=None
            history=[]
            state_path=(completion_state_dir or private_dir)/'completion-night-state'/f'{identity}.json'
            if state_path.exists():
                state=json.loads(state_path.read_text())
                history=[s for origin,saved in state.get('days',{}).items() if origin<day for s in saved['slots']]
            completion_slots=choose_completion(history+[s for s in shop['slots'] if s['slot_type']=='limited'],day)
            completion_slots=filter_slots(completion_slots,excluded)
            detail=build_details(day,shop,metrics,rosters.get(identity),daily_plan,completion_slots)
            if training:detail['metrics']['training']=training['detail']
            if excluded:
                for item in detail['metrics'].values():
                    item['note']=(item.get('note','')+' Из расчёта исключено отключённых курьеров по подтверждению пользователя: '+str(len(excluded))+'.').strip()
            private_details.append(detail)
        except (OSError,ValueError,KeyError,TypeError):
            private_details.append({'kind':'courier_metric_details','schema_version':1,'date':day,'shop_id':identity,
                'metrics':{key:{'aggregate':value,'groups':[],'reconciled':False,
                    'note':'Персональную выборку не удалось согласовать с источником.'} for key,value in metrics.items()}})
        summaries.append({'date': day, 'shop_id': identity, 'slot_type': 'limited',
                          'booked_places': fill['numerator'], 'capacity': fill['denominator'],
                          'fill_percent': fill['value'], 'metrics': metrics})
    if not summaries:
        raise ValueError('None of the requested DS is available; previous feed preserved')
    atomic_json(folder/'all-shops-observations.json', observations)
    report = {'schema_version': 1, 'snapshot_consistent': True, 'issues': [],
              'generated_at': datetime.now(timezone.utc).isoformat(), 'summaries': summaries}
    fresh = build([report])
    for detail in private_details:
        detail['generated_at']=report['generated_at']
        atomic_json((completion_state_dir or private_dir)/'details'/f"{day}-{detail['shop_id']}.json",detail)
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
            'completion_reporting': {s['shop_id']: s['completion_reporting'] for s in observations['shops']},
            'report': report}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--session', type=Path, default=Path('/root/curator-session.json'))
    parser.add_argument('--proxy', default=configured_proxy())
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
