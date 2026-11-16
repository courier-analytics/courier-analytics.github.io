"""Programmatic, aligned SVG reports. No fabricated report values."""
from html import escape
import base64
from pathlib import Path

W,H=3200,2000
DARK='#1b2b4a';INK='#23324b';MUTED='#65748b'


def n(value):return '—' if value is None else f'{value:.1f}'.replace('.',',')
def duration(value):
    if value is None:return '—'
    mins=round(value*60);return f'{mins//60} ч {mins%60:02d} мин'
def txt(x,y,text,size=26,bold=False,color=INK):
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{escape(str(text))}</text>'
def rect(x,y,w,h,color,r=12):return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{color}"/>'
def base(title,sub):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="DejaVu Sans,Arial,sans-serif">',
            rect(0,0,W,H,'#f7f9fc',0),rect(0,0,W,140,DARK,0),txt(42,62,title,43,True,'white'),txt(42,108,sub,25,False,'#c9d5e8')]

def weather_block(parts, data, y, weather):
    good=weather=='good';parts.append(rect(28,y,3144,482,'#e5f1e9' if good else '#e5eef8'))
    parts.append(txt(50,y+38,('Хорошая погода · 60% выхода' if good else 'Плохая погода · 80% выхода')+' · факт и расчётная потребность',28,True))
    labels=['Заказов в день, все статусы','Общий штат, человек','Ядро / подработчики, человек','Доля ядра / подработки в штате','Выход в день, человек','Ядро / подработчики в смене','Доля ядра / подработки в смене','Выход от общего штата']
    for i,label in enumerate(labels):parts.append(txt(50,y+123+i*43,label,23))
    x0=670;cw=345;gap=8
    for index in range(7):
        x=x0+index*(cw+gap);color='#fbe7e5' if index<5 else '#d8f2df' if index==5 else '#d9eafa'
        parts.append(rect(x,y+55,cw,410,color))
        if index<5:
            w=data['weeks'][index];g=w['groups'];values=[n(w['load_daily']),str(w['staff']),f"{g['core']['staff']} / {g['side']['staff']}",
              n(w['core_staff_percent'])+'% / '+n(w['side_staff_percent'])+'%',n(w['daily_shifts']),f"{n(g['core']['shifts']/7)} / {n(g['side']['shifts']/7)}",
              n(w['core_shift_percent'])+'% / '+n(w['side_shift_percent'])+'%',n(w['attendance_percent'])+'%'];title='Факт · '+str(w['week'])
        else:
            d=data['need'] if index==5 else data['growth'];scenario=d[weather]
            values=[n(d['orders_daily']),str(d['staff']),'Не нормируется¹','—',n(scenario['shifts']),f"{n(scenario['core'])} / {n(scenario['side'])}",'70,0% / 30,0%', '60,0%' if good else '80,0%'];title='Нужно сейчас' if index==5 else 'Нужно при +10%'
        parts.append(txt(x+14,y+89,title,25,True))
        for i,value in enumerate(values):parts.append(txt(x+14,y+123+i*43,value,24 if i in (3,6) else 27,i in (1,4)))

def performance(parts,data,y):
    parts.append(txt(42,y,'Фактическая продолжительность смен и производительность',32,True))
    labels=['Период','Группа','Смена','Заказов / смену','Заказов / час']
    xs=[50,490,1040,1660,2380]
    for x,label in zip(xs,labels):parts.append(txt(x,y+45,label,25,True))
    entries=[(str(w['week']),w['groups']) for w in data['weeks']]+[('5 недель · взвешенно',data['weighted']['groups'])]
    for index,(label,groups) in enumerate(entries):
        yy=y+83+index*45
        parts.append(rect(32,yy-29,3135,43,'#eef2f8' if index%2==0 else 'white',0))
        parts.extend([txt(xs[0],yy,label,24),txt(xs[1],yy,'Ядро / подработка',24),
            txt(xs[2],yy,duration(groups['core']['hours_per_shift'])+' / '+duration(groups['side']['hours_per_shift']),24),
            txt(xs[3],yy,n(groups['core']['orders_per_shift'])+' / '+n(groups['side']['orders_per_shift']),25),
            txt(xs[4],yy,n(groups['core']['orders_per_hour'])+' / '+n(groups['side']['orders_per_hour']),25)])

def footer(parts,report,shop=None):
    e=report["exclusions_by_shop"][str(shop)] if shop else report["exclusions"]
    notes=[
      'Методика: объединение пересечений; перерывы ≤60 мин включены, >60 мин исключены целиком. Ядро >50 ч за склад-неделю; ровно 50 ч — подработка.',
      'Нагрузка: уникальные «Заказ» всех статусов по date_supply. Часы и выходы: успешные заказы службы «Курьеры», по дню начала доставки; мобильные исключены.',
      'Потребность: ceil(заказов в день / 44 / 0,6). Выход — 60% штата. Норма 44 = 50×70% + 30×30%. ¹ 70/30 — состав смен, а не недельного штата.',
      'Пустые ФИО исключены из индивидуального расчёта; одноимённые курьеры объединены. Интервалы >12 ч изолированы из часов до ручной проверки.',
      f"Исключения (успешные заказы): мобильные — {e.get('mobile_successful_orders',0)}; другие службы — {e.get('non_courier_service',0)}; без ФИО — {e.get('missing_courier_name',0)}; без типа курьера — {e.get('unknown_mobile_status_orders_excluded',0)}; интервал >12 ч — {e.get('over_12h_quarantined_hours_excluded',0)}.",
      'Источники и все допущения: расчётный JSON. Промежуточные значения не округлялись; проценты и средние — взвешенные.'
    ]
    for i,line in enumerate(notes):
        # Keep a long exception list out of the artwork margins; full audit is in JSON.
        if len(line)>210:line=line[:207]+'…'
        parts.append(txt(42,1800+i*29,line,20,False,MUTED))
    parts.append('</svg>')

