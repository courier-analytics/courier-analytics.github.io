"""Copy only the two public aggregate feeds into the protected site's data directory."""
import json,os,tempfile
from pathlib import Path
source=Path('/opt/courier-analytics/current-site/data')
target=Path('/opt/courier-dashboard/site/data')
for name in ['dashboard.json','medical-books.json']:
    data=json.loads((source/name).read_text())
    if data.get('schema_version')!=1 or not isinstance(data.get('records'),list):
        raise ValueError('Invalid aggregate feed; protected copy preserved')
    fd,tmp=tempfile.mkstemp(prefix='.'+name,dir=target)
    try:
        with os.fdopen(fd,'w') as output:json.dump(data,output,ensure_ascii=False)
        os.chmod(tmp,0o644);os.replace(tmp,target/name)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
print('Protected aggregate copies updated.')
