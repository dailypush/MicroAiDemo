import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from app import auth

class IdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def token(self,**changes):
        body={'sub':'requester-id','iat':int(time.time()),'exp':int(time.time())+60,'iss':auth.ISSUER,'aud':auth.CLIENT,'preferred_username':'requester','realm_access':{'roles':['requester']},**changes}
        return jwt.encode(body,self.key,algorithm='RS256',headers={'kid':'test'})
    def test_signature_issuer_audience_and_expiry(self):
        with patch.object(auth.JWKS,'get_signing_key_from_jwt',return_value=SimpleNamespace(key=self.key.public_key())):
            self.assertEqual(auth.verify(self.token())['sub'],'requester-id')
            for changes in [{'iss':'http://attacker'},{'aud':'another-client'},{'exp':0}]:
                with self.assertRaises(PermissionError):auth.verify(self.token(**changes))
            other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            wrong=jwt.encode({'sub':'fake','iat':0,'exp':int(time.time())+60,'iss':auth.ISSUER,'aud':auth.CLIENT},other,algorithm='RS256')
            with self.assertRaises(PermissionError):auth.verify(wrong)
    def test_no_cookie_no_identity(self):self.assertEqual(auth.identity({}),(None,None))
    def test_session_identity_and_logout(self):
        with tempfile.TemporaryDirectory() as path,patch.dict(os.environ,{'DATA_DIR':path}):
            with auth.store() as c:c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(auth.digest('sid'),json.dumps({'sub':'verified','roles':['approver']}),'csrf',time.time()+60))
            actor,csrf=auth.identity({'Cookie':'micro_session=sid'})
            self.assertEqual(actor['sub'],'verified');self.assertEqual(csrf,'csrf')
            auth.logout({'Cookie':'micro_session=sid'})
            self.assertEqual(auth.identity({'Cookie':'micro_session=sid'}),(None,None))
    def test_login_requires_matching_state_cookie(self):
        with self.assertRaises(PermissionError):auth.callback('code=x&state=y',{'Cookie':'micro_login=z'})
