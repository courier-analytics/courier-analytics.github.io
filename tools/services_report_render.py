"""Render the verified DS9107 pilot as an HTML report; missing facts remain blank."""
import argparse,html,json,math
from pathlib import Path

def render(payload):
    samples={r['date']:r for r in payload['samples']}
    def row(day):
        sample=samples[day]
        if sample.get('http_status')!=200 or len(sample['rows'])!=1:raise ValueError('Unconfirmed report source')
        value=sample['rows'][0]
        if value.get('shopno')!=9107:raise ValueError('Unexpected shop')
        return value
    current,previous=row('2026-11-09'),row('2026-11-08')
    def pct(key):
        value=current.get(key);before=previous.get(key)
        if value is None:return '—'
        delta=(value-before)*100 if before is not None else None
        trend='' if delta is None else f'<small class="{"down" if delta<=0 else "up"}">{"↓" if delta<=0 else "↑"}{abs(delta):.1f} п.п.</small>'
        return f'<strong>{value*100:.1f}%</strong> {trend}'
    def c2e():
        value=current.get('avg_order_time');before=previous.get('avg_order_time')
        if value is None:return 'Нет данных'
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('Invalid C2E')
        trend=''
        if before is not None:
            if not isinstance(before,(int,float)) or not math.isfinite(before) or before<0:raise ValueError('Invalid previous C2E')
            delta=value-before
            trend=f'<small class="{"down" if delta<=0 else "up"}">{"↓" if delta<=0 else "↑"}{abs(delta):.1f} мин</small>'
        return f'<strong>{value:.2f} мин</strong> {trend}'
    return '''<!doctype html><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#fff;color:#233147;font:16px Arial,sans-serif;width:1365px}header{background:#1b2b49;color:white;padding:22px 26px}h1{margin:0 0 10px;font-size:29px}header p{margin:6px 0;color:#bdc9df;font-size:15px}main{padding:38px 18px 24px}table{border-collapse:collapse;width:100%;font-size:16px}th{background:#263f68;color:white;text-align:left;padding:15px 10px}td{padding:20px 10px;border-bottom:1px solid #dfe5ee}td.total{font-weight:bold;background:#eef2f8}.down{color:#168458}.up{color:#c3424a}small{font-size:13px;font-weight:bold;margin-left:7px}.missing{color:#96a0b1}.notes{font-size:14px;line-height:1.7;color:#6e7b90;margin:22px 8px 0}.draft{display:inline-block;margin-top:9px;padding:6px 10px;background:#344766;border-radius:5px;font-size:13px;color:white}
    </style><header><h1>Просрочки — 9107 Николо-Хованская</h1><p>09.11.2026 · Курьеры + Такси · по дате доставки · сравнение с 08.11.2026</p><p>Полные сутки 00:00–24:00 МСК</p><span class="draft">Проверочный отчёт · 5 показателей · C2E по формуле Superset</span></header><main><table><thead><tr><th>ДС</th><th>Доставлено</th><th>Курьеров</th><th>Сборка</th><th>Общая (время)</th><th>За час</th><th>Ожидание → риск</th><th>C2E (ср. время)</th></tr></thead><tbody><tr><td>9107 ДС</td><td>'''+str(current['qty_orders_delivered'])+'''</td><td>'''+str(current['qty_couriers'])+'''</td><td>'''+pct('share_collection_delay_all')+'''</td><td>'''+pct('share_all_0_sla_offline')+'''</td><td class="missing">—</td><td class="missing">—</td><td>'''+c2e()+'''</td></tr></tbody></table><div class="notes">Источник: Superset · services_lite · набор 3035. Показатели получены штатными формулами источника.<br>Стрелки — изменение к предыдущему дню в процентных пунктах; снижение просрочек отмечено зелёным. Изменение C2E показано в минутах.<br>Почасовые данные, ожидание, магазины зоны и сравнение с Москвой в проверочную выгрузку пока не включены.<br>В образце данные были на 22:15; здесь показаны полные сутки, поэтому значения могут отличаться.</div></main>'''

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.write_text(render(json.loads(a.input.read_text())))
