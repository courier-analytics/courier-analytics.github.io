"""Validate the existing 1C typed export, install the loader, and queue dashboard refresh."""
import json
import os
import shutil
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from typed_roster_8889 import SOURCE,normalize,TZ

def main():
    if os.geteuid()!=0:raise SystemExit('Run on the VPS as root')
    now=datetime.now(timezone.utc)
    roster=normalize(json.loads(SOURCE.read_text()),now.astimezone(TZ).date().isoformat(),now)
    print('Verified DS8889 denominator:',roster['count'],'couriers; snapshot:',roster['observed_at'],flush=True)
    config=json.loads(Path('/etc/courier-dashboard/settings.json').read_text())
    site=Path(config['site_root'])
    source=Path(__file__).resolve().parents[1]/'dashboard-data.js'
    target=site/'dashboard-data.js'
    backup=Path('/opt/courier-analytics/private')/('8889-metric-install-'+now.strftime('%Y%m%dT%H%M%S%f'))
    backup.mkdir(mode=0o700,parents=True)
    if target.exists():shutil.copy2(target,backup/'dashboard-data.js')
    if source.resolve()!=target.resolve():
        temporary=target.with_name('.dashboard-data.js-8889')
        shutil.copyfile(source,temporary);temporary.chmod(0o644);os.replace(temporary,target)
    subprocess.run(['systemctl','start','--no-block','courier-refresh.service'],check=True)
    print('Typed roster calculation enabled. Dashboard refresh queued; inspect courier-refresh.service journal.',flush=True)
if __name__=='__main__':main()
