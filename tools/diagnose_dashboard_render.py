"""Render installed dashboard assets against configured feeds without login or network."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
from playwright.sync_api import sync_playwright

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--shop',type=int,choices=(7745,8889,9107),default=9107)
    args=parser.parse_args()
    settings=json.loads(Path('/etc/courier-dashboard/settings.json').read_text())
    site=Path(settings['site_root']).resolve()
    data=Path(settings['data_root']).resolve()
    errors=[];requests=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=browser.new_context(service_workers='block')
        def serve(route):
            url=urlsplit(route.request.url)
            if url.hostname!='dashboard.test':return route.abort()
            name=unquote(url.path).lstrip('/')
            base=data if name.startswith('data/') else site
            relative=name[5:] if name.startswith('data/') else name
            path=(base/relative).resolve()
            if not path.is_relative_to(base) or path.suffix not in ('.html','.js','.css','.json') or not path.is_file():
                requests.append({'path':url.path,'status':404})
                return route.fulfill(status=404,body='Not found')
            requests.append({'path':url.path,'status':200})
            mime={'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json'}[path.suffix]
            route.fulfill(status=200,content_type=mime,body=path.read_bytes())
        context.route('**/*',serve)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)[:250]))
        page.goto('http://dashboard.test/'+str(args.shop)+'.html',wait_until='networkidle')
        page.wait_for_timeout(1500)
        feed=json.loads((data/'dashboard.json').read_text())
        own=sorted((r for r in feed['records'] if r['shop_id']==args.shop),key=lambda r:r['date'])
        source_summary=[{'date':r['date'],'metric':r.get('metrics',{}).get('shift_marked')} for r in own[-2:]]
        try:
            from typed_roster_8889 import normalize,SOURCE,TZ
            from datetime import datetime,timezone
            now=datetime.now(timezone.utc)
            roster=normalize(json.loads(SOURCE.read_text()),now.astimezone(TZ).date().isoformat(),now)
            roster_status={'verified':True,'count':roster['count'],'observed_at':roster['observed_at']}
        except (ValueError,KeyError,OSError,TypeError) as error:
            roster_status={'verified':False,'reason':str(error) if type(error) is ValueError else type(error).__name__}
        output={'shop':args.shop,'served_feed':source_summary,'typed_roster_8889':roster_status,'page_errors':errors,'requests':requests,
                'status':page.locator('#dataStatus').inner_text() if page.locator('#dataStatus').count() else 'status_element_missing',
                'first_metric':page.locator('#metricsBody tr').nth(1).inner_text() if page.locator('#metricsBody tr').count()>1 else 'metric_rows_missing'}
        print(json.dumps(output,ensure_ascii=False,indent=2))
        browser.close()
if __name__=='__main__':main()
