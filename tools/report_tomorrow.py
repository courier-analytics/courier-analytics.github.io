"""Private detailed and concise reports from live courier schedules, no dashboard writes."""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_sources import sanitize_slot
from discover_scopes import discover
from enrich_slots import ApiError, api_get, fetch
from prepare_openvpn import private_write
from proxy_config import configured_proxy

MOSCOW = ZoneInfo('Europe/Moscow')


def totals(slots):
    limited = [s for s in slots if s['slot_type'] == 'limited']
    for slot in limited:
        if type(slot['capacity']) is not int or slot['capacity'] < 0:
            raise ValueError('Invalid limited capacity')
        if type(slot['occupied']) is not int or slot['occupied'] != len(slot['couriers']):
            raise ValueError('Occupied count differs from participants')
    capacity = sum(s['capacity'] for s in limited)
    booked = sum(len(s['couriers']) for s in limited)
    return {'limited_slots': len(limited), 'capacity': capacity, 'booked_places': booked,
            'vacancies': sum(max(s['capacity'] - len(s['couriers']), 0) for s in limited),
            'overbooked_places': sum(max(len(s['couriers']) - s['capacity'], 0) for s in limited),
            'fill_percent': round(booked / capacity * 100, 2) if capacity else None,
            'manual_slots': sum(s['slot_type'] == 'manual' for s in slots),
            'manual_records': sum(len(s['couriers']) for s in slots if s['slot_type'] == 'manual'),
            'unique_couriers': len({p['courier_id'] for s in slots for p in s['couriers']})}


def collect(day, shops, token, proxy):
    config = discover(api_get('/v1/shops', token, proxy), api_get('/v1/clusters', token, proxy), targets=shops)
    output = []
    for shop in config['shops']:
        result = {'shop_id': shop['shop_id'], 'available': False}
        output.append(result)
        if not shop['scope_verified']:
            result['reason'] = shop.get('reason', 'scope_not_verified')
            continue
        try:
            slots, seen = [], set()
            for kind, scope in [('shopno', shop['shop_id'])] + [('cluster_id', c) for c in shop['cluster_ids']]:
                payload = fetch((day, kind, scope, 'all'), token, proxy)
                rows = payload if isinstance(payload, list) else payload.get('slots', payload.get('items'))
                if not isinstance(rows, list):
                    raise ValueError('Unknown slot list format')
                for raw in rows:
                    slot = sanitize_slot(raw, day, kind, scope)
                    identity = (slot['slot_type'], slot['slot_id'])
                    if identity in seen:
                        raise ValueError('Duplicate slot across scopes')
                    seen.add(identity)
                    names = {str(p.get('id')): str(p.get('name') or 'ФИО не передано')
                             for p in raw['couriers'] if p.get('status') != 'cancelled'}
                    for person in slot['couriers']:
                        person['name'] = names[person['courier_id']]
                    slot['name'] = str(raw.get('name') or scope)
                    slots.append(slot)
            result.update(available=True, slots=slots, totals=totals(slots), cluster_ids=shop['cluster_ids'])
        except ApiError as error:
            result['reason'] = 'slots_http_' + str(error.status)
        except (ValueError, TypeError, KeyError):
            result['reason'] = 'source_validation_failed'
    return output


def clean(value):
    return ' '.join(str(value).split()).replace('|', '/')


