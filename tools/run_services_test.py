"""Fetch, render and explicitly send the dated DS9107 pilot entirely on the VPS."""
import argparse,json,subprocess,sys,time,os,math
from pathlib import Path
from services_report_render import render
from send_services_photo import send

def run(refresh=True,send_report=False):
    folder=Path('/opt/courier-analytics/private')
    source=folder/'services-report-pilot.json'
    if refresh:
        started=time.time()
        subprocess.run([sys.executable,str(Path(__file__).with_name('probe_superset_vpn.py')),'--check-login','--inspect-datasets'],check=True,timeout=180)
        if not source.exists() or source.stat().st_mtime<started:raise ValueError('Fresh source was not saved')
    payload=json.loads(source.read_text())
    if payload.get('shop_id')!=9107 or payload.get('date')!='2026-11-09':raise ValueError('Unexpected pilot scope')
    if payload.get('source_dataset')!=3035:raise ValueError('C2E source must be refreshed')
    for sample in payload['samples']:
        for row in sample['rows']:
            value=row.get('avg_order_time')
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('C2E not confirmed')
    html=render(payload)
    from playwright.sync_api import sync_playwright
    target=folder/'services-test-9107-2026-11-09.png'
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1365,'height':550},device_scale_factor=1)
        page.route('**/*',lambda route:route.abort())
        page.set_content(html,wait_until='load')
        page.screenshot(path=str(target),full_page=True)
        browser.close()
    target.chmod(0o600)
    print('Report PNG generated privately on server.',flush=True)
    if send_report:send(target)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--send',action='store_true');parser.add_argument('--saved-source',action='store_true');args=parser.parse_args()
    os.umask(0o077)
    try:run(not args.saved_source,args.send)
    except Exception as error:
        print('Report failed; no automatic retry. Check the group before repeating. Error type: '+type(error).__name__,flush=True)
        raise SystemExit(1)
