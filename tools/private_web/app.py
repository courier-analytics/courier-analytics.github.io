"""Authenticated read-only dashboard; credentials and rate state stay on the VPS."""
import argparse
from datetime import timedelta
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit

from flask import Flask, abort, g, jsonify, redirect, render_template_string, request, send_file, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

FILES = {'index.html','7745.html','4747.html','8092.html','dashboard-data.js',
         'dashboard-trends.js','dashboard-trends.css','metric-details.js'}
FEEDS = {'dashboard.json','medical-books.json'}
EXTRA_FILES = {'private-session.js','private-details.js'}
PAGE = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Вход — Курьерский дашборд</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100dvh;display:grid;place-items:center;padding:24px;background:#f1f5f9;color:#18364b;font:16px/1.5 system-ui}main{background:white;border:1px solid #e2e8f0;border-radius:20px;padding:32px;width:min(100%,390px);box-shadow:0 12px 40px #18364b12}h1{font-size:24px;margin:0 0 8px}p{color:#64748b;margin:0 0 22px}label{display:block;margin:16px 0 6px}input,button{font:inherit;width:100%;padding:11px 12px;border-radius:9px;border:1px solid #cbd5e1}input:focus{outline:2px solid #2563eb;outline-offset:1px}button{margin-top:22px;background:#245fd3;color:white;border:0;cursor:pointer}.error{color:#a32626;background:#fff1f2;border-radius:8px;padding:10px;margin:18px 0 0}</style>
<main><h1>Вход в дашборд</h1><p>Показатели курьерской службы</p>
<form method="post" action="{{url_for('login')}}"><input type="hidden" name="csrf" value="{{csrf}}"><input type="hidden" name="next" value="{{next_path}}">
<label for="username">Логин</label><input id="username" name="username" autocomplete="username" maxlength="80" required autofocus>
<label for="password">Пароль</label><input id="password" name="password" type="password" autocomplete="current-password" maxlength="256" required>
{% if error %}<p class="error" role="alert">{{error}}</p>{% endif %}<button type="submit">Войти</button></form></main></html>'''


def write_private(path, data):
    path=Path(path);fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        if path.exists():
            previous=path.stat()
            os.fchmod(fd,previous.st_mode & 0o777)
            os.fchown(fd,previous.st_uid,previous.st_gid)
        with os.fdopen(fd,'w') as f:json.dump(data,f)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def safe_next(value):
    value=value or '/'
    try:parsed=urlsplit(value)
    except ValueError:return '/'
    if parsed.scheme or parsed.netloc or not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c)<32 for c in value):
        return '/'
    return value


def create_app(config=None):
    settings=Path(os.environ.get('COURIER_WEB_SETTINGS','/etc/courier-dashboard/settings.json'))
    values=config if config is not None else json.loads(settings.read_text())
    app=Flask(__name__,static_folder=None)
    app.config.update(SECRET_KEY=values['secret'],SESSION_COOKIE_NAME='__Host-courier_session',
        SESSION_COOKIE_SECURE=True,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_PATH='/',PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False,MAX_CONTENT_LENGTH=8192)
    app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)
    users_path=Path(values['users']);db_path=Path(values['database'])
    dummy=generate_password_hash(secrets.token_urlsafe(32),method='scrypt')

    def users():return json.loads(users_path.read_text())
    def connection():
        if 'db' not in g:
            g.db=sqlite3.connect(db_path,timeout=10)
            g.db.execute('CREATE TABLE IF NOT EXISTS attempts (key TEXT, at REAL)')
            g.db.execute('CREATE INDEX IF NOT EXISTS attempts_key ON attempts(key,at)')
            g.db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user TEXT, version TEXT, expires REAL)')
        return g.db
    def rate_key():return hmac.new(values['secret'].encode(),(request.remote_addr or '').encode(),hashlib.sha256).hexdigest()
    def current_user():
        token=session.get('token')
        if not isinstance(token,str):return None
        record=connection().execute('SELECT user,version,expires FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not record or record[2]<time.time():return None
        password=users().get(record[0])
        if not password or not hmac.compare_digest(record[1],hashlib.sha256(password.encode()).hexdigest()):return None
        return record[0]
    def csrf():
        if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(32)
        return session['csrf']
    def valid_csrf():
        supplied=request.form.get('csrf') or request.headers.get('X-CSRF-Token','')
        return bool(session.get('csrf')) and hmac.compare_digest(supplied.encode(),session['csrf'].encode())

    @app.teardown_appcontext
    def close_db(error=None):
        db=g.pop('db',None)
        if db is not None:db.close()

    @app.before_request
    def authenticate():
        if request.host.lower() != values['host'].lower():abort(400)
        if not request.is_secure:abort(400)
        if request.path=='/login':return None
        g.user=current_user()
        if not g.user:
            if request.path.startswith(('/api/','/data/')):return jsonify(error='authentication_required'),401
            return redirect(url_for('login',next=safe_next(request.full_path.rstrip('?'))))

    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store, private'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        return response

    @app.route('/login',methods=['GET','POST'])
    def login():
        error=None;status=200;next_path=safe_next(request.values.get('next'))
        if request.method=='POST':
            if not valid_csrf():abort(400)
            db=connection();now=time.time();key=rate_key()
            # One short transaction keeps limits consistent across Gunicorn workers.
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE at<?',(now-900,))
            count=db.execute('SELECT COUNT(*) FROM attempts WHERE key=?',(key,)).fetchone()[0]
            if count>=5:
                db.commit();error='Слишком много попыток. Попробуйте через 15 минут.';status=429
            else:
                db.execute('INSERT INTO attempts VALUES (?,?)',(key,now));db.commit()
                username=request.form.get('username','');password=request.form.get('password','')
                saved=users().get(username)
                valid=check_password_hash(saved or dummy,password)
                if saved and valid:
                    previous=session.get('token')
                    if isinstance(previous,str):db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(previous.encode()).hexdigest(),))
                    token=secrets.token_urlsafe(32)
                    db.execute('DELETE FROM sessions WHERE expires<?',(now,))
                    db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),username,hashlib.sha256(saved.encode()).hexdigest(),now+28800))
                    db.execute('DELETE FROM attempts WHERE key=?',(key,));db.commit()
                    session.clear();session.permanent=True;session['token']=token;csrf()
                    return redirect(next_path)
                error='Неверный логин или пароль.';status=401
        return render_template_string(PAGE,csrf=csrf(),next_path=next_path,error=error),status

    @app.get('/api/session')
    def session_info():return jsonify(username=g.user,csrf=csrf())

    @app.get('/api/details/<int:shop>/<day>/<key>')
    def metric_details(shop,day,key):
        from datetime import date
        try:
            if date.fromisoformat(day).isoformat()!=day:abort(400)
        except ValueError:abort(400)
        if shop not in (7745,5818,4747,8092) or key not in ('shift_marked','slot_fill','planned_attendance','planned_late','unplanned_work','planned_completion','medical'):abort(404)
        if key=='medical':return jsonify(available=False,note='Персональная выгрузка медицинских книжек пока не подключена. Доступны только общие количества.')
        path=Path(values.get('details_root','/opt/courier-dashboard/details'))/f'{day}-{shop}.json'
        if not path.is_file():return jsonify(available=False,note='Персональная детализация за эту дату ещё не сохранена.'),404
        data=json.loads(path.read_text())
        if data.get('kind')!='courier_metric_details' or data.get('date')!=day or data.get('shop_id')!=shop:abort(500)
        if key not in data.get('metrics',{}):abort(404)
        return jsonify(available=True,date=day,shop_id=shop,generated_at=data['generated_at'],detail=data['metrics'][key])

    @app.post('/logout')
    def logout():
        if not valid_csrf():abort(400)
        token=session.get('token','')
        db=connection();db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),));db.commit()
        session.clear();return redirect(url_for('login'))

    @app.get('/')
    def index():return site_file('index.html')
    @app.get('/<path:name>')
    def site_file(name):
        if name.startswith('data/') and name[5:] in FEEDS:
            path=Path(values['data_root'])/name[5:]
        elif name in FILES | EXTRA_FILES:path=Path(values['site_root'])/name
        else:abort(404)
        if not path.is_file():abort(404)
        return send_file(path,conditional=False,max_age=0)
    return app


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--add-user',action='store_true');args=parser.parse_args()
    if not args.add_user:parser.error('Use Gunicorn create_app() to run the server')
    settings=json.loads(Path(os.environ.get('COURIER_WEB_SETTINGS','/etc/courier-dashboard/settings.json')).read_text())
    username=input('Логин пользователя: ').strip()
    if not username or len(username)>80 or any(ord(c)<33 for c in username):raise SystemExit('Некорректный логин')
    password=getpass.getpass('Пароль (не менее 12 символов): ')
    if len(password)<12 or len(password)>256:raise SystemExit('Требуется пароль длиной 12–256 символов')
    if password!=getpass.getpass('Повторите пароль: '):raise SystemExit('Пароли не совпали')
    path=Path(settings['users']);data=json.loads(path.read_text()) if path.exists() else {}
    data[username]=generate_password_hash(password,method='scrypt');write_private(path,data)
    print('Пользователь сохранён. Пароль не выводится и не хранится открытым текстом.')

if __name__=='__main__':main()
