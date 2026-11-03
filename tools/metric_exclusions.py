"""Explicit, date/shop-scoped private exclusions; original snapshots stay immutable."""
from copy import deepcopy
from pathlib import Path
import json


def load(private,day,shop):
    path=Path(private)/'metric-exclusions'/f'{day}-{shop}.json'
    if not path.exists():return set()
    data=json.loads(path.read_text());ids=data.get('courier_ids')
    if (data.get('date')!=day or data.get('shop_id')!=shop or data.get('reason')!='user_confirmed_disabled' or
            not isinstance(ids,list) or any(not isinstance(i,str) or not i.isdigit() for i in ids)):
        raise ValueError('Invalid private exclusion policy')
    return set(ids)


def filter_slots(slots,ids):
    result=deepcopy(slots)
    for slot in result:
        slot['couriers']=[person for person in slot['couriers'] if person['courier_id'] not in ids]
        if 'occupied' in slot:slot['occupied']=len(slot['couriers'])
    return result


def views(slots,plan,roster,ids):
    if not ids:return slots,plan,roster
    slots=filter_slots(slots,ids)
    if plan:plan={**plan,'slots':filter_slots(plan['slots'],ids)}
    if roster:
        roster={**roster,'courier_ids':[i for i in roster['courier_ids'] if i not in ids]}
        roster['count']=len(roster['courier_ids'])
    return slots,plan,roster
