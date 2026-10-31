"""Private late/no-show report for manual and limited slots from live schedules API."""
import argparse
from collections import Counter
import csv
from datetime import date, datetime
import html
import io
import json
from pathlib import Path

from enrich_slots import ApiError, source_status
from prepare_openvpn import private_write
from proxy_config import configured_proxy
from report_tomorrow import collect, clean, MOSCOW


def status(value):
    text = (value or '').strip().lower()
    return text if text in {'late', 'no_show', 'expected', 'early', 'on_time'} else source_status(value)


def observations(shop):
    all_rows = []
    for slot in shop['slots']:
        for person in slot['couriers']:
            all_rows.append({'shop_id': shop['shop_id'], 'slot_id': slot['slot_id'],
                'scope': clean(slot['name']), 'slot_type': slot['slot_type'],
                'time_from': clean(slot['time_from']), 'time_to': clean(slot['time_to']),
                'courier_id': person['courier_id'], 'name': clean(person['name']),
                'state': status(person['shift_status']), 'source_status': clean(person['shift_status'] or 'Не передан'),
                'shift_start': person['shift_start'] or '—', 'shift_end': person['shift_end'] or '—'})
    counts = Counter(r['state'] for r in all_rows)
    flagged = [r for r in all_rows if r['state'] in {'late', 'no_show'}]
    summary = {'total_slots': len(shop['slots']), 'total_records': len(all_rows),
               'unique_couriers': len({r['courier_id'] for r in all_rows}),
               'late_records': counts['late'], 'no_show_records': counts['no_show'],
               'late_unique': len({r['courier_id'] for r in flagged if r['state'] == 'late'}),
               'no_show_unique': len({r['courier_id'] for r in flagged if r['state'] == 'no_show'}),
               'affected_unique': len({r['courier_id'] for r in flagged}),
               'expected_records': counts['expected'], 'unknown_records': counts['unknown'],
               'contradictory_no_show_records': sum(r['state'] == 'no_show' and r['shift_start'] != '—' for r in all_rows)}
    return summary, flagged


