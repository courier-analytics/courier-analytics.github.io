"""Render installed dashboard assets against configured feeds without login or network."""
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote
from playwright.sync_api import sync_playwright

def main():
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
        page.goto('http://dashboard.test/9107.html',wait_until='networkidle')
        page.wait_for_timeout(1500)
        output={'page_errors':errors,'requests':requests,
                'status':page.locator('#dataStatus').inner_text() if page.locator('#dataStatus').count() else 'status_element_missing',
                'first_metric':page.locator('#metricsBody tr').nth(1).inner_text() if page.locator('#metricsBody tr').count()>1 else 'metric_rows_missing'}
        print(json.dumps(output,ensure_ascii=False,indent=2))
        browser.close()
if __name__=='__main__':main()
