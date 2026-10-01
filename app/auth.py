"""Local OIDC authorization code + PKCE, verified bearer tokens, server sessions."""
import hashlib
import json
import os
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path
import jwt

ISSUER=os.getenv('OIDC_ISSUER','http://localhost:8180/realms/micro')
INTERNAL=os.getenv('OIDC_INTERNAL_URL','http://keycloak:8080/realms/micro')
CLIENT=os.getenv('OIDC_CLIENT_ID','micro-app')
REDIRECT='http://localhost:8080/auth/callback'
JWKS=jwt.PyJWKClient(INTERNAL+'/protocol/openid-connect/certs',timeout=5)

@contextmanager
def store():
    path=Path(os.getenv('DATA_DIR','/data'));path.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path/'auth.sqlite') as c:
        c.execute('CREATE TABLE IF NOT EXISTS login (state TEXT PRIMARY KEY, verifier TEXT, nonce TEXT, expires REAL)')
        c.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, actor TEXT, csrf TEXT, expires REAL)')
        c.execute('DELETE FROM login WHERE expires<?',(time.time(),));c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
        yield c


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def cookies(headers):
    result=SimpleCookie()
    try:result.load(headers.get('Cookie',''))
    except Exception:return {}
    return {key:value.value for key,value in result.items()}


def verify(token):
    try:
        key=JWKS.get_signing_key_from_jwt(token).key
        return jwt.decode(token,key,algorithms=['RS256'],audience=CLIENT,issuer=ISSUER,options={'require':['exp','iat','sub']})
    except Exception as error:raise PermissionError('Invalid or expired identity token. Sign in again.') from error


def actor_from(claims):
    roles=claims.get('realm_access',{}).get('roles',[])
    return {'sub':claims['sub'],'username':claims.get('preferred_username','user'),'roles':[role for role in roles if role in ('requester','approver','administrator')]}


def identity(headers):
    authorization=headers.get('Authorization','')
    if authorization.startswith('Bearer '):return actor_from(verify(authorization[7:])),None
    sid=cookies(headers).get('micro_session')
    if not sid:return None,None
    with store() as c:row=c.execute('SELECT actor,csrf FROM sessions WHERE id=? AND expires>?',(digest(sid),time.time())).fetchone()
    return (json.loads(row[0]),row[1]) if row else (None,None)


def login():
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);nonce=secrets.token_urlsafe(32)
    import base64
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    with store() as c:c.execute('INSERT INTO login VALUES (?,?,?,?)',(digest(state),verifier,nonce,time.time()+300))
    url=ISSUER+'/protocol/openid-connect/auth?'+urllib.parse.urlencode({'client_id':CLIENT,'redirect_uri':REDIRECT,'prompt':'login','response_type':'code','scope':'openid profile','state':state,'nonce':nonce,'code_challenge':challenge,'code_challenge_method':'S256'})
    return url,state


def callback(query,headers):
    params=urllib.parse.parse_qs(query)
    state=params.get('state',[''])[0];code=params.get('code',[''])[0]
    if not state or not secrets.compare_digest(state,cookies(headers).get('micro_login','')):raise PermissionError('Login state mismatch.')
    with store() as c:
        row=c.execute('SELECT verifier,nonce FROM login WHERE state=? AND expires>?',(digest(state),time.time())).fetchone()
        c.execute('DELETE FROM login WHERE state=?',(digest(state),))
    if not row or not code:raise PermissionError('Login expired or already used.')
    data=urllib.parse.urlencode({'grant_type':'authorization_code','client_id':CLIENT,'redirect_uri':REDIRECT,'code':code,'code_verifier':row[0]}).encode()
    with urllib.request.urlopen(urllib.request.Request(INTERNAL+'/protocol/openid-connect/token',data,{'Content-Type':'application/x-www-form-urlencoded'}),timeout=10) as r:tokens=json.load(r)
    claims=verify(tokens['id_token'])
    if claims.get('nonce')!=row[1]:raise PermissionError('Login nonce mismatch.')
    access=verify(tokens['access_token']);actor=actor_from(access)
    if access['sub']!=claims['sub']:raise PermissionError('Identity mismatch.')
    sid=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
    expires=min(time.time()+300,access['exp'])
    with store() as c:c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(sid),json.dumps(actor),csrf,expires))
    return sid


def logout(headers):
    sid=cookies(headers).get('micro_session')
    if sid:
        with store() as c:c.execute('DELETE FROM sessions WHERE id=?',(digest(sid),))
