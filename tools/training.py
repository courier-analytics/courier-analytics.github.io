"""Intersect dated training records with the verified, date-specific private 1C roster."""
import csv,io,json,re,unicodedata
from datetime import datetime,time,date,timezone
from pathlib import Path
from urllib.request import urlopen
from calculate_metrics import metric,MOSCOW,timestamp
from prepare_openvpn import private_write

BASIS='onec_training_named_intersection'


def name_key(value):
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().replace('ё','е').split())


def parse(text):
    reader=csv.reader(io.StringIO(text.lstrip('\ufeff')))
    header=[v.strip() for v in next(reader,[])]
    if header.count('Отметка времени')!=1 or header.count('ФИО курьера')!=1:
        raise ValueError('Training columns not verified')
    ti,ni=header.index('Отметка времени'),header.index('ФИО курьера')
    records=[]
    for row in reader:
        if not any(v.strip() for v in row):continue
        if len(row)!=len(header):raise ValueError('Incomplete training row')
        name=' '.join(row[ni].split())
        if not name or len(name_key(name).split())<2:raise ValueError('Training name missing')
        trained=datetime.strptime(row[ti].strip(),'%d.%m.%Y %H:%M:%S').replace(tzinfo=MOSCOW)
        records.append({'name':name,'trained_at':trained.isoformat()})
    if not records:raise ValueError('Training source empty')
    return records


def evaluate(day,roster,records,now=None):
    now=now or datetime.now(timezone.utc)
    unavailable=lambda reason: {'metric':metric(reason=reason,basis=BASIS),'detail':{
        'aggregate':metric(reason=reason,basis=BASIS),'groups':[],'reconciled':False,
        'note':'Для сверки нужны доступная таблица обучения и полная база 1С на выбранную дату.'}}
    if not isinstance(roster,dict) or roster.get('verified') is not True or roster.get('date')!=day:
        return unavailable('assigned_roster_not_verified')
    raw_ids=roster.get('courier_ids')
    if not isinstance(raw_ids,list) or not raw_ids or any(not isinstance(i,str) or not i.isdigit() for i in raw_ids) or len(set(raw_ids))!=len(raw_ids):
        return unavailable('assigned_roster_not_verified')
    ids=set(raw_ids);names=roster.get('names',{})
    if not isinstance(names,dict) or any(not isinstance(names.get(i),str) or not name_key(names[i]) for i in ids):
        return unavailable('training_roster_names_missing')
    by_name={}
    for identity in ids:by_name.setdefault(name_key(names[identity]),set()).add(identity)
    cutoff=min(datetime.combine(date.fromisoformat(day),time.max,tzinfo=MOSCOW),now)
    earliest={}
    for record in records:
        trained=timestamp(record['trained_at'])
        if trained is None:raise ValueError('Training date invalid')
        if trained>cutoff:continue
        key=name_key(record['name'])
        if key not in earliest or trained<timestamp(earliest[key]['trained_at']):earliest[key]=record
    trained_ids={};unmatched=[]
    for key,record in earliest.items():
        candidates=by_name.get(key,set())
        if len(candidates)==1:
            identity=next(iter(candidates));trained_ids[identity]=record['trained_at']
        else:
            unmatched.append({'courier_id':'—','name':record['name'],'slots':[],
                'training_date':record['trained_at'],'match_status':'Неоднозначное ФИО в базе 1С' if candidates else 'Нет точного совпадения в активной базе 1С'})
    def people(identities):
        return [{'courier_id':i,'name':names[i],'slots':[],'training_date':trained_ids.get(i),
                 'match_status':'Обучение подтверждено' if i in trained_ids else 'Нет подтверждённой записи об обучении'}
                for i in sorted(identities,key=lambda i:(name_key(names[i]),i))]
    aggregate=metric(len(trained_ids),len(ids),basis=BASIS)
    groups=[{'title':'Обучены к выбранной дате','count':len(trained_ids),'couriers':people(set(trained_ids))},
        {'title':'В базе 1С — обучение не подтверждено','count':len(ids-set(trained_ids)),'couriers':people(ids-set(trained_ids))},
        {'title':'Записи таблицы без однозначного совпадения в активной базе','count':len(unmatched),'couriers':unmatched}]
    return {'metric':aggregate,'detail':{'aggregate':aggregate,'groups':groups,'reconciled':True,
        'note':'Каждая строка таблицы считается фактом обучения по отметке времени. Оценки знаний не ограничивают расчёт. '
               'Сверка по полному ФИО без учёта регистра, лишних пробелов и различия е/ё. Опечатки, сокращения и неоднозначные совпадения не угадываются. '
               'В процент входят только курьеры подтверждённой базы 1С на выбранную дату; повторное обучение не увеличивает число курьеров.'}}


def collect(day,roster,config,private,now=None):
    document=config['spreadsheet_id'];gid=str(config['gid'])
    if not re.fullmatch(r'[A-Za-z0-9_-]+',document) or not gid.isdigit():raise ValueError('Training source configuration invalid')
    try:
        url='https://docs.google.com/spreadsheets/d/'+document+'/export?format=csv&gid='+gid
        with urlopen(url,timeout=20) as response:
            if response.status!=200 or 'text/csv' not in response.headers.get('Content-Type',''):
                raise ValueError('Training CSV unavailable')
            raw=response.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('Training source too large')
        text=raw.decode('utf-8-sig');records=parse(text)
        result=evaluate(day,roster,records,now)
        folder=Path(private)/'training';folder.mkdir(parents=True,exist_ok=True,mode=0o700);folder.chmod(0o700)
        private_write(folder/'latest.csv',text)
        result['detail']['source_observed_at']=(now or datetime.now(timezone.utc)).isoformat()
        return result
    except (OSError,ValueError,KeyError,TypeError,csv.Error):
        failed=metric(reason='training_source_unavailable',basis=BASIS)
        return {'metric':failed,'detail':{'aggregate':failed,'groups':[],'reconciled':False,
            'note':'Таблицу обучения не удалось получить или проверить. Отсутствие данных не считается нулём.'}}


def configured(day,roster,private,config_path=Path('/etc/courier-analytics/training.json')):
    try:
        if not config_path.exists():return None
        config=json.loads(config_path.read_text())
        start=date.fromisoformat(config['start_date']).isoformat()
        if day<start:return None
        return collect(day,roster,config,private)
    except (OSError,ValueError,KeyError,TypeError):
        failed=metric(reason='training_source_unavailable',basis=BASIS)
        return {'metric':failed,'detail':{'aggregate':failed,'groups':[],'reconciled':False,
            'note':'Источник обучения не настроен или недоступен. Другие показатели обновляются независимо.'}}
