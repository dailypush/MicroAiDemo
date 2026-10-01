"""Server-side agent identities, policy gates, and durable approval decisions.

Publishing writes only a simulated report to SQLite. No external communication.
"""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from app.agent import MODEL, SYSTEM, NOTES, calculate, model_call, LOCK
from app.telemetry import export_trace

AGENTS = {
    'coordinator': {'role':'Delegates to specialists', 'tools':[], 'delegates':['analyst','researcher','publisher','expense_agent']},
    'analyst': {'role':'Calculates numbers', 'tools':['calculator','finish'], 'delegates':[]},
    'researcher': {'role':'Explains local concepts', 'tools':['lookup','finish'], 'delegates':[]},
    'expense_agent': {'role':'Reads synthetic expenses and requests approval', 'tools':['read_expense','approve_expense','finish'], 'delegates':[]},
    'publisher': {'role':'Drafts simulated reports for human approval', 'tools':['publish_report','finish'], 'delegates':[]},
}
DEFAULT = {'version':1, 'tool_budget':2, 'allow_publish':True, 'approval_required':True, 'block_demo_secrets':True}
SCENARIOS = {
    'allowed': {'label':'Allowed calculation', 'agent':'analyst','prompt':'Calculate (12 + 8) * 3'},
    'role_denied': {'label':'Researcher attempts calculator', 'agent':'researcher','prompt':'Calculate 7 * 8','proposal':{'tool':'calculator','argument':'7*8'}},
    'approval': {'label':'Publish report needs approval', 'agent':'publisher','prompt':'Publish a demo report saying: Agent governance is enabled.','proposal':{'tool':'publish_report','argument':'Agent governance is enabled.'}},
    'budget': {'label':'Exhaust the tool budget', 'agent':'analyst','prompt':'Calculate 7 * 8','proposal':{'tool':'calculator','argument':'7*8'},'used_budget':3},
    'delegation_denied': {'label':'Analyst attempts to delegate', 'agent':'analyst','prompt':'Delegate this report to publisher','delegate':'publisher'},
    'sensitive': {'label':'Block synthetic secret', 'agent':'publisher','prompt':'Publish DEMO_SECRET=training-only-123'},
}
SECRET = re.compile(r'DEMO_SECRET\s*=\s*[^\s]+', re.I)


@contextmanager
def db():
    directory=Path(os.getenv('DATA_DIR','/data'));directory.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(directory/'governance.sqlite',timeout=10)
    connection.execute('CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL, expires REAL NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, approval_id TEXT UNIQUE NOT NULL, content TEXT NOT NULL, created REAL NOT NULL)')
    connection.execute('INSERT OR IGNORE INTO policy VALUES (1, ?)',(json.dumps(DEFAULT),))
    connection.commit()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def policy():
    with db() as c: return json.loads(c.execute('SELECT body FROM policy WHERE id=1').fetchone()[0])