def render(day, generated, shops):
    title = f'Опоздания и невыходы за {day} · ДС ' + ', '.join(str(s['shop_id']) for s in shops)
    intro = f'{title}\nСнимок: {generated}\nИсточник: «Выходы курьеров», API; ручные и лимитированные слоты, включая подтверждённые кластеры.\n'
    text = [intro]
    summaries, records = [], []
    for shop in shops:
        if not shop['available']:
            text.append(f"ДС {shop['shop_id']}: данные недоступны ({shop['reason']}); не нулевой результат.")
            summaries.append({'shop_id': shop['shop_id'], 'available': False, 'reason': shop['reason']})
            continue
        summary, flagged = observations(shop)
        summaries.append({'shop_id': shop['shop_id'], 'available': True, **summary})
        records.extend(flagged)
        text.append(f"ДС {shop['shop_id']}: проверено {summary['total_slots']} слотов, {summary['total_records']} записей, {summary['unique_couriers']} уникальных курьеров.\n"
                    f"Опоздали: {summary['late_unique']} курьеров / {summary['late_records']} записей. "
                    f"Не вышли: {summary['no_show_unique']} курьеров / {summary['no_show_records']} записей.\n"
                    f"Ожидаются: {summary['expected_records']} записей; неизвестный статус: {summary['unknown_records']}. "
                    f"Противоречивый невыход с указанным началом смены: {summary['contradictory_no_show_records']}.")
        for state, label in [('late', 'ОПОЗДАВШИЕ'), ('no_show', 'НЕВЫШЕДШИЕ')]:
            text.append(label)
            chosen = [r for r in flagged if r['state'] == state]
            if not chosen:
                text.append('Записей с таким статусом нет на момент снимка.')
            for row in sorted(chosen, key=lambda r: (r['time_from'], r['name'], r['slot_id'])):
                kind = 'лимитированный' if row['slot_type'] == 'limited' else 'ручной'
                text.append(f"{row['name']} (ID {row['courier_id']}) | {row['scope']} | "
                            f"{row['time_from']}–{row['time_to']} | {kind}, слот {row['slot_id']} | "
                            f"{row['source_status']} | факт начала: {clean(row['shift_start'])}")
    note = ('Невыход учитывается только по явному статусу источника. «Ожидается», пустой статус и отсутствие времени начала не означают невыход. '
            'Один курьер может встречаться в нескольких слотах и категориях; уникальные количества категорий нельзя автоматически складывать. '
            'Слоты отнесены к дате начала. Фактическое время показано как передано API; длительность опоздания не вычисляется без однозначных временных данных.')
    text.append(note)
    esc = lambda x: html.escape(str(x))
    cards = ''
    for s in summaries:
        if not s['available']:
            content = '<p>Данные недоступны: ' + esc(s['reason']) + '</p>'
        else:
            content = (f"<div class='stats'><div><b>{s['late_unique']}</b>опоздавших курьеров<br>{s['late_records']} записей</div>"
                       f"<div><b>{s['no_show_unique']}</b>невышедших курьеров<br>{s['no_show_records']} записей</div></div>"
                       f"<p>Проверено слотов: {s['total_slots']} · Курьеров: {s['unique_couriers']}<br>"
                       f"Ожидаются: {s['expected_records']} записей · Неизвестно: {s['unknown_records']}</p>")
        cards += '<article><h2>ДС ' + str(s['shop_id']) + '</h2>' + content + '</article>'
    headers = ['ДС','Категория','ФИО','ID курьера','Направление','Слот','Тип','Плановое время','Статус источника','Фактическое начало','Фактический конец']
    values = [[r['shop_id'], 'Опоздал' if r['state']=='late' else 'Не вышел',r['name'],r['courier_id'],r['scope'],r['slot_id'],
               'Лимитированный' if r['slot_type']=='limited' else 'Ручной',r['time_from']+'–'+r['time_to'],r['source_status'],r['shift_start'],r['shift_end']] for r in records]
    body = ''.join('<tr>' + ''.join('<td>'+esc(v)+'</td>' for v in row) + '</tr>' for row in values)
    page = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{font:16px/1.5 system-ui;background:#f2f5f9;color:#18364b;margin:28px}h1{font-size:28px}.cards{display:flex;gap:20px;flex-wrap:wrap}article{background:white;padding:20px;border-radius:14px;min-width:300px}.stats{display:flex;gap:28px}.stats b{display:block;font-size:36px}.scroll{overflow:auto;margin-top:24px}table{border-collapse:collapse;background:white;font-size:14px}th,td{padding:10px;border:1px solid #dfe7ef;text-align:left;vertical-align:top}th{background:#e5edf5}button{padding:10px}footer{margin-top:20px;color:#607589}@media print{button{display:none}body{margin:0;background:white}.scroll{overflow:visible}table{font-size:10px}tr{break-inside:avoid}@page{size:A3 landscape;margin:10mm}}</style>'''
    page += '<h1>'+esc(title)+'</h1><p>Снимок: '+esc(generated)+'</p><button onclick="window.print()">Печать / PDF</button><div class="cards">'+cards+'</div>'
    page += '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+body+'</tbody></table></div><footer>'+esc(note)+'</footer></html>'
    stream = io.StringIO();writer=csv.writer(stream,delimiter=';');writer.writerow(headers)
    for row in values:
        writer.writerow(["'"+str(v) if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in row])
    return '\n\n'.join(text)+'\n', page, '\ufeff'+stream.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',default=datetime.now(MOSCOW).date().isoformat())
    parser.add_argument('--shops',nargs='+',type=int,default=[7745,8889])
    parser.add_argument('--proxy',default=configured_proxy())
    args=parser.parse_args();date.fromisoformat(args.date)
    token=json.loads(Path('/root/curator-session.json').read_text())['token']
    if not isinstance(token,str) or not token or any(c in token for c in '\r\n'):raise ValueError('Invalid token')
    shops=collect(args.date,args.shops,token,args.proxy)
    output=Path('/opt/courier-analytics/private/reports');output.mkdir(parents=True,exist_ok=True,mode=0o700)
    text,page,csv_text=render(args.date,datetime.now(MOSCOW).isoformat(timespec='seconds'),shops)
    for ext,content in [('txt',text),('html',page),('csv',csv_text)]:
        path=output/f'attendance-{args.date}.{ext}';private_write(path,content)
    print(text)
    print('TXT, HTML и CSV сохранены приватно: '+str(output/f'attendance-{args.date}.*'))
    print('Дашборд и таймеры не изменены.')


if __name__=='__main__':
    try:main()
    except ApiError as error:raise SystemExit('API HTTP '+str(error.status)+'; response hidden.')
    except RuntimeError as error:
        from verify_server_proxy import error_code
        raise SystemExit('Report failed: '+error_code(error))
    except (OSError,ValueError,TypeError,KeyError):raise SystemExit('Report failed: source/session/local validation; private details hidden.')
