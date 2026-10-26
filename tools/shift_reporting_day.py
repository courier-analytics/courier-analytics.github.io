"""Assign an overnight shift to its actual completion date in Moscow."""
from datetime import date
from calculate_metrics import MOSCOW, period, timestamp


def reporting_day(slot, person):
    origin = date.fromisoformat(slot['date'])
    start, planned_end = period(slot)
    if planned_end.date() == origin:
        return origin.isoformat()
    actual_end = timestamp(person.get('shift_end'))
    if actual_end is None or actual_end < start:
        return None
    return actual_end.astimezone(MOSCOW).date().isoformat()
