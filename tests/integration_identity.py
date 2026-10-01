"""Run inside Docker; receive local test credentials on stdin, never print them."""
import json
import sys
import urllib.request
import urllib.parse
import urllib.error

credentials=json.load(sys.stdin)
base='http://localhost:8080'
tokens={}
for name,password in credentials.items():
    data=urllib.parse.urlencode({'grant_type':'password','client_id':'micro-app','username':name,'password':password}).encode()
    req=urllib.request.Request('http://keycloak:8080/realms/micro/protocol/openid-connect/token',data,{'Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req) as r:tokens[name]=json.load(r)['access_token']
    print('Verified Keycloak login:',name)

def request(path,actor=None,body=None,expected=200):
    headers={'Content-Type':'application/json'}
    if actor:headers['Authorization']='Bearer '+tokens[actor]
    req=urllib.request.Request(base+path,None if body is None else json.dumps(body).encode(),headers)
    try:
        with urllib.request.urlopen(req,timeout=120) as r:status=r.status;result=json.load(r)
    except urllib.error.HTTPError as e:status=e.code;result=json.load(e)
    assert status==expected,(path,status,result)
    return result

request('/api/governance',expected=401)
request('/api/workshop/run','approver',{'lab':'expense_approve'},403)
state=request('/api/governance','administrator')
policy=state['policy'];policy.pop('version')
request('/api/policy','requester',policy,403)
request('/api/policy','administrator',policy)
draft=request('/api/workshop/run','requester',{'lab':'expense_approve'})
assert draft['status']=='awaiting_approval',draft
assert draft['langfuse']['status']=='accepted'
print('Durable approval paused:',draft['approval_id'])
request('/api/approvals/resolve','requester',{'approval_id':draft['approval_id'],'decision':'approve'},403)
result=request('/api/approvals/resolve','approver',{'approval_id':draft['approval_id'],'decision':'approve'})
assert result['status']=='ok',result
assert result['username']=='approver' and result['original_run_id']==draft['id']
request('/api/approvals/resolve','approver',{'approval_id':draft['approval_id'],'decision':'approve'},400)
print('Role separation, authenticated approval, OPA recheck, and replay protection verified.')
blocked=request('/api/workshop/run','requester',{'lab':'expense_threshold'})
assert blocked['status']=='blocked'
print('External policy rejected the over-threshold expense.')
with urllib.request.urlopen(base+'/api/health') as r:assert json.load(r)['model_bytes']<1_000_000_000
print('Model remains under 1 GB.')
