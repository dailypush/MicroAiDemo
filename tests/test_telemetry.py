import json
import os
import unittest
from unittest.mock import patch
from app.agent import run, SYSTEM
from app.telemetry import payload, export_trace

class TelemetryTests(unittest.TestCase):
    def trace(self, fault='none'):
        return run('7*8', fault, caller=lambda _: {'message': {'content': '{"tool":"calculator","argument":"7*8"}'}, 'prompt_eval_count': 30, 'eval_count': 10}, persist=False)

    def test_parentage_timing_and_tokens(self):
        trace = self.trace()
        spans = payload(trace, SYSTEM)['resourceSpans'][0]['scopeSpans'][0]['spans']
        root, generation = spans[:2]
        self.assertEqual(root['traceId'], trace['id'])
        self.assertEqual(len(spans), 5)
        for span in spans[1:]:
            self.assertEqual(span['parentSpanId'], root['spanId'])
            self.assertGreaterEqual(int(span['startTimeUnixNano']), int(root['startTimeUnixNano']))
            self.assertGreaterEqual(int(span['endTimeUnixNano']), int(span['startTimeUnixNano']))
        attrs={a['key']:a['value']['stringValue'] for a in generation['attributes']}
        self.assertEqual(attrs['langfuse.observation.type'], 'generation')
        self.assertEqual(json.loads(attrs['langfuse.observation.usage_details']), {'input':30,'output':10})

    def test_error_is_visible(self):
        spans=payload(self.trace('invalid_tool'), SYSTEM)['resourceSpans'][0]['scopeSpans'][0]['spans']
        self.assertEqual(spans[0]['status']['code'], 2)
        self.assertEqual(spans[-1]['status']['code'], 2)
        self.assertIn('rejected', spans[-1]['status']['message'])

    def test_export_failure_does_not_raise(self):
        with patch.dict(os.environ, {'LANGFUSE_BASE_URL':'http://local','LANGFUSE_PUBLIC_KEY':'pk','LANGFUSE_SECRET_KEY':'sk'}), patch('urllib.request.urlopen', side_effect=TimeoutError('offline')):
            self.assertEqual(export_trace(self.trace(), SYSTEM)['status'], 'error')
