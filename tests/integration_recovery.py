"""Receive secrets on stdin, return only test results and public workflow IDs."""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

settings=json.load(sys.stdin);mode=settings['mode']
username='approver' if mode=='resume' else 'requester'
data=urllib.parse.urlencode({'grant_type':'password','client_id':'micro-app','username':username,'password':settings['credentials'][username]}).encode()
with urllib.request.urlopen(urllib.request.Request('http://keycloak:8080/realms/micro/protocol/openid-connect/token',data,{'Content-Type':'application/x-www-form-urlencoded'})) as r:token=json.load(r)['access_token']
# Wait for the app's public health endpoint after a container restart.
import time
for attempt in range(40):
    try:
        with urllib.request.urlopen('http://localhost:8080/api/health',timeout=2) as r:
            if r.status==200:break
    except urllib.error.URLError:time.sleep(0.25)
else:raise RuntimeError('Demo did not become ready.')
body={'approval_id':settings.get('approval_id'),'decision':'approve'} if mode=='resume' else {'lab':'expense_approve'}
path='/api/approvals/resolve' if mode=='resume' else '/api/workshop/run'
req=urllib.request.Request('http://localhost:8080'+path,json.dumps(body).encode(),{'Content-Type':'application/json','Authorization':'Bearer '+token})
if mode=='outage':
    import sqlite3
    connection=sqlite3.connect(os.environ['DATA_DIR']+'/governance.sqlite')
    before=connection.execute('SELECT count(*) FROM reports').fetchone()[0]
    try:urllib.request.urlopen(req);raise AssertionError('OPA outage allowed action')
    except urllib.error.HTTPError as error:assert error.code==503
    after=connection.execute('SELECT count(*) FROM reports').fetchone()[0]
    assert before==after;connection.close()
    print(json.dumps({'outage':'failed closed','new_receipts':0}))
else:
    with urllib.request.urlopen(req) as r:result=json.load(r)
    assert result['status']==('ok' if mode=='resume' else 'awaiting_approval'),result
    print(json.dumps({'status':result['status'],'approval_id':result['approval_id'],'trace_id':result['id'],'username':result['username']}))