def update_policy(body):
    keys={'tool_budget','allow_publish','approval_required','block_demo_secrets'}
    if set(body)!=keys or type(body['tool_budget']) is not int or not 0<=body['tool_budget']<=3 or any(type(body[k]) is not bool for k in keys-{'tool_budget'}):
        raise ValueError('Policy requires budget 0–3 and three boolean controls.')
    # Always require human approval for writes in this local learning demo.
    if not body['approval_required']:
        raise ValueError('Human approval for publishing cannot be disabled in this demo.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=json.loads(c.execute('SELECT body FROM policy WHERE id=1').fetchone()[0]);new={**body,'version':current['version']+1}
        c.execute('UPDATE policy SET body=? WHERE id=1',(json.dumps(new),))
    return new


def redact(value):
    return SECRET.sub('[REDACTED DEMO SECRET]',value)


def gate(agent, action, rules, used=0):
    if agent not in AGENTS or not isinstance(action,dict) or set(action)!={'tool','argument'} or type(action.get('argument')) is not str or len(action['argument'])>2000:
        return 'deny','invalid_action','Action shape or agent identity is invalid.'
    if action['tool'] not in AGENTS[agent]['tools']:
        return 'deny','role_permissions',f"{agent} cannot use {action['tool']}."
    if rules['block_demo_secrets'] and SECRET.search(action['argument']):
        return 'deny','demo_secret','Synthetic secret must not enter a tool.'
    if used >= rules['tool_budget']:
        return 'deny','tool_budget','Run has exhausted its tool-call budget.'
    if action['tool'] in ('read_expense','approve_expense'):
        from app.workshop import EXPENSES
        try:
            args=json.loads(action['argument'])
        except (ValueError,TypeError):
            return 'deny','expense_arguments','Expense arguments must be JSON.'
        if not isinstance(args,dict) or set(args)!=({'report_id'} if action['tool']=='read_expense' else {'report_id','amount','currency'}):
            return 'deny','expense_arguments','Invalid expense argument fields.'
        expense=EXPENSES.get(args.get('report_id')) if isinstance(args.get('report_id'),str) else None
        if not expense: return 'deny','report_exists','Expense report does not exist.'
        if action['tool']=='approve_expense':
            if type(args['amount']) not in (int,float) or args['amount']!=expense['amount'] or args['currency']!=expense['currency']:
                return 'deny','canonical_amount','Requested amount or currency does not match the stored expense.'
            if expense['amount']>1000: return 'deny','amount_threshold','Amount exceeds the local $1,000 approval threshold; no human request created.'
            if not rules['allow_publish']: return 'deny','writes_disabled','Simulated writes are disabled by current policy.'
            return 'approval_required','human_approval','Human must approve this exact expense ID, amount, and currency.'
    if action['tool']=='publish_report':
        if not rules['allow_publish']: return 'deny','publishing_disabled','Publishing is disabled by current policy.'
        return 'approval_required','human_approval','Publishing requires approval of this exact report.'
    return 'allow','role_and_budget','Agent role and run budget allow this action.'


class Trace:
    def __init__(self,prompt,scenario,rules):
        self.start=time.perf_counter()
        self.data={'id':uuid.uuid4().hex,'timestamp':time.time(),'prompt':redact(prompt),'model':MODEL,
                   'fault':'none','status':'running','spans':[],'scenario':scenario,'policy_version':rules['version'],'decisions':[]}
    def add(self,name,agent='coordinator',began=None,parent=None,**values):
        now=time.perf_counter();began=now if began is None else began
        item={'name':name,'agent':agent,'id':uuid.uuid4().hex[:16],'start_offset_ms':round((began-self.start)*1000,2),
              'duration_ms':round((now-began)*1000,2),**values}
        if parent: item['parent_id']=parent
        self.data['spans'].append(item);return item['id']
    def decision(self,agent,action,rules,used=0,parent=None):
        outcome,rule,reason=gate(agent,action,rules,used)
        item={'agent':agent,'outcome':outcome,'rule':rule,'reason':reason,'policy_version':rules['version'],'action':json.loads(redact(json.dumps(action)))}
        self.data['decisions'].append(item)
        self.add('governance.check',agent,parent=parent,observation_type='guardrail',output=item)
        return outcome,reason
    def finish(self,status,answer,persist=True):
        for item in self.data['spans']:
            if item.get('observation_type')=='agent' and item['agent']!='coordinator':
                item['duration_ms']=round((time.perf_counter()-self.start)*1000-item['start_offset_ms'],2)
        self.data.update(status=status,answer=redact(answer),duration_ms=round((time.perf_counter()-self.start)*1000,2))
        if persist:
            self.data['langfuse']=export_trace(self.data,SYSTEM)
            with LOCK, (Path(os.getenv('DATA_DIR','/data'))/'traces.jsonl').open('a') as f: f.write(json.dumps(self.data)+'\n')
        return self.data


def run_team(prompt,agent='analyst',scenario='custom',caller=model_call,persist=True):
    if scenario!='custom':
        if scenario not in SCENARIOS: raise ValueError('Unknown scenario.')
        config=SCENARIOS[scenario];prompt=config['prompt'];agent=config['agent']
    else: config={}
    if agent not in AGENTS or agent=='coordinator': raise ValueError('Choose a specialist agent.')
    if type(prompt) is not str or not 1<=len(prompt.strip())<=1000: raise ValueError('Enter 1–1000 characters.')
    rules=policy();t=Trace(prompt,scenario,rules)
    if rules['block_demo_secrets'] and SECRET.search(prompt):
        t.add('governance.input','coordinator',observation_type='guardrail',output={'outcome':'deny','rule':'demo_secret','reason':'Synthetic secret blocked before model inference.'})
        t.data['decisions'].append({'outcome':'deny','rule':'demo_secret','reason':'Synthetic secret blocked before inference.','policy_version':rules['version']})
        return t.finish('blocked','Synthetic secret blocked before model inference.',persist)
    t.add('agent.coordinator',observation_type='agent',output={'delegate_to':agent,'source':'User-selected workflow'})
    t.add('governance.delegation',observation_type='guardrail',output={'outcome':'allow','from':'coordinator','to':agent,'policy_version':rules['version']})
    began=time.perf_counter();parent=t.add('agent.'+agent,agent,observation_type='agent',output=AGENTS[agent]['role'])
    try:
        if config.get('delegate'):
            target=config['delegate']
            t.add('governance.delegation',agent,parent=parent,observation_type='guardrail',output={'outcome':'deny','reason':f'{agent} cannot delegate to {target}.'})
            t.data['decisions'].append({'outcome':'deny','rule':'delegation_permissions','reason':f'{agent} has no delegation permission.','policy_version':rules['version']})
            return t.finish('blocked','Delegation blocked: specialist agents cannot delegate.',persist)
        if 'proposal' in config:
            action=copy.deepcopy(config['proposal'])
            t.add('demo.inject_proposal',agent,parent=parent,output={'source':'Explicit demo fixture; no model inference','action':action})
        else:
            tools=AGENTS[agent]['tools']
            system=SYSTEM+'\nYour agent identity is '+agent+'. You may choose only '+', '.join(tools)+'. For publish_report, argument is the report text.'
            if agent=='expense_agent':
                from app.workshop import EXPENSES
                system+=' For read_expense, argument is a JSON string with report_id. For approve_expense, argument is a JSON string with report_id, amount, currency. Stored synthetic expenses: '+json.dumps(EXPENSES)
            schema={'type':'object','properties':{'tool':{'type':'string','enum':tools},'argument':{'type':'string'}},'required':['tool','argument'],'additionalProperties':False}
            model_start=time.perf_counter();response=caller(prompt,system=system,schema=schema)
            raw=response['message']['content']
            t.add('model.choose_action',agent,began=model_start,parent=parent,output=redact(raw),input=redact(prompt),system_prompt=system,
                  input_tokens=response.get('prompt_eval_count',0),output_tokens=response.get('eval_count',0))
            action=json.loads(raw)
        used=config.get('used_budget',0)
        outcome,reason=t.decision(agent,action,rules,used,parent)
        t.data['action']=json.loads(redact(json.dumps(action)))
        if outcome=='deny': return t.finish('blocked',reason,persist)
        if outcome=='approval_required':
            approval_id=uuid.uuid4().hex
            body={'agent':agent,'action':action,'policy_version':rules['version'],'run_id':t.data['id'],'used_budget':used,
                  'digest':hashlib.sha256(json.dumps(action,sort_keys=True).encode()).hexdigest()}
            with db() as c: c.execute('INSERT INTO approvals VALUES (?,?,?,?)',(approval_id,json.dumps(body),'pending',time.time()+900))
            t.data['approval_id']=approval_id
            return t.finish('awaiting_approval','Report drafted. Review the exact action in the approval queue.',persist)
        tool_start=time.perf_counter()
        if action['tool']=='calculator': result=calculate(action['argument'])
        elif action['tool']=='lookup': result=NOTES[action['argument'].strip().lower()]
        elif action['tool']=='read_expense':
            from app.workshop import EXPENSES
            result=json.dumps(EXPENSES[json.loads(action['argument'])['report_id']])
        else: result=action['argument']
        t.add('tool.'+action['tool'],agent,began=tool_start,parent=parent,input=action,output=redact(result))
        t.add('harness.return_answer',agent,parent=parent,output=redact(result))
        return t.finish('ok',result,persist)
    except Exception as e:
        t.add('harness.error',agent,parent=parent,error=redact(str(e)))
        return t.finish('error',f'Run stopped: {redact(str(e))}',persist)


def approvals():
    with db() as c:
        rows=c.execute('SELECT id,body,state,expires FROM approvals ORDER BY rowid DESC LIMIT 30').fetchall()
    return [{'id':i,**json.loads(body),'state':'expired' if state=='pending' and expires<time.time() else state,'expires':expires} for i,body,state,expires in rows]


def reports():
    with db() as c: return [{'id':i,'approval_id':a,'content':body,'created':created} for i,a,body,created in c.execute('SELECT * FROM reports ORDER BY created DESC LIMIT 30')]


def resolve(approval_id,decision,persist=True):
    if type(approval_id) is not str or decision not in ('approve','reject'): raise ValueError('Choose approve or reject for a pending approval.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT body,state,expires FROM approvals WHERE id=?',(approval_id,)).fetchone()
        if not row or row[1]!='pending': raise ValueError('Approval is missing or has already been resolved.')
        body=json.loads(row[0]);rules=json.loads(c.execute('SELECT body FROM policy WHERE id=1').fetchone()[0])
        t=Trace('Human decision on simulated report','approval_resolution',rules)
        t.data.update(approval_id=approval_id,original_run_id=body['run_id'])
        digest=hashlib.sha256(json.dumps(body['action'],sort_keys=True).encode()).hexdigest()
        if row[2]<time.time(): state='expired';reason='Approval expired. Create a new draft.'
        elif digest!=body['digest']: state='blocked';reason='Approval action integrity check failed.'
        elif decision=='reject': state='rejected';reason='Human rejected the report.'
        elif rules['version']!=body['policy_version']: state='blocked';reason='Policy changed since drafting. Create a new draft.'
        else:
            outcome,reason=t.decision(body['agent'],body['action'],rules,body['used_budget'])
            state='approved' if outcome=='approval_required' else 'blocked'
        t.add('governance.human_decision','human',observation_type='guardrail',input=body['action'],output={'decision':decision,'outcome':state,'reason':reason,'original_run_id':body['run_id']})
        if state=='approved':
            report_id=uuid.uuid4().hex
            c.execute('INSERT INTO reports VALUES (?,?,?,?)',(report_id,approval_id,body['action']['argument'],time.time()))
            t.add('tool.'+body['action']['tool'],body['agent'],input=body['action'],output={'report_id':report_id,'simulated':True})
            reason='Approved: action saved to the local simulated report store. No payment or external action occurred.'
        c.execute('UPDATE approvals SET state=? WHERE id=?',(state,approval_id))
    return t.finish('ok' if state=='approved' else state,reason,persist)
