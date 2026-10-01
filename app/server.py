import json
import os
import urllib.request
import urllib.parse
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Semaphore
from app.agent import URL, MODEL, LOCK, run, evaluate
from app import governance, workshop, auth
from app.security import ACTOR, require, AccessDenied, PolicyUnavailable
from app.workflow import invoke

BUSY = Semaphore(1)

class Handler(BaseHTTPRequestHandler):
    def log_request(self,code='-',size='-'):
        print(self.command,urllib.parse.urlsplit(self.path).path,code,flush=True)

    def send(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self,url,cookie=None):
        self.send_response(302)
        self.send_header('Location',url)
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers()

    def current_identity(self):
        ACTOR.set(None)
        actor,csrf=auth.identity(self.headers)
        ACTOR.set(actor)
        return actor,csrf

    def denied(self,error,status):
        if status in (403,503):
            try:
                t=governance.Trace('HTTP request '+self.path,'access_denied',governance.policy())
                t.add('governance.api_authorization','human',observation_type='guardrail',output={'outcome':'deny','reason':str(error)})
                t.finish('blocked',str(error))
            except Exception:pass
        self.send({'error':str(error)},status)

    def do_GET(self):
        try:
            parsed=urllib.parse.urlsplit(self.path)
            if parsed.path=='/auth/login':
                url,state=auth.login()
                return self.redirect(url,'micro_login='+state+'; HttpOnly; SameSite=Lax; Path=/auth; Max-Age=300')
            if parsed.path=='/auth/callback':
                sid=auth.callback(parsed.query,self.headers)
                return self.redirect('/','micro_session='+sid+'; HttpOnly; SameSite=Lax; Path=/; Max-Age=300')
            if parsed.path=='/api/me':
                actor,csrf=self.current_identity()
                return self.send({'actor':actor,'csrf':csrf})
            if parsed.path.startswith('/api/') and parsed.path!='/api/health':
                actor,csrf=self.current_identity()
                if not actor:return self.send({'error':'Sign in to access the demo.'},401)
                require('view')
            self.handle_GET()
        except PermissionError as e:self.denied(e,401)
        except AccessDenied as e:self.denied(e,403)
        except PolicyUnavailable as e:self.denied(e,503)
        except Exception:self.send({'error':'Identity provider unavailable. Try again shortly.'},503)

    def handle_GET(self):
        if self.path == '/':
            data = Path('/demo/app/index.html' if Path('/demo').exists() else 'app/index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(data)
        elif self.path == '/api/health':
            try:
                with urllib.request.urlopen(URL + '/api/tags', timeout=5) as response:
                    models = json.load(response)['models']
                model = next(m for m in models if m['name'] == MODEL)
                self.send({'ready': model['size'] < 1_000_000_000, 'model': MODEL, 'model_bytes': model['size']})
            except Exception as error:
                self.send({'ready': False, 'error': str(error)}, 503)
        elif self.path in ('/workshop','/workshop/threat-model'):
            name='README.md' if self.path=='/workshop' else 'threat-model.md'
            root=Path('/demo/workshop') if Path('/demo').exists() else Path('workshop')
            data=(root/name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(data)
        elif self.path == '/api/workshop':
            self.send({'labs':workshop.LABS,'expenses':workshop.EXPENSES,'documents':workshop.DOCUMENTS})
        elif self.path == '/api/governance':
            self.send({'agents':governance.AGENTS,'scenarios':governance.SCENARIOS,'policy':governance.policy(),'approvals':governance.approvals(),'reports':governance.reports()})
        elif self.path == '/api/traces':
            file = Path(os.getenv('DATA_DIR', '/data')) / 'traces.jsonl'
            with LOCK:
                from collections import deque
                if file.exists():
                    with file.open() as stream:
                        traces = [json.loads(line) for line in deque(stream, maxlen=30)]
                else:
                    traces = []
            self.send(traces[::-1])
        else:
            self.send({'error': 'Not found'}, 404)

    def do_POST(self):
        if self.path not in ('/api/run', '/api/evaluate', '/api/team/run', '/api/approvals/resolve', '/api/policy', '/api/workshop/run', '/auth/logout'):
            return self.send({'error': 'Not found'}, 404)
        origin=self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host',''):
            return self.send({'error':'Cross-origin writes are not allowed.'},403)
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            return self.send({'error':'Use application/json.'},415)
        try:
            actor,csrf=self.current_identity()
            if not actor:return self.send({'error':'Sign in before performing an action.'},401)
            if csrf and not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),csrf):
                return self.send({'error':'Missing or invalid session CSRF token.'},403)
            if self.path=='/auth/logout':
                auth.logout(self.headers)
                self.send_response(200);self.send_header('Set-Cookie','micro_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0');self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{}');return
            require('policy' if self.path=='/api/policy' else 'view' if self.path=='/api/approvals/resolve' else 'run')
        except PermissionError as e:return self.denied(e,401)
        except AccessDenied as e:return self.denied(e,403)
        except PolicyUnavailable as e:return self.denied(e,503)
        if not BUSY.acquire(blocking=False):
            return self.send({'error': 'A run is already active. Try again shortly.'}, 429)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 8192:
                raise ValueError('Request body must be 1–8192 bytes.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Request must be a JSON object.')
            if self.path == '/api/workshop/run': result=workshop.run(body.get('lab'),body.get('question','How many days of annual leave?'))
            elif self.path == '/api/evaluate': result=evaluate()
            elif self.path == '/api/team/run': result=governance.run_team(body.get('prompt'),body.get('agent','analyst'),body.get('scenario','custom'))
            elif self.path == '/api/approvals/resolve':
                approval_id=body.get('approval_id');decision=body.get('decision')
                if type(approval_id) is not str or decision not in ('approve','reject'):raise ValueError('Choose approve or reject for an approval.')
                with governance.db() as c: row=c.execute('SELECT body FROM approvals WHERE id=?',(approval_id,)).fetchone()
                if not row:raise ValueError('Approval does not exist.')
                draft=json.loads(row[0]);require('review',requester=(draft.get('requester') or {}).get('sub',''))
                result=invoke(approval_id,decision)
            elif self.path == '/api/policy':
                result=governance.update_policy(body)
                audit=governance.Trace('Human updated governance policy','policy_change',result)
                audit.add('governance.policy_change','human',observation_type='guardrail',output=result)
                audit.finish('ok','Policy updated to version '+str(result['version']))
            else: result=run(body.get('prompt'), body.get('fault', 'none'))
            self.send(result)
        except AccessDenied as error:
            self.denied(error,403)
        except PolicyUnavailable as error:
            self.denied(error,503)
        except (ValueError, TypeError) as error:
            self.send({'error': str(error)}, 400)
        except Exception as error:
            self.send({'error': str(error)}, 500)
        finally:
            BUSY.release()

if __name__ == '__main__':
    with urllib.request.urlopen(URL + '/api/tags', timeout=10) as response:
        installed = json.load(response)['models']
    selected = next(m for m in installed if m['name'] == MODEL)
    if selected['size'] >= 1_000_000_000:
        raise RuntimeError('Model exceeds the 1 GB download budget.')
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
