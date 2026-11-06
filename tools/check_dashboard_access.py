"""Run on the user's Mac with Happ disabled. No credentials or local configuration changes."""
import argparse,ipaddress,json,re,socket,ssl,time
from datetime import datetime,timezone

HOST='courier-7745.147.90.10.158.sslip.io'
IP='147.90.10.158'
TIMEOUT=6


def probe(name,operation):
    start=time.monotonic()
    try:result={'ok':True,**operation()}
    except (OSError,ValueError) as error:
        result={'ok':False,'error':type(error).__name__,'message':str(error)}
    result.update(check=name,seconds=round(time.monotonic()-start,2))
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return result


def dns():
    addresses=sorted({item[4][0] for item in socket.getaddrinfo(HOST,443,type=socket.SOCK_STREAM)})
    return {'addresses':addresses,'expected_ipv4_present':IP in addresses}


def tcp(port):
    with socket.create_connection((IP,port),TIMEOUT):return {'port':port,'connected':True}


def http(tls=False,fixed_ip=True,tls12=False):
    port=443 if tls else 80
    address=IP if fixed_ip else HOST
    with socket.create_connection((address,port),TIMEOUT) as raw:
        connection=raw
        if tls:
            context=ssl.create_default_context()
            if tls12:context.maximum_version=ssl.TLSVersion.TLSv1_2
            connection=context.wrap_socket(raw,server_hostname=HOST)
        try:
            connection.sendall(('HEAD /login HTTP/1.1\r\nHost: '+HOST+'\r\nConnection: close\r\n\r\n').encode('ascii'))
            response=b''
            while b'\r\n' not in response and len(response)<1024:
                chunk=connection.recv(1024)
                if not chunk:break
                response+=chunk
            status=response.split(b'\r\n')[0].decode('ascii','replace')
            if not status.startswith('HTTP/'):raise ValueError('No HTTP response')
            code=int(status.split()[1])
            return {'status':status,'http_status':code,'login_available':code==200,
                    'tls':connection.version() if tls else None,'fixed_ipv4':fixed_ip}
        finally:
            if connection is not raw:connection.close()


def main():
    global HOST,IP
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default=HOST,help='Dashboard hostname without scheme or path')
    parser.add_argument('--ip',help='Explicit public IPv4; if omitted, resolve the supplied hostname')
    args=parser.parse_args()
    if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',args.host) or len(args.host)>253:
        parser.error('Pass a lowercase DNS hostname without scheme, path or port.')
    HOST=args.host
    try:
        IP=str(ipaddress.IPv4Address(args.ip or (IP if HOST=='courier-7745.147.90.10.158.sslip.io' else socket.gethostbyname(HOST))))
        if not ipaddress.IPv4Address(IP).is_global:raise ValueError('Public IPv4 required')
    except (OSError,ValueError) as error:
        parser.error('Could not select a public IPv4: '+str(error))
    print('Проверка доступа к дашборду. Happ должен быть выключен. Пароли не нужны.',flush=True)
    print(json.dumps({'observed_at':datetime.now(timezone.utc).isoformat(),'host':HOST,'ip':IP}),flush=True)
    results={}
    results['dns']=probe('dns',dns)
    for port in (80,443):results['tcp'+str(port)]=probe('tcp_'+str(port),lambda port=port:tcp(port))
    results['http']=probe('http_fixed_ipv4',lambda:http())
    results['https']=probe('https_fixed_ipv4',lambda:http(tls=True))
    results['hostname']=probe('https_system_dns',lambda:http(tls=True,fixed_ip=False))
    if results['tcp443']['ok'] and not results['https']['ok']:
        results['tls12']=probe('https_fixed_ipv4_tls12',lambda:http(tls=True,tls12=True))
    if results['https']['ok'] and not results['hostname']['ok']:
        print('Итог: HTTPS по IPv4 работает; проблема в разрешении имени или выбранном DNS-адресе.')
    elif not results['tcp80']['ok'] and not results['tcp443']['ok']:
        print('Итог: TCP-соединение с IP не установлено. Нужна проверка маршрута и фильтрации на сервере/у провайдера.')
    elif results['tcp443']['ok'] and not results['https']['ok']:
        print('Итог: TCP 443 доступен, но HTTPS не завершается. Проверьте результат TLS и настройки сервера.')
    elif results['hostname']['ok'] and not results['hostname'].get('login_available'):
        print('Итог: HTTPS-соединение установлено, но страница входа вернула '+results['hostname']['status']+'. Нужно проверить конфигурацию сайта.')
    elif results['hostname']['ok']:
        print('Итог: HTTPS работает из Терминала; нужно проверить настройки браузера и системного прокси.')
    else:print('Итог: передайте строки проверки для разбора; причина пока не определена.')


if __name__=='__main__':main()
