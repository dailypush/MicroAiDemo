import json
import os
import tempfile
import unittest
from unittest.mock import patch
from app import governance as g, workshop as w

class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name});self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_read_without_human(self):
        t=w.run('expense_read',persist=False);self.assertEqual(t['status'],'ok');self.assertEqual(g.approvals(),[])
        self.assertIn('250',t['answer'])
    def test_amount_and_unknown_block_before_human(self):
        for lab in ('expense_unknown','expense_threshold'):
            t=w.run(lab,persist=False);self.assertEqual(t['status'],'blocked')
        self.assertEqual(g.approvals(),[])
    def test_changed_amount_rejected(self):
        action={'tool':'approve_expense','argument':json.dumps({'report_id':'EXP-001','amount':1,'currency':'USD'})}
        self.assertEqual(g.gate('expense_agent',action,g.policy())[1],'canonical_amount')
    def test_approve_is_exact_and_simulated(self):
        t=w.run('expense_approve',persist=False);self.assertEqual(t['status'],'awaiting_approval');self.assertEqual(g.reports(),[])
        resolved=g.resolve(t['approval_id'],'approve',persist=False);self.assertEqual(resolved['status'],'ok')
        self.assertTrue(any(s['name']=='tool.approve_expense' for s in resolved['spans']))
        self.assertEqual(json.loads(g.reports()[0]['content']),{'report_id':'EXP-001','amount':250,'currency':'USD'})
    def test_budget_consumed(self):
        t=w.run('expense_budget',persist=False)
        self.assertEqual(t['status'],'blocked')
        self.assertEqual(sum(s['name']=='tool.read_expense' for s in t['spans']),2)
        self.assertEqual(t['decisions'][-1]['rule'],'tool_budget')
    def test_retrieval_citation_and_refusal(self):
        self.assertEqual(w.retrieve('How many days of annual leave?')['source'],'hr-leave.txt')
        self.assertIsNone(w.retrieve('What is the pension policy?')['source'])
    def test_evaluation_split(self):
        t=w.run('evaluation_split',persist=False);self.assertTrue(t['evaluations']['task_adherence']['passed']);self.assertFalse(t['evaluations']['compliance']['passed'])
        self.assertFalse(w.evaluate_answer('fake','fake',['MISSING'])['compliance']['passed'])
    def test_guardrail_comparison(self):
        t=w.run('guardrail_compare',persist=False);result=json.loads(t['answer'])
        self.assertEqual(result['basic']['outcome'],'allow');self.assertEqual(result['strict']['outcome'],'deny')
    def test_grounding_uses_model_and_document(self):
        fake=lambda *a,**k:{'message':{'content':'{"tool":"finish","argument":"I need the document."}'},'eval_count':8,'prompt_eval_count':20}
        t=w.run('data_grounding',caller=fake,persist=False);self.assertEqual(t['status'],'ok')
        self.assertEqual(json.loads(t['answer'])['local_retrieval']['source'],'hr-leave.txt')
        from app.telemetry import payload
        from app.agent import SYSTEM
        spans=payload(t,SYSTEM)['resourceSpans'][0]['scopeSpans'][0]['spans']
        retrieval=next(s for s in spans if s['name']=='tool.retrieve_documents')
        attrs={a['key']:a['value']['stringValue'] for a in retrieval['attributes']}
        self.assertEqual(attrs['langfuse.observation.type'],'retriever')
