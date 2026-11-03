import importlib.util,json,re,sys,tempfile,unittest,sqlite3
from pathlib import Path

@unittest.skipUnless(importlib.util.find_spec('flask'),'Optional private web dependencies')
class PrivateDashboardTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/private_web'))
        from app import create_app
        from werkzeug.security import generate_password_hash
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'site').mkdir();(self.root/'data').mkdir()
        (self.root/'site/index.html').write_text('PRIVATE_DASHBOARD')
        (self.root/'site/private-session.js').write_text('logout UI')
        (self.root/'data/dashboard.json').write_text('{"records":[]}')
        self.userfile=self.root/'users.json';self.password='valid-long-password'
        self.userfile.write_text(json.dumps({'max':generate_password_hash(self.password)}))
        self.app=create_app({'secret':'test-secret'*8,'host':'test.example','users':str(self.userfile),'database':str(self.root/'auth.db'),'site_root':str(self.root/'site'),'data_root':str(self.root/'data')})
        self.app.testing=True;self.client=self.app.test_client()
    def tearDown(self):self.temp.cleanup()
    def get(self,path,**kw):return self.client.get(path,base_url='https://test.example',**kw)
    def post(self,path,**kw):return self.client.post(path,base_url='https://test.example',**kw)
    def token(self):return re.search('name="csrf" value="([^"]+)"',self.get('/login').text).group(1)
    def login(self,next='/'):return self.post('/login',data={'csrf':self.token(),'username':'max','password':self.password,'next':next})
    def test_pages_and_json_cannot_be_accessed_without_login(self):
        self.assertEqual(self.get('/').status_code,302)
        self.assertEqual(self.get('/data/dashboard.json').status_code,401)
        self.assertEqual(self.get('/api/session').status_code,401)
        self.assertNotIn('PRIVATE_DASHBOARD',self.get('/').text)
        self.assertEqual(self.client.get('/login',base_url='https://evil.example').status_code,400)
        self.assertEqual(self.client.get('/login',base_url='http://test.example').status_code,400)
    def test_login_secure_cookie_and_protected_allowlist(self):
        response=self.login();self.assertEqual(response.status_code,302)
        cookie=response.headers['Set-Cookie']
        for flag in ('Secure','HttpOnly','SameSite=Lax','Path=/'):self.assertIn(flag,cookie)
        with self.get('/') as page:self.assertEqual(page.text,'PRIVATE_DASHBOARD')
        with self.get('/data/dashboard.json') as page:self.assertEqual(page.status_code,200)
        with self.get('/private-session.js') as page:self.assertEqual(page.status_code,200)
        for path in ['/settings.json','/tools/private_web/app.py','/data/../users.json']:
            self.assertEqual(self.get(path).status_code,404)
        with self.get('/') as page:self.assertIn('no-store',page.headers['Cache-Control'])
    def test_csrf_required_and_redirects_remain_local(self):
        self.assertEqual(self.post('/login',data={'username':'max','password':self.password}).status_code,400)
        self.assertEqual(self.login('https://evil.example').headers['Location'],'/')
        self.assertEqual(self.post('/logout',data={'csrf':'wrong'}).status_code,400)
    def test_logout_revokes_replayed_cookie(self):
        self.login();old=self.client.get_cookie('__Host-courier_session',domain='test.example').value
        csrf=self.get('/api/session').json['csrf']
        self.assertEqual(self.post('/logout',headers={'X-CSRF-Token':csrf}).status_code,302)
        self.client.set_cookie('__Host-courier_session',old,domain='test.example')
        self.assertEqual(self.get('/api/session').status_code,401)
    def test_password_change_revokes_existing_session(self):
        self.login();self.userfile.write_text('{}')
        self.assertEqual(self.get('/api/session').status_code,401)
    def test_five_wrong_password_attempts_are_rate_limited(self):
        token=self.token()
        for i in range(5):
            response=self.post('/login',data={'csrf':token,'username':'max','password':'wrong'})
            self.assertEqual(response.status_code,401)
        self.assertEqual(self.post('/login',data={'csrf':token,'username':'max','password':self.password}).status_code,429)
    def test_expired_server_session_is_rejected(self):
        self.login()
        with sqlite3.connect(self.root/'auth.db') as db:db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.get('/data/dashboard.json').status_code,401)
