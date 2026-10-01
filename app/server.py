import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Semaphore
from app.agent import URL, MODEL, LOCK, run, evaluate
from app import governance

BUSY = Semaphore(1)

class Handler(BaseHTTPRequestHandler):
    def send(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
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
        if self.path not in ('/api/run', '/api/evaluate', '/api/team/run', '/api/approvals/resolve', '/api/policy'):
            return self.send({'error': 'Not found'}, 404)
        origin=self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host',''):
            return self.send({'error':'Cross-origin writes are not allowed.'},403)
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            return self.send({'error':'Use application/json.'},415)
        if not BUSY.acquire(blocking=False):
            return self.send({'error': 'A run is already active. Try again shortly.'}, 429)
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 8192:
                raise ValueError('Request body must be 1–8192 bytes.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Request must be a JSON object.')
            if self.path == '/api/evaluate': result=evaluate()
            elif self.path == '/api/team/run': result=governance.run_team(body.get('prompt'),body.get('agent','analyst'),body.get('scenario','custom'))
            elif self.path == '/api/approvals/resolve': result=governance.resolve(body.get('approval_id'),body.get('decision'))
            elif self.path == '/api/policy':
                result=governance.update_policy(body)
                audit=governance.Trace('Human updated governance policy','policy_change',result)
                audit.add('governance.policy_change','human',observation_type='guardrail',output=result)
                audit.finish('ok','Policy updated to version '+str(result['version']))
            else: result=run(body.get('prompt'), body.get('fault', 'none'))
            self.send(result)
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
