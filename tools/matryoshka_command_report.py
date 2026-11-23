"""Render verified Matryoshka participants; no network or message sending."""
import re
from datetime import datetime, timedelta
TYPES = {code: (transport, i + 1) for transport, codes in [('Вело', (24, 25, 26, 27)), ('Авто', (28, 29, 30, 31))] for i, code in enumerate(codes)}

def command(text, username):
    words = text.strip().split()
    if not words:
        return None
    first = words[0].split('@', 1)
    if first[0].lower() not in ('/matreshka', '/matreshka_idle'):
        return None
    if len(first) == 2 and first[1].lower() != username.lower():
        return None
    if len(words) > 2 or (len(words) == 2 and (not re.fullmatch('[1-9][0-9]{0,8}', words[1]))):
        raise ValueError('usage')
    return words[1] if len(words) == 2 else ''

def membership(rosters):
    result = {}
    for shop, data in rosters.items():
        if not str(shop).isdigit() or not isinstance(data, dict) or data.get('verified') is not True:
            continue
        for row in data.get('couriers', []):
            result.setdefault(str(row.get('courier_id', '')), set()).add(str(shop))
    return result

def render(snapshot, number, now, rosters=None, idle_days=None, pools=None):
    if snapshot.get('verified') is not True:
        raise ValueError('unverified')
    observed = datetime.fromisoformat(snapshot['observed_at'].replace('Z', '+00:00'))
    if observed.tzinfo is None or observed > now + timedelta(minutes=2):
        raise ValueError('invalid_time')
    groups = membership(rosters or {})
    rows = []
    seen = set()
    idle_info = {}
    unknown_last = 0
    if idle_days is not None and (type(idle_days) is not int or idle_days < 1):
        raise ValueError('invalid_idle_threshold')
    for p in snapshot['participants']:
        cid = p['courier_id']
        if not isinstance(cid, str) or not cid.isdigit() or cid in seen:
            raise ValueError('invalid_identity')
        seen.add(cid)
        if p.get('count_scope') != 'delivered_since_enrollment' or p.get('current_type_verified') is not True:
            raise ValueError('unverified_participant')
        code = p['current_type']
        count = p['delivered_orders']
        if type(code) is not int or code not in TYPES or type(count) is not int or (count < 0):
            raise ValueError('invalid_participant')
        tt = str(p.get('last_shop') or '')
        if not tt.isdigit():
            raise ValueError('invalid_shop')
        possible = groups.get(cid, set())
        ds = next(iter(possible)) if len(possible) == 1 else tt if tt in ('8889', '9107', '7745') and (not possible or tt in possible) else None
        if number and number not in (ds, tt):
            continue
        if idle_days is not None:
            try:
                last = datetime.fromisoformat(str(p['last_delivery']).replace('Z', '+00:00'))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=observed.tzinfo)
            except (KeyError, TypeError, ValueError):
                unknown_last += 1
                continue
            if last > observed + timedelta(minutes=2):
                raise ValueError('last_delivery_after_snapshot')
            elapsed = observed - last
            if elapsed < timedelta(days=idle_days):
                continue
            idle_info[cid] = (last, elapsed.days)
        transport, stage = TYPES[code]
        name = ' '.join(str(p.get('name') or cid).split())[:200]
        rows.append((ds or 'Не определён', name, cid, tt, transport, stage, count))
    rows.sort(key=lambda r: (idle_info[r[2]][0] if idle_days is not None else r[0], r[1].casefold(), r[2]))
    header = 'Матрёшка' + (' · ' + number if number else ' · все участники') + '\nДанные на ' + observed.astimezone(now.tzinfo).strftime('%d.%m.%Y %H:%M') + ' МСК'
    if idle_days is not None:
        header = header.replace('Матрёшка', 'Матрёшка · без доставок ' + str(idle_days) + ' полных дня', 1)
    if now - observed > timedelta(minutes=30):
        header += '\n⚠ Данные старше 30 минут.'
    footer = ''
    if idle_days is not None:
        pass
        if unknown_last:
            pass
    if not rows:
        return [header + ('\nУчастники с таким простоем не найдены.\n' if idle_days is not None else '\nУчастники не найдены.\n') + footer]
    entries = []
    for i, (ds, name, cid, tt, transport, stage, count) in enumerate(rows, 1):
        entry = f'{i}. {name}\nID {cid} · ДС {ds} · ТТ {tt}\n{transport} · этап {stage} · заказов {count}'
        participant = next(p for p in snapshot['participants'] if p['courier_id']==cid)
        overdue=participant.get('overdue_orders')
        confirmed=participant.get('overdue_verified') is True and participant.get('overdue_scope')=='delivered_since_enrollment' and type(overdue) is int and overdue>=0
        entry += '\nПросрочено за период Матрёшки: ' + (str(overdue) if confirmed else 'нет данных')
        from matryoshka_pools import label
        entry += '\n' + label(cid,now,pools or {})
        if idle_days is not None:
            last, days = idle_info[cid]
            entry += '\nПоследняя доставка: ' + last.astimezone(now.tzinfo).strftime('%d.%m.%Y %H:%M') + ' МСК · без доставок ' + str(days) + ' полных дн.'
        entries.append(entry)
    pages = []
    body = header + '\nУчастников: ' + str(len(rows)) + '\n\n'
    for entry in entries:
        if len(body) + len(entry) + len(footer) + 5 > 3500:
            pages.append(body + footer)
            body = header + ' · продолжение\n\n'
        body += entry + '\n\n'
    pages.append(body + footer)
    return pages
