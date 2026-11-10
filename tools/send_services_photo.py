"""Send an explicitly requested report image to the configured test group."""
import argparse,json,re,secrets,urllib.request,urllib.error
from pathlib import Path

def send(photo):
    root=Path('/etc/superset-telegram')
    token=json.loads((root/'telegram.json').read_text())['token']
    chat=json.loads((root/'test-group.json').read_text())['chat_id']
    if chat!=-1004427986473:raise ValueError('Unexpected test group')
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{30,}',token):raise ValueError('Invalid token')
    image=Path(photo).read_bytes()
    if not image.startswith(b'\x89PNG\r\n\x1a\n') or len(image)>9_000_000:raise ValueError('Invalid PNG')
    boundary='report'+secrets.token_hex(16)
    parts=[]
    for key,value in {'chat_id':str(chat),'caption':'Тестовый отчёт · ДС 9107 · 09.11.2026, полные сутки. Пять показателей, включая C2E — среднее время заказа по формуле Superset; прочерки — данные ещё не подключены.'}.items():
        parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
    parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="photo"; filename="report.png"\r\nContent-Type: image/png\r\n\r\n').encode()+image+b'\r\n')
    parts.append(('--'+boundary+'--\r\n').encode())
    request=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendPhoto',data=b''.join(parts),headers={'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
    opener=urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request,timeout=45) as response:result=json.load(response)
    except urllib.error.HTTPError as error:raise RuntimeError('Telegram HTTP '+str(error.code)) from None
    except Exception:raise RuntimeError('Delivery status unknown. Check group before retrying.') from None
    if not result.get('ok'):raise RuntimeError('Telegram did not confirm delivery')
    print('Photo sent. Message ID:',result['result']['message_id'])
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--photo',type=Path,required=True);a=p.parse_args()
    try:send(a.photo)
    except (ValueError,OSError,KeyError,RuntimeError) as error:
        raise SystemExit(str(error) if isinstance(error,RuntimeError) else 'Invalid local image or private configuration')
