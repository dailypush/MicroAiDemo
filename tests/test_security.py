import json
import os
import unittest
from unittest.mock import patch, MagicMock
from app.security import authorize, require, ACTOR, AccessDenied, PolicyUnavailable

class SecurityTests(unittest.TestCase):
    def test_missing_opa_fails_closed(self):
        with patch.dict(os.environ,{'AUTH_ENABLED':'true','OPA_URL':''}):
            with self.assertRaises(PolicyUnavailable):authorize('run')
    def test_outage_fails_closed(self):
        with patch.dict(os.environ,{'OPA_URL':'http://offline'}),patch('urllib.request.urlopen',side_effect=TimeoutError):
            with self.assertRaises(PolicyUnavailable):authorize('review',requester='other')
    def test_denial_cannot_be_overridden(self):
        with patch('app.security.authorize',return_value={'allowed':False,'reason':'self-approval'}):
            with self.assertRaises(AccessDenied):require('review',requester='me')
    def test_subject_is_server_context(self):
        token=ACTOR.set({'sub':'verified','username':'requester','roles':['requester']})
        try:
            response=MagicMock();response.__enter__.return_value.read.return_value=b'{"result":{"allowed":true,"policy_version":"v1","reason":"allowed"}}'
            with patch.dict(os.environ,{'OPA_URL':'http://opa'}),patch('urllib.request.urlopen',return_value=response) as call:
                authorize('run')
                sent=json.loads(call.call_args.args[0].data)['input']
                self.assertEqual(sent['actor']['sub'],'verified')
        finally:ACTOR.reset(token)
