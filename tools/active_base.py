"""Five-day direct-DS scheduled population, matching the audited dashboard count."""
from datetime import date, timedelta
from audit_sources import sanitize_slot
from calculate_metrics import metric
from enrich_slots import fetch

BASIS = 'direct_shop_scheduled_unique_5d_including_day'


def participants(slots, shop):
    return {c['courier_id'] for s in slots
            if s['scope_kind'] == 'shopno' and s['scope_id'] == shop
            for c in s['couriers']}


def collect(day, shop, current_slots, token, proxy):
    direct_today = participants(current_slots, shop)
    today = {c['courier_id'] for s in current_slots for c in s['couriers']}
    population = set(direct_today)
    for offset in range(1, 5):
        previous = (date.fromisoformat(day)-timedelta(days=offset)).isoformat()
        payload = fetch((previous, 'shopno', shop, 'all'), token, proxy)
        rows = payload if isinstance(payload, list) else payload.get('slots', payload.get('items'))
        if not isinstance(rows, list):
            raise ValueError('Incomplete five-day population')
        slots = [sanitize_slot(row, previous, 'shopno', shop) for row in rows]
        population.update(participants(slots, shop))
    # Count bookings anywhere in the verified DS/cluster scope, but only for
    # members of the direct-DS active population. Guests cannot inflate it.
    return metric(len(today & population), len(population), basis=BASIS)
