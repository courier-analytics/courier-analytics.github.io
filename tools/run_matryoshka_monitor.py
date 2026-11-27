"""Fetch a fresh snapshot, then deliver notices with persistent delivery claims."""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from matryoshka_alerts import plan
from send_services_photo import NoRedirect

ROOT = Path('/opt/courier-analytics/private')


def notices(snapshot, now):
    result = plan(snapshot, now)
    alerts = []
    for person in snapshot['participants']:
        identity = person['courier_id']
        event = hashlib.sha256(json.dumps([identity, person['enrollment_id'], 'joined']).encode()).hexdigest()
        alerts.append({'event_id': event, 'text':
            f"Матрёшка: участник обнаружен\n{person['name']} · ID {identity}\n"
            f"ДС последнего заказа: {person['last_shop']}\nТип по последнему доставленному заказу: {person['current_type']}\n"
            f"Доставлено с первого заказа Матрёшки: {person['delivered_orders']}\n"
            f"Начало отсчёта: {person['enrolled_at']}\n"
            "Источник: заказы Superset; дата подключения и текущая карточка курьера отдельно не подтверждены."})
    for event in result['alerts']:
        event['text'] = event['text'].replace('Доставлено с подключения:', 'Доставлено с первого заказа Матрёшки:')
        event['text'] += '\nТип определён по последнему доставленному заказу в Superset.'
        alerts.append(event)
    return alerts


def telegram(text):
    config = Path('/etc/superset-telegram')
    for name in ('telegram.json', 'test-group.json'):
        if (config / name).stat().st_mode & 0o077:
            raise ValueError('Telegram configuration must be private')
    token = json.loads((config / 'telegram.json').read_text())['token']
    chat = json.loads((config / 'test-group.json').read_text())['chat_id']
    if chat != -1004427986473:
        raise ValueError('Unexpected Telegram group')
    request = urllib.request.Request('https://api.telegram.org/bot' + token + '/sendMessage',
        data=json.dumps({'chat_id': chat, 'text': text}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
        answer = json.load(response)
    if answer.get('ok') is not True or type(answer.get('result', {}).get('message_id')) is not int:
        raise ValueError('Telegram delivery not confirmed')
    return answer['result']['message_id']


def deliver(db, events, sender):
    db.execute('CREATE TABLE IF NOT EXISTS deliveries (event_id TEXT PRIMARY KEY, status TEXT NOT NULL, message_id INTEGER)')
    db.commit()
    sent = 0
    for event in events:
        # Commit claim before network I/O. A crash or uncertain network response
        # remains held for manual review, never blindly resent on the next poll.
        cursor = db.execute("INSERT OR IGNORE INTO deliveries(event_id,status) VALUES (?, 'inflight')", (event['event_id'],))
        db.commit()
        if not cursor.rowcount:
            continue
        try:
            message_id = sender(event['text'])
        except Exception:
            db.execute("UPDATE deliveries SET status='uncertain' WHERE event_id=?", (event['event_id'],))
            db.commit()
            raise RuntimeError('Telegram delivery uncertain; event held, check test group before retrying') from None
        db.execute("UPDATE deliveries SET status='sent',message_id=? WHERE event_id=?", (message_id,event['event_id']))
        db.commit()
        sent += 1
    return sent


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--send', action='store_true')
    args = p.parse_args()
    os.umask(0o077)
    before = datetime.now(ZoneInfo('Europe/Moscow'))
    subprocess.run([sys.executable, str(Path(__file__).with_name('probe_superset_vpn.py')),
                    '--wait-vpn', '120', '--check-login', '--collect-matryoshka'], check=True, timeout=480)
    snapshot = json.loads((ROOT / 'matryoshka-monitor.json').read_text())
    if datetime.fromisoformat(snapshot['observed_at']) < before:
        raise ValueError('Snapshot was not refreshed')
    events = notices(snapshot, datetime.now(ZoneInfo('Europe/Moscow')))
    print('Matryoshka notice candidates=' + str(len(events)), flush=True)
    if args.send:
        with sqlite3.connect(ROOT / 'matryoshka-deliveries.sqlite3') as db:
            print('Matryoshka notices sent=' + str(deliver(db, events, telegram)), flush=True)
            uncertain = db.execute("SELECT count(*) FROM deliveries WHERE status!='sent'").fetchone()[0]
            print('Matryoshka deliveries requiring review=' + str(uncertain), flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Matryoshka monitor failed: ' + type(error).__name__ + '; private details hidden') from None
