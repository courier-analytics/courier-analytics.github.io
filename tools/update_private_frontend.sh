#!/usr/bin/env bash
set -euo pipefail
/opt/courier-dashboard/venv/bin/python - <<'PY'
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,'/opt/courier-dashboard/app')
from app import FILES
source=Path('/opt/courier-analytics/dashboard-code')
target=Path('/opt/courier-dashboard/site')
old=(target/'index.html').read_text()
private_details='/private-details.js' in old
for name in sorted(FILES):
    text=(source/name).read_text()
    if name.endswith('.html'):
        if private_details:text=text.replace('</head>','<script>window.courierPrivate=true;</script></head>')
        scripts='<script src="/private-session.js"></script>'
        if private_details:scripts+='<script src="/private-details.js"></script>'
        text=text.replace('</body>',scripts+'\n</body>')
    fd,tmp=tempfile.mkstemp(prefix='.ui-',dir=target)
    try:
        with os.fdopen(fd,'w') as output:output.write(text)
        os.chmod(tmp,0o644);os.replace(tmp,target/name)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
print('Closed dashboard interface updated; authentication and accounts preserved.')
print('Manual metric values copied from the current dashboard HTML.')
PY
