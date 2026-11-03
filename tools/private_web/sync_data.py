"""Copy validated public feeds into the authenticated site; preserve available data."""
import json,os,sys,tempfile
from pathlib import Path


def validated(payload,name):
    tools=Path('/opt/courier-analytics/dashboard-code/tools')
    if not tools.exists():tools=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(tools))
    if name=='medical-books.json':
        from medical_feed import merge
    else:
        from refresh_dashboard import merge_feed as merge
    return merge(None,payload)


def sync(sources,target):
    target=Path(target);result={}
    for name,paths in sources.items():
        data=None
        for path in paths:
            try:
                data=validated(json.loads(Path(path).read_text()),name)
                break
            except (OSError,ValueError,KeyError,TypeError):
                continue
        if data is None:
            if (target/name).is_file():
                result[name]='previous_copy_preserved';continue
            if name=='dashboard.json':
                raise ValueError('No valid slot feed available; installation stopped')
            # An empty optional feed means unavailable, never a made-up 0%.
            data={'schema_version':1,'records':[]}
            result[name]='optional_feed_unavailable'
        else:result[name]='updated'
        fd,tmp=tempfile.mkstemp(prefix='.'+name,dir=target)
        try:
            with os.fdopen(fd,'w') as output:json.dump(data,output,ensure_ascii=False)
            os.chmod(tmp,0o644);os.replace(tmp,target/name)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    return result


def sync_details(source,target):
    target=Path(target)
    if not target.is_dir():return 0
    count=0
    for path in Path(source).glob('????-??-??-*.json'):
        data=json.loads(path.read_text())
        if data.get('kind')!='courier_metric_details' or data.get('schema_version')!=1:
            continue
        if path.name!=f"{data.get('date')}-{data.get('shop_id')}.json":continue
        fd,tmp=tempfile.mkstemp(prefix='.detail-',dir=target)
        try:
            with os.fdopen(fd,'w') as output:json.dump(data,output,ensure_ascii=False)
            os.chmod(tmp,0o640);os.replace(tmp,target/path.name);count+=1
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    return count


def main():
    base=Path('/opt/courier-analytics')
    sources={
        'dashboard.json':[base/'current-site/data/dashboard.json',base/'publisher/data/dashboard.json',base/'dashboard-code/data/dashboard.json'],
        'medical-books.json':[base/'publisher/data/medical-books.json',base/'current-site/data/medical-books.json',base/'dashboard-code/data/medical-books.json']
    }
    print(json.dumps(sync(sources,Path('/opt/courier-dashboard/site/data'))))
    print('Private detail snapshots copied:',sync_details(base/'private/details',Path('/opt/courier-dashboard/details')))

if __name__=='__main__':main()
