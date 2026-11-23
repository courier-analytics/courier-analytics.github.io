"""Private periodic service health snapshot; never sends messages or edits 1C."""
import json
from datetime import datetime,timezone
from pathlib import Path
from service_isolation_audit import inventory
from prepare_openvpn import private_write
if __name__=='__main__':
 units=inventory();failed=[u['Id'] for u in units if u.get('ActiveState')=='failed']
 report={'checked_at':datetime.now(timezone.utc).isoformat(),'failed_units':failed,'units':units}
 private_write(Path('/opt/courier-analytics/private/service-health.json'),json.dumps(report,ensure_ascii=False,indent=2))
 print('Service health: failed='+str(len(failed)))
 for name in failed:print('Failed unit: '+name)
