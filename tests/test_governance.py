import json
import os
import tempfile
import unittest
from unittest.mock import patch
from app import governance as g
from app.telemetry import payload
from app.agent import SYSTEM

class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name});self.env.start()
    def tearDown(self): self.env.stop();self.tmp.cleanup()
    def fake(self,prompt,**kwargs):
        return {'message':{'content':json.dumps({'tool':'calculator','argument':'7*8'})},'prompt_eval_count':10,'eval_count':10}
    def team(self,**kwargs):
        return g.run_team('hello',scenario=kwargs.pop('scenario','custom'),caller=self.fake,persist=False,**kwargs)
    def test_allowed_and_identity_gate(self):
        t=self.team();self.assertEqual(t['answer'],'56')
        t=self.team(agent='researcher');self.assertEqual(t['status'],'blocked')
        self.assertFalse(any(s['name'].startswith('tool.') for s in t['spans']))
    def test_all_blocked_fixtures(self):
        for name in ['role_denied','budget','delegation_denied','sensitive']:
            self.assertEqual(self.team(scenario=name)['status'],'blocked')
    def test_sensitive_never_reaches_model_or_trace(self):
        t=g.run_team('DEMO_SECRET=abc',caller=lambda *a,**kw:self.fail('Model must not run'),persist=False)
        self.assertNotIn('DEMO_SECRET=abc',json.dumps(t))
    def draft(self): return self.team(scenario='approval')['approval_id']
    def test_approval_single_use_and_durable(self):
        approval=self.draft();self.assertEqual(g.reports(),[])
        t=g.resolve(approval,'approve',persist=False);self.assertEqual(t['status'],'ok')
        self.assertEqual(len(g.reports()),1)
        with self.assertRaises(ValueError): g.resolve(approval,'approve',persist=False)
        self.assertEqual(len(g.reports()),1)
    def test_reject_does_not_publish(self):
        self.assertEqual(g.resolve(self.draft(),'reject',persist=False)['status'],'rejected')
        self.assertEqual(g.reports(),[])
    def test_policy_change_invalidates_approval(self):
        approval=self.draft();rules=g.policy();rules.pop('version');g.update_policy(rules)
        self.assertEqual(g.resolve(approval,'approve',persist=False)['status'],'blocked')
        self.assertEqual(g.reports(),[])
    def test_expiry_and_tamper(self):
        approval=self.draft()
        with g.db() as c:c.execute('UPDATE approvals SET expires=0 WHERE id=?',(approval,))
        self.assertEqual(g.resolve(approval,'approve',persist=False)['status'],'expired')
        approval=self.draft()
        with g.db() as c:
            body=json.loads(c.execute('SELECT body FROM approvals WHERE id=?',(approval,)).fetchone()[0]);body['action']['argument']='changed'
            c.execute('UPDATE approvals SET body=? WHERE id=?',(json.dumps(body),approval))
        self.assertEqual(g.resolve(approval,'approve',persist=False)['status'],'blocked')
        self.assertEqual(g.reports(),[])
    def test_publishing_disabled_and_zero_budget(self):
        rules=g.policy();rules.pop('version');rules['allow_publish']=False;g.update_policy(rules)
        self.assertEqual(self.team(scenario='approval')['status'],'blocked')
        rules['tool_budget']=0;g.update_policy(rules)
        self.assertEqual(self.team()['status'],'blocked')
    def test_cannot_disable_approval(self):
        rules=g.policy();rules.pop('version');rules['approval_required']=False
        with self.assertRaises(ValueError):g.update_policy(rules)
    def test_nested_telemetry(self):
        t=self.team();spans=payload(t,SYSTEM)['resourceSpans'][0]['scopeSpans'][0]['spans']
        agent=next(x for x in spans if x['name']=='agent.analyst')
        tool=next(x for x in spans if x['name']=='tool.calculator')
        self.assertEqual(tool['parentSpanId'],agent['spanId'])
