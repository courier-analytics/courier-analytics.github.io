"""Generate the three requested reports from a verified private export."""
import argparse
import gzip
import json
import os
import subprocess
import shutil
import sys
from pathlib import Path
from staffing.core import analyse, SHOPS
from staffing.render import write_svgs, W, H


def load(path):
    with gzip.open(path,'rt',encoding='utf-8') as f:data=json.load(f)
    if data.get('schema_version')!=1 or data.get('complete') is not True or data.get('period')!='2026-10-12..2026-11-15':
        raise ValueError('Unverified export or incorrect period')
    shops=[c['shop'] for c in data['checks']]
    if not shops or len(shops)!=len(set(shops)) or not set(shops)<={7745,8889,9107}:raise ValueError('Invalid shop coverage')
    if data.get('shops',shops)!=shops:raise ValueError('Requested shop coverage mismatch')
    if any(int(r['shopno']) not in shops for r in data['rows']):raise ValueError('Unexpected row scope')
    for c in data['checks']:
        actual=sum(int(r['shopno'])==c['shop'] for r in data['rows'])
        if not c['expected']==c['received']==c['after']==actual:raise ValueError('Export completeness check failed')
    return data


def rasterize(paths):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'],executable_path=shutil.which('chromium') or None)
        page=browser.new_page(viewport={'width':W,'height':H},device_scale_factor=1)
        page.route('**/*',lambda route:route.abort())
        for path in paths:
            page.set_content('<html><body style="margin:0">'+path.read_text()+'</body></html>',wait_until='load')
            page.evaluate('document.fonts.ready')
            page.screenshot(path=str(path.with_suffix('.png')))
        browser.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--collect',action='store_true')
    parser.add_argument('--input',type=Path,default=Path('/opt/courier-analytics/private/staffing-orders-910-914.json.gz'))
    parser.add_argument('--output',type=Path,default=Path('/opt/courier-analytics/private/staffing-report-910-914'))
    parser.add_argument('--svg-only',action='store_true')
    args=parser.parse_args();os.umask(0o077)
    if args.collect:
        subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('probe_superset_vpn.py')),
                        '--check-login','--collect-staffing'],check=True,timeout=640)
    data=load(args.input)
    report=analyse(data['rows'],shops=[c['shop'] for c in data['checks']]);report['source_audit']={k:v for k,v in data.items() if k!='rows'}
    args.output.mkdir(mode=0o700,parents=True,exist_ok=True)
    (args.output/'calculation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    paths=write_svgs(report,args.output)
    from staffing.trend import write_comparison
    write_comparison(report,args.output,svg_only=args.svg_only)
    if not args.svg_only:rasterize(paths)
    print('Reports written: '+str(args.output),flush=True)
    print('Exceptions: '+json.dumps(report['exclusions']),flush=True)

if __name__=='__main__':
    main()
