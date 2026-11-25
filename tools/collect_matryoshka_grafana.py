"""Collect delivered order IDs for verified Matryoshka participants into private SQLite."""
import fcntl
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from probe_grafana import probe

ROOT = Path('/opt/courier-analytics/private/grafana')
PARTICIPANTS = Path('/opt/courier-analytics/private/matryoshka-monitor.json')

def epoch(value):
    if isinstance(value, (int, float)):
        return float(value) / 1000  # Grafana frame timestamps are milliseconds.
    if not isinstance(value, str):
        raise ValueError('Invalid timestamp')
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo('Europe/Moscow'))
    return moment.timestamp()

def ingest(db_path, snapshot, export):
    if snapshot.get('verified') is not True or export.get('scope') != 'matryoshka participants across all shops':
        raise ValueError('Unverified source')
    participants = {str(int(p['courier_id'])): p for p in snapshot['participants']}
    prepared = []
    for row in export['rows']:
        identity = str(row['courier_id'])
        if identity not in participants:
            raise ValueError('Unexpected courier')
        delivered = epoch(row['delivered_at'])
        if delivered > export['observed_at_ms'] / 1000 + 120:
            raise ValueError('Future delivery')
        prepared.append((str(row['order_id']), identity, str(row['shop_number']), delivered))
    db = sqlite3.connect(db_path)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, courier_id TEXT NOT NULL, shop TEXT NOT NULL, delivered REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS participants(courier_id TEXT PRIMARY KEY, enrollment_id TEXT NOT NULL, enrolled REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            before = db.execute('SELECT count(*) FROM orders').fetchone()[0]
            for identity, p in participants.items():
                db.execute('INSERT INTO participants VALUES(?,?,?) ON CONFLICT(courier_id) DO UPDATE SET enrollment_id=excluded.enrollment_id,enrolled=excluded.enrolled',
                           (identity, p['enrollment_id'], epoch(p['enrolled_at'])))
            for row in prepared:
                old = db.execute('SELECT courier_id,shop,delivered FROM orders WHERE order_id=?', (row[0],)).fetchone()
                if old is not None and old != row[1:]:
                    raise ValueError('Order attribution changed; manual reconciliation required')
                db.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?)', row)
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('last_success', datetime.now(timezone.utc).isoformat()))
            after = db.execute('SELECT count(*) FROM orders').fetchone()[0]
        return {'participants': len(participants), 'received': len(prepared), 'new_orders': after-before, 'stored_orders': after,
                'history_complete': False}
    finally:
        db.close()

def main():
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT/'collector.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Collector already running; deferred.')
            return
        snapshot = json.loads(PARTICIPANTS.read_text())
        if not probe(proxy='socks5h://127.0.0.1:18081', query_shop=9107, delivered=True, matryoshka_only=True):
            raise RuntimeError('Grafana collection failed')
        current = json.loads(PARTICIPANTS.read_text())
        if current != snapshot:
            raise RuntimeError('Participant snapshot changed during collection; retry next run')
        export = json.loads((ROOT/'delivered-shop-9107.json').read_text())
        print('Matryoshka ledger:', json.dumps(ingest(ROOT/'orders.sqlite3', snapshot, export)))
        from reconcile_matryoshka_orders import save_report
        report = save_report(snapshot)
        print('Reconciliation saved; participants:',len(report['participants']),'; overlapping totals not added.')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Collection failed:', type(error).__name__, '; no success recorded')
        raise SystemExit(1)
