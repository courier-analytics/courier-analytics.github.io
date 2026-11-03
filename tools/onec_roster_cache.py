"""Private verified 1C roster snapshots, retained by Moscow report date."""
from datetime import datetime, timezone
import json
from pathlib import Path
import stat
from zoneinfo import ZoneInfo
from prepare_openvpn import private_write

BASIS = 'onec_accessible_nonmobile_unique_couriers'
MOSCOW = ZoneInfo('Europe/Moscow')


def save(native, filters, directory, now=None):
    now = now or datetime.now(timezone.utc)
    ids = native.get('courier_ids')
    if (native.get('verified') is not True or filters.get('filters_verified') is not True or
            not isinstance(ids, list) or not ids or any(not isinstance(i,str) or not i.isdigit() for i in ids) or
            len(set(ids)) != len(ids) or native.get('count') != len(ids)):
        raise ValueError('1C roster snapshot not verified')
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    snapshot = {'shop_id':7745,'verified':True,'basis':BASIS,
                'source':'native_all_filtered_rows_id_only_text_output',
                'observed_at':now.isoformat(),'date':now.astimezone(MOSCOW).date().isoformat(),
                'courier_ids':sorted(ids),'count':len(ids),'filters_verified':True}
    snapshot['names']={i:n for i,n in native.get('names',{}).items() if i in ids and isinstance(n,str)}
    archive_latest(directory, now)
    archive = directory/'by-date'
    archive.mkdir(exist_ok=True, mode=0o700); archive.chmod(0o700)
    private_write(archive/(snapshot['date']+'-7745.json'),json.dumps(snapshot,ensure_ascii=False))
    private_write(directory/'7745.json',json.dumps(snapshot,ensure_ascii=False))
    return len(ids)


def load(path, day, now=None):
    now = now or datetime.now(timezone.utc)
    path = Path(path); info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError('1C roster snapshot permissions invalid')
    data=json.loads(path.read_text()); observed=datetime.fromisoformat(data['observed_at'])
    ids=data.get('courier_ids')
    if (observed.tzinfo is None or observed > now or
            data.get('date') != day or observed.astimezone(MOSCOW).date().isoformat() != day or
            (day == now.astimezone(MOSCOW).date().isoformat() and (now-observed).total_seconds() > 7200) or
            data.get('shop_id') != 7745 or data.get('verified') is not True or
            data.get('filters_verified') is not True or data.get('basis') != BASIS or
            data.get('source') != 'native_all_filtered_rows_id_only_text_output' or
            not isinstance(ids,list) or not ids or any(not isinstance(i,str) or not i.isdigit() for i in ids) or
            len(set(ids)) != len(ids) or data.get('count') != len(ids)):
        raise ValueError('1C roster snapshot stale or invalid')
    return data


def archive_latest(directory, now=None):
    """Migrate a verified previous-day latest snapshot before a new collection replaces it."""
    directory=Path(directory)
    path=directory/'7745.json'
    if not path.exists(): return
    try:
        day=json.loads(path.read_text())['date']
        data=load(path,day,now)
    except (OSError,ValueError,KeyError,TypeError):
        return
    archive=directory/'by-date'
    archive.mkdir(exist_ok=True,mode=0o700); archive.chmod(0o700)
    target=archive/(day+'-7745.json')
    if target.exists():
        previous=load(target,day,now)
        if previous['observed_at'] >= data['observed_at']: return
    private_write(target,json.dumps(data,ensure_ascii=False))


def load_for_day(directory, day, now=None):
    directory=Path(directory)
    # Latest takes precedence for today; a saved archive cannot mask a corrupt latest file.
    latest=directory/'7745.json'
    if latest.exists() and json.loads(latest.read_text()).get('date') == day:
        return load(latest,day,now)
    return load(directory/'by-date'/(day+'-7745.json'),day,now)
