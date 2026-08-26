from __future__ import annotations
import json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
V2_ROOT=Path(__file__).resolve().parents[1]; V1_ROOT=V2_ROOT.parent/'p-aas-v1'
for p in (V2_ROOT,V1_ROOT):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
FIXTURE=V1_ROOT/'examples'/'automotive-eol-station'/'aas-environment.json'; ENV=json.loads(FIXTURE.read_text(encoding='utf-8'))
class FakeBaSyx:
    def __init__(self): self.env=json.loads(json.dumps(ENV)); self.server=None; self.thread=None; self.base_url=None
    def start(self):
        env=self.env
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def _json(self,status,obj):
                data=json.dumps(obj).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
            def _decode(self,token):
                import base64
                return base64.urlsafe_b64decode(token+'='*((4-len(token)%4)%4)).decode()
            def do_GET(self):
                if self.path=='/v3/api-docs': return self._json(200,{'openapi':'3.0.1','paths':{'/shells':{'post':{}},'/shells/{aasIdentifier}':{'get':{}},'/submodels':{'post':{}},'/submodels/{submodelIdentifier}':{'get':{}},'/concept-descriptions':{'post':{}},'/concept-descriptions/{cdIdentifier}':{'get':{}},'/upload':{'post':{}}}})
                if self.path.startswith('/shells/'):
                    raw=self._decode(self.path.split('/shells/',1)[1]); return self._json(200,next(x for x in env['assetAdministrationShells'] if x['id']==raw))
                if self.path.startswith('/submodels/'):
                    raw=self._decode(self.path.split('/submodels/',1)[1]); return self._json(200,next(x for x in env['submodels'] if x['id']==raw))
                if self.path.startswith('/concept-descriptions/'):
                    raw=self._decode(self.path.split('/concept-descriptions/',1)[1]); return self._json(200,next(x for x in env['conceptDescriptions'] if x['id']==raw))
                return self._json(404,{'error':'no route'})
            def do_POST(self):
                length=int(self.headers.get('Content-Length','0')); data=self.rfile.read(length) if length else b''
                if self.path in ('/shells','/submodels','/concept-descriptions'):
                    try: obj=json.loads(data or b'{}')
                    except Exception: return self._json(400,{'error':'bad json'})
                    return self._json(201,obj)
                return self._json(404,{'error':'no route'})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler); self.base_url=f'http://127.0.0.1:{self.server.server_address[1]}'; self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); return self
    def stop(self):
        if self.server: self.server.shutdown(); self.server.server_close()
