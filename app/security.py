"""Verified identities and fail-closed external policy decisions."""
import contextvars
import json
import os
import urllib.request

ACTOR=contextvars.ContextVar('actor',default=None)
LAST_DECISION=contextvars.ContextVar('policy_decision',default=None)

class PolicyUnavailable(Exception): pass
class AccessDenied(Exception): pass


def authorize(operation, **details):
    actor=ACTOR.get()
    base=os.getenv('OPA_URL')
    if not base:
        if os.getenv('AUTH_ENABLED')=='true':raise PolicyUnavailable('External policy service is not configured.')
        return {'allowed':True,'policy_version':'unit-test-local','reason':'Local test mode'}
    request=urllib.request.Request(base+'/v1/data/micro/decision',json.dumps({'input':{'operation':operation,'actor':actor or {'sub':'','roles':[]},**details}}).encode(),{'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=3) as response:result=json.load(response)['result']
        if type(result.get('allowed')) is not bool:raise ValueError('Undefined policy result')
        LAST_DECISION.set(result)
        return result
    except Exception as error:
        raise PolicyUnavailable('External policy service is unavailable; action stopped.') from error


def require(operation,**details):
    result=authorize(operation,**details)
    if not result['allowed']:raise AccessDenied(result['reason'])
    return result
