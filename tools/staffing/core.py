"""Courier staffing methodology, corporate weeks 910–914. Standard library only."""
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta, timezone
from math import ceil, isfinite
import re
import unicodedata

START = date(2026, 10, 12)
END = date(2026, 11, 16)
SHOPS = (8889, 9107)
SUCCESS = 'Успешно завершен'


def name(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def timestamp(value):
    if not value: return None
    if type(value) in (int,float):
        if not isfinite(value): raise ValueError('Nonfinite timestamp')
        # Superset re-encodes its main temporal column as epoch milliseconds
        # even when the exported SQL value is a timezone-free local string.
        return datetime.fromtimestamp(value/1000,timezone.utc).replace(tzinfo=None)
    if not isinstance(value, str): raise ValueError('Unsupported timestamp encoding')
    d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if d.tzinfo is not None: raise ValueError('Expected source wall-clock timestamps')
    return d


def week(day):
    return 910 + (day - START).days // 7


def working_seconds(intervals):
    """Union overlaps and include gaps <= 60 minutes; exclude larger gaps fully."""
    if not intervals: return 0
    items = sorted(intervals)
    left, right = items[0]
    total = 0
    for start, end in items[1:]:
        if start <= right + timedelta(minutes=60):
            right = max(right, end)
        else:
            total += (right-left).total_seconds()
            left, right = start, end
    return total + (right-left).total_seconds()


def safe_ratio(n, d): return n/d if d else None


def need(orders_daily, growth=1):
    staff = ceil(orders_daily * growth / 44 / .6)
    return {'staff':staff, 'orders_daily':orders_daily*growth,
            'good':{'shifts':staff*.6,'core':staff*.6*.7,'side':staff*.6*.3},
            'bad':{'shifts':staff*.8,'core':staff*.8*.7,'side':staff*.8*.3}}


def group_totals(people):
    groups = {}
    for label in ('core', 'side'):
        subset = [p for p in people if p['group']==label]
        seconds = sum(p['seconds'] for p in subset)
        shifts = sum(p['shifts'] for p in subset)
        orders = sum(p['orders'] for p in subset)
        groups[label] = {'staff':len(subset),'seconds':seconds,'shifts':shifts,'orders':orders,
            'hours_per_shift':safe_ratio(seconds/3600,shifts),
            'orders_per_shift':safe_ratio(orders,shifts),'orders_per_hour':safe_ratio(orders,seconds/3600)}
    staff = len(people); shifts = sum(p['shifts'] for p in people)
    return {'staff':staff, 'shifts':shifts,'daily_shifts':shifts/7,
            'attendance_percent':safe_ratio(shifts/7*100,staff), 'groups':groups,
            'core_staff_percent':safe_ratio(groups['core']['staff']*100,staff),
            'side_staff_percent':safe_ratio(groups['side']['staff']*100,staff),
            'side_shift_percent':safe_ratio(groups['side']['shifts']*100,shifts),
            'core_shift_percent':safe_ratio(groups['core']['shifts']*100,shifts)}


def weighted(weeks):
    # Courier is counted once in each shop-week, not once in the entire period.
    staff = sum(w['staff'] for w in weeks); shifts = sum(w['shifts'] for w in weeks)
    result = {'staff_weeks':staff,'shifts':shifts,'groups':{}}
    for label in ('core','side'):
        g = {k:sum(w['groups'][label][k] for w in weeks) for k in ('staff','seconds','shifts','orders')}
        g.update(staff_percent=safe_ratio(g['staff']*100,staff),shift_percent=safe_ratio(g['shifts']*100,shifts),
                 hours_per_shift=safe_ratio(g['seconds']/3600,g['shifts']),
                 orders_per_shift=safe_ratio(g['orders'],g['shifts']),
                 orders_per_hour=safe_ratio(g['orders'],g['seconds']/3600))
        result['groups'][label]=g
    result['core_shift_deviation_pp']=None if not shifts else result['groups']['core']['shift_percent']-70
    return result


def analyse(rows):
    exclusions = Counter(); by_shop = {shop:Counter() for shop in SHOPS}; dedup = {}
    def exclude(key, shop):
        exclusions[key]+=1;by_shop[shop][key]+=1
    for row in rows:
        if int(row['shopno']) not in SHOPS: raise ValueError('Unexpected shop')
        identity = str(row.get('id_order') or '')
        if not identity: raise ValueError('Missing order ID')
        key=(int(row['shopno']),identity)
        if key in dedup:
            if row == dedup[key]: exclude('identical_duplicate_rows',key[0]); continue
            # An order changing version inside a paginated export would make
            # totals unverifiable. Do not silently select a convenient version.
            raise ValueError('Conflicting versions of an order; repeat export')
        dedup[key]=row
    loads=Counter(); people=defaultdict(lambda:{'intervals':[],'days':set(),'orders':0})
    for (shop,identity), r in dedup.items():
        supply=timestamp(r.get('date_supply'))
        if supply and START<=supply.date()<END: loads[shop,week(supply.date())]+=1
        if r.get('status_name') != SUCCESS: continue
        try:
            start=timestamp(r.get('date_delivery_start'))
        except ValueError:
            if supply and START<=supply.date()<END:exclude('invalid_delivery_date',shop)
            continue
        reference=start or supply
        if not reference or not START<=reference.date()<END:continue
        if r.get('delivery_type_group') != 'Курьеры': exclude('non_courier_service',shop); continue
        kind = str(r.get('id_courier_type') or '')
        label = name(r.get('courier_type'))
        if kind in ('6','9','15','16') or 'мобильн' in label:
            exclude('mobile_successful_orders',shop); continue
        who=name(r.get('courier'))
        if not who: exclude('missing_courier_name',shop); continue
        if start is None: exclude('missing_delivery_start',shop); continue
        if not kind and not label:
            exclude('unknown_mobile_status_orders_excluded',shop)
            continue
        try:
            regular=timestamp(r.get('date_delivered'))
            offline=timestamp(r.get('order_closed_offline_dttm'))
        except ValueError:
            exclude('invalid_delivery_date',shop);continue
        person=people[shop,week(start.date()),who]
        person['days'].add(start.date());person['orders']+=1
        # Prefer a valid offline close. Invalid closes never overwrite a valid end.
        end=offline if offline and offline>=start else regular
        if offline and offline<start: exclude('offline_close_before_start',shop)
        if end is None or end<start:
            exclude('missing_or_negative_interval_hours_excluded',shop);continue
        if end-start>timedelta(hours=12):
            exclude('over_12h_quarantined_hours_excluded',shop);continue
        person['intervals'].append((start,end))
    weekly={}
    for shop in SHOPS:
        items=[]
        for number in range(910,915):
            roster=[]
            for (s,w,who),p in people.items():
                if (s,w)!=(shop,number):continue
                seconds=working_seconds(p['intervals'])
                roster.append({'courier':who,'seconds':seconds,'shifts':len(p['days']),
                               'orders':p['orders'],'group':'core' if seconds>50*3600 else 'side'})
            totals=group_totals(roster)
            totals.update(week=number,load_orders=loads[shop,number],load_daily=loads[shop,number]/7)
            assert totals['staff']==sum(g['staff'] for g in totals['groups'].values())
            assert totals['shifts']==sum(g['shifts'] for g in totals['groups'].values())
            items.append(totals)
        latest=items[-1]
        current=need(latest['load_daily']);growth=need(latest['load_daily'],1.1)
        weekly[str(shop)]={'weeks':items,'weighted':weighted(items),'need':current,'growth':growth,
            'staff_deficit':max(0,current['staff']-latest['staff']),
            'shift_core_deviation_pp':None if latest['core_shift_percent'] is None else latest['core_shift_percent']-70}
    return {'period_start':START.isoformat(),'period_end_inclusive':(END-timedelta(days=1)).isoformat(),
            'shops':weekly,'combined':weighted([w for s in weekly.values() for w in s['weeks']]),
            'provisional':any(exclusions[k] for k in ('unknown_mobile_status_orders_excluded','invalid_delivery_date','missing_delivery_start','missing_or_negative_interval_hours_excluded','over_12h_quarantined_hours_excluded')),
            'exclusions':dict(exclusions),'exclusions_by_shop':{str(k):dict(v) for k,v in by_shop.items()},'input_rows':len(rows),'unique_shop_orders':len(dedup),
            'assumptions':[
              'Workload counts unique order IDs in all statuses by date_supply (delivery reporting date).',
              'Successful courier orders, shifts and whole intervals belong to delivery-start day/week; offline closing preferred when valid.',
              'Core >50h per shop-week; side <=50h. Names normalized by case/whitespace; namesakes may merge.',
              'Mobile types 6/9/15/16 and names containing мобильн excluded from workforce, not workload.',
              'Orders with unknown courier type excluded from individual metrics and counted explicitly; no inferred stationary status.',
              'Intervals >12h quarantined from hours pending manual confirmation; successful orders and attendance retained.',
              'Missing/invalid ends excluded only from hours; resulting hours/classification are incomplete if such exceptions exist.']}