def reports(day, generated, shops):
    heading = f'План выходов на {day} (дата начала слота, МСК)\nСнимок: {generated}\nИсточник: API «Выходы курьеров», ДС и подтверждённые кластеры.\n'
    concise, detail = [heading], [heading]
    for shop in shops:
        prefix = 'ДС ' + str(shop['shop_id'])
        if not shop['available']:
            text = prefix + ': данные недоступны (' + shop['reason'] + '). Это не нулевой план.'
            concise.append(text); detail.append(text)
            continue
        t = shop['totals']
        fill = str(t['fill_percent']).replace('.', ',') + '%' if t['fill_percent'] is not None else 'не рассчитывается'
        line = (f"{prefix}: записано {t['unique_couriers']} уникальных курьеров; "
                f"лимитированные слоты — {t['booked_places']}/{t['capacity']} мест ({fill}), "
                f"свободно {t['vacancies']}; ручные записи — {t['manual_records']}.")
        concise.append(line)
        detail.extend([line, f"Лимитированных слотов: {t['limited_slots']}; ручных: {t['manual_slots']}; "
                       f"мест сверх лимита: {t['overbooked_places']}.",
                       'Слот | ДС/кластер | Время | Тип | Записано/мест | Свободно | Курьеры'])
        for s in sorted(shop['slots'], key=lambda s: (str(s['time_from']), s['scope_kind'], s['scope_id'], s['slot_id'])):
            limited = s['slot_type'] == 'limited'
            booked = len(s['couriers'])
            places = f"{booked}/{s['capacity']}" if limited else f'{booked}/без лимита'
            free = str(max(s['capacity'] - booked, 0)) if limited else '—'
            names = '; '.join(clean(p['name']) + ' (ID ' + p['courier_id'] + ')' for p in s['couriers']) or 'нет записей'
            detail.append(f"{s['slot_id']} | {clean(s['name'])} ({s['scope_kind']} {s['scope_id']}) | "
                          f"{clean(s['time_from'])}–{clean(s['time_to'])} | {s['slot_type']} | {places} | {free} | {names}")
    if all(s['available'] for s in shops):
        identities = [{p['courier_id'] for slot in s['slots'] for p in slot['couriers']} for s in shops]
        shared = set.intersection(*identities) if len(identities) > 1 else set()
        if shared:
            note = f'Внимание: в обоих ДС записаны {len(shared)} курьеров. Итоги по ДС нельзя складывать как уникальных людей.'
            concise.append(note);detail.append(note)
    note = ('Запись на слот — план, а не подтверждённый фактический выход. Свободные места рассчитаны только '
            'по лимитированным слотам; ручные записи показаны отдельно. Ночные слоты включены по дате начала. '
            'Отчёт — текущий снимок, не замороженный план на 23:59.')
    concise.append(note);detail.append(note)
    return '\n\n'.join(concise) + '\n', '\n'.join(detail) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', default=(datetime.now(MOSCOW).date() + timedelta(days=1)).isoformat())
    parser.add_argument('--shops', nargs='+', type=int, default=[8889, 7745])
    parser.add_argument('--proxy', default=configured_proxy())
    parser.add_argument('--output-dir', type=Path, default=Path('/opt/courier-analytics/private/reports'))
    args = parser.parse_args()
    date.fromisoformat(args.date)
    token = json.loads(Path('/root/curator-session.json').read_text())['token']
    if not isinstance(token, str) or not token or any(c in token for c in '\r\n'):
        raise ValueError('Invalid session')
    shops = collect(args.date, args.shops, token, args.proxy)
    generated = datetime.now(MOSCOW).isoformat(timespec='seconds')
    concise, detailed = reports(args.date, generated, shops)
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for variant, content in [('concise', concise), ('detailed', detailed)]:
        path = args.output_dir / f'exits-{args.date}-{variant}.txt'
        private_write(path, content)
    print('СЖАТЫЙ ОТЧЁТ\n' + concise)
    print('ПОДРОБНЫЙ ОТЧЁТ\n' + detailed)
    print('Оба отчёта сохранены приватно (600). Дашборд и таймеры не изменены.')


if __name__ == '__main__':
    try:
        main()
    except ApiError as error:
        raise SystemExit('API HTTP ' + str(error.status) + '; response hidden. Report not completed.')
    except RuntimeError as error:
        from verify_server_proxy import error_code
        raise SystemExit('Report failed: ' + error_code(error))
    except (OSError, ValueError, TypeError, KeyError):
        raise SystemExit('Report failed: source/session/local validation. Private details hidden.')
