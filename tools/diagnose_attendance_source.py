"""Read-only source diagnosis: no private response values or tokens printed."""
import json
from pathlib import Path
from proxy_config import configured_proxy
from enrich_slots import api_get
from verify_server_proxy import network_probe,error_code
if __name__=='__main__':
 proxy=configured_proxy()
 print('Network:',json.dumps(network_probe(proxy)),flush=True)
 try:
  token=json.loads(Path('/root/curator-session.json').read_text())['token']
  for endpoint in ('/v1/shops','/v1/clusters'):
   api_get(endpoint,token,proxy)
   print('Authenticated source read:',endpoint,'passed',flush=True)
 except (RuntimeError,ValueError,OSError,KeyError,TypeError) as error:
  print('Source failure:',error_code(error),flush=True)
  raise SystemExit(1)