def individual(report,shop):
    data=report['shops'][str(shop)];place={7745:'Мосфильмовская, 74',8889:'Липовый Парк, 1',9107:'Николо-Хованская, 7'}[shop]
    p=base(f'ДС {shop} · {place} · ядро и потребность в курьерах','12 октября — 15 ноября 2026 · недели 910–914 · последняя полная неделя: 914')
    g=data['weighted']['groups'];p.append(txt(42,192,f"За 5 недель: ядро в штате {n(g['core']['staff_percent'])}% · в сменах {n(g['core']['shift_percent'])}% · дефицит штата к неделе 914: {data['staff_deficit']} чел.",29,True))
    if report.get('provisional'):p.append(txt(42,218,'Расчёт с исключениями по качеству данных; подробности — в audit.md',19,True,'#b52525'))
    weather_block(p,data,220,'good')
    p.append(txt(42,758,'Динамика ядра по неделям',30,True))
    from staffing.trend import svg_panel
    panel=base64.b64encode(svg_panel(report,shop).encode()).decode()
    p.append(f'<image x="40" y="780" width="3080" height="515" href="data:image/svg+xml;base64,{panel}"/>')
    performance(p,data,1340);footer(p,report,shop)
    return ''.join(p)

def comparison(report):
    p=base('ДС 8889 и ДС 9107 · сравнительный отчёт','12 октября — 15 ноября 2026 · недели 910–914 · взвешенные итоги по связке «склад — курьер — неделя»')
    labels=['Сумма недельной численности','Ядро / подработка в недельном штате','Ядро / подработка в сменах','Смена ядра / подработки','Заказов за смену: ядро / подработка','Заказов в час: ядро / подработка','Отклонение ядра в сменах от 70%']
    for i,label in enumerate(labels):p.append(txt(45,310+i*80,label,28))
    for i,(title,data) in enumerate([(f'ДС {s}',report['shops'][str(s)]['weighted']) for s in (8889,9107)]+[('Итого по двум ДС',report['combined'])]):
        x=1080+i*690;p.append(rect(x,205,660,620,['#fbe7e5','#d9eafa','#d8f2df'][i]));p.append(txt(x+22,260,title,34,True));g=data['groups']
        values=[str(data['staff_weeks']),n(g['core']['staff_percent'])+'% / '+n(g['side']['staff_percent'])+'%',n(g['core']['shift_percent'])+'% / '+n(g['side']['shift_percent'])+'%',
                duration(g['core']['hours_per_shift'])+' / '+duration(g['side']['hours_per_shift']),
                n(g['core']['orders_per_shift'])+' / '+n(g['side']['orders_per_shift']),n(g['core']['orders_per_hour'])+' / '+n(g['side']['orders_per_hour']),n(data['core_shift_deviation_pp'])+' п.п.']
        for j,value in enumerate(values):p.append(txt(x+22,310+j*80,value,30,True))
    p.append(txt(45,915,'Динамика по неделям · 8889 / 9107',34,True))
    heads=['Неделя','Штат','Ядро, чел.','Выход / день','Ядро в сменах','Заказов / день']
    xs=[50,430,950,1460,2020,2580]
    for x,label in zip(xs,heads):p.append(txt(x,975,label,29,True))
    for i in range(5):
        a=report['shops']['8889']['weeks'][i];b=report['shops']['9107']['weeks'][i];yy=1040+i*78
        p.append(rect(32,yy-42,3135,72,'#eaf0f8' if i%2==0 else 'white'))
        values=[str(910+i),f"{a['staff']} / {b['staff']}",f"{a['groups']['core']['staff']} / {b['groups']['core']['staff']}",
                n(a['daily_shifts'])+' / '+n(b['daily_shifts']),n(a['core_shift_percent'])+'% / '+n(b['core_shift_percent'])+'%',n(a['load_daily'])+' / '+n(b['load_daily'])]
        for x,value in zip(xs,values):p.append(txt(x,yy,value,29))
    for i,shop in enumerate((8889,9107)):
        d=report['shops'][str(shop)];x=50+i*1560;p.append(rect(x,1480,1510,230,'#d8f2df'))
        p.append(txt(x+20,1525,f'ДС {shop} · потребность по неделе 914',31,True))
        p.append(txt(x+20,1575,f"Штат сейчас / +10%: {d['need']['staff']} / {d['growth']['staff']} · дефицит сейчас: {d['staff_deficit']}",29))
        p.append(txt(x+20,1625,f"Выход 60% сейчас / +10%: {n(d['need']['good']['shifts'])} / {n(d['growth']['good']['shifts'])}",29))
        p.append(txt(x+20,1675,f"Отклонение доли ядра в смене от 70%: {n(d['shift_core_deviation_pp'])} п.п.",27))
    if report.get('provisional'):p.append(txt(45,180,'Есть исключения по качеству данных; подробности и чувствительность — в audit.md',24,True,'#a62c26'))
    footer(p,report);return ''.join(p)


def write_svgs(report,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    paths=[]
    for shop in map(int,report['shops']):
        path=directory/f'staffing-{shop}-910-914.svg';path.write_text(individual(report,shop));paths.append(path)
    if set(report['shops'])=={'8889','9107'}:
        path=directory/'staffing-comparison-910-914.svg';path.write_text(comparison(report));paths.append(path)
    return paths
