"""HTTP integration check of the browser OIDC flow, without logging secrets."""
import http.cookiejar
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.request
import urllib.parse
import urllib.error

values=dict(line.split('=',1) for line in (Path(__file__).resolve().parent.parent/'.env').read_text().splitlines() if line and not line.startswith('#'))
class LoginForm(HTMLParser):
    def __init__(self):super().__init__();self.action=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='form' and attrs.get('id')=='kc-form-login':self.action=attrs['action']
jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
with client.open('http://localhost:8080/auth/login') as r:html=r.read().decode()
form=LoginForm();form.feed(html)
# Browsers allow Secure cookies on localhost; urllib does not.
# This accommodation is limited to the local HTTP test client.
for cookie in jar:
    if cookie.domain=='localhost.local':cookie.secure=False
assert form.action,'Keycloak login form missing'
body=urllib.parse.urlencode({'username':'requester','password':values['REQUESTER_PASSWORD'],'credentialId':''}).encode()
try:
    with client.open(urllib.request.Request(form.action,body,{'Content-Type':'application/x-www-form-urlencoded'})) as r:assert r.url=='http://localhost:8080/'
except urllib.error.HTTPError as e:
    import re
    html=e.read().decode()
    print('Login error:',e.code,'at',urllib.parse.urlsplit(e.url).path)
    for tag in ['title','h1']:
        for value in re.findall('<'+tag+r'[^>]*>(.*?)</'+tag+'>',html,re.S):print(re.sub('<[^>]+>','',value).strip())
    raise SystemExit(1)
with client.open('http://localhost:8080/api/me') as r:me=json.load(r)
assert me['actor']['username']=='requester' and me['csrf']
print('OIDC authorization code + PKCE callback created a verified requester session.')
headers={'Content-Type':'application/json'}
try:client.open(urllib.request.Request('http://localhost:8080/api/workshop/run',b'{"lab":"expense_read"}',headers));raise AssertionError('Missing CSRF accepted')
except urllib.error.HTTPError as e:assert e.code==403
headers['X-CSRF-Token']=me['csrf']
with client.open(urllib.request.Request('http://localhost:8080/api/workshop/run',b'{"lab":"expense_read"}',headers)) as r:assert json.load(r)['status']=='ok'
with client.open(urllib.request.Request('http://localhost:8080/auth/logout',b'{}',headers)) as r:assert r.status==200
with client.open('http://localhost:8080/api/me') as r:assert json.load(r)['actor'] is None
print('Session CSRF protection and logout verified.')
