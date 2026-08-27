from __future__ import annotations
import io, json, sys, threading, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

V2_ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = V2_ROOT.parent / 'p-aas-v1'
for p in (V2_ROOT, V1_ROOT):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
FIXTURE = V1_ROOT / 'examples' / 'automotive-eol-station' / 'aas-environment.json'
ENV = json.loads(FIXTURE.read_text(encoding='utf-8'))


def _rels(rows):
    body=''.join(f'<Relationship Id="{rid}" Type="{typ}" Target="{target}"/>' for rid,typ,target in rows)
    return f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{body}</Relationships>'


def _fake_aasx(environment: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="json" ContentType="application/json"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/aasx/aasx-origin" ContentType="application/aas-origin"/></Types>')
        z.writestr('_rels/.rels', _rels([('R1','http://admin-shell.io/aasx/relationships/aasx-origin','/aasx/aasx-origin')]))
        z.writestr('aasx/aasx-origin', '')
        z.writestr('aasx/_rels/aasx-origin.rels', _rels([('R1','http://admin-shell.io/aasx/relationships/aas-spec','aas-environment.json')]))
        z.writestr('aasx/aas-environment.json', json.dumps(environment, ensure_ascii=False))
        z.writestr('aasx/_rels/aas-environment.json.rels', _rels([]))
    return buffer.getvalue()


class FakeBaSyx:
    def __init__(self, openapi_base64=False):
        self.env=json.loads(json.dumps(ENV)); self.openapi_base64=openapi_base64; self.server=None; self.thread=None; self.base_url=None
        self.last_upload_accept=None; self.last_upload_contains_zip=False
    def start(self):
        env=self.env; openapi_base64=self.openapi_base64; owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def _bytes(self,status,data,content_type):
                self.send_response(status); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
            def _json(self,status,obj): return self._bytes(status,json.dumps(obj).encode(),'application/json')
            def do_GET(self):
                split=urlsplit(self.path)
                if split.path=='/large-json': return self._json(200,{'payload':'x'*20000,'tail':'parsed'})
                if split.path=='/v3/api-docs':
                    doc={'openapi':'3.0.1','paths':{'/shells':{'post':{}},'/shells/{aasIdentifier}':{'get':{}},'/submodels':{'post':{}},'/submodels/{submodelIdentifier}':{'get':{}},'/concept-descriptions':{'post':{}},'/concept-descriptions/{cdIdentifier}':{'get':{}},'/upload':{'post':{}},'/serialization':{'get':{}}}}
                    if openapi_base64:
                        import base64
                        return self._json(200,base64.urlsafe_b64encode(json.dumps(doc,separators=(',',':')).encode()).decode().rstrip('='))
                    return self._json(200,doc)
                if split.path=='/serialization':
                    if self.headers.get('Accept')!='application/asset-administration-shell-package+xml': return self._json(400,{'error':'wrong accept'})
                    query=parse_qs(split.query)
                    if not query.get('aasIds'): return self._json(400,{'error':'missing aasIds'})
                    import base64
                    token=query['aasIds'][0]; raw=base64.urlsafe_b64decode(token+'='*((4-len(token)%4)%4)).decode()
                    if raw!=env['assetAdministrationShells'][0]['id']: return self._json(404,{'error':'unknown aas'})
                    return self._bytes(200,_fake_aasx(env),'application/asset-administration-shell-package+xml')
                for prefix,key in (('/shells/','assetAdministrationShells'),('/submodels/','submodels'),('/concept-descriptions/','conceptDescriptions')):
                    if split.path.startswith(prefix):
                        import base64
                        token=split.path.split(prefix,1)[1]; raw=base64.urlsafe_b64decode(token+'='*((4-len(token)%4)%4)).decode()
                        for x in env[key]:
                            if x['id']==raw: return self._json(200,x)
                        return self._json(404,{'error':'not found'})
                return self._json(404,{'error':'no route'})
            def do_POST(self):
                split=urlsplit(self.path); length=int(self.headers.get('Content-Length','0')); data=self.rfile.read(length) if length else b''
                if split.path=='/upload':
                    owner.last_upload_accept=self.headers.get('Accept')
                    owner.last_upload_contains_zip=b'PK' in data
                    return self._json(200,{'uploaded':owner.last_upload_contains_zip}) if owner.last_upload_contains_zip else self._json(400,{'error':'missing zip payload'})
                if split.path in ('/shells','/submodels','/concept-descriptions'):
                    try: obj=json.loads(data or b'{}')
                    except Exception: return self._json(400,{'error':'bad json'})
                    return self._json(201,obj)
                return self._json(404,{'error':'no route'})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler); self.base_url=f'http://127.0.0.1:{self.server.server_address[1]}'; self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start(); return self
    def stop(self):
        if self.server: self.server.shutdown(); self.server.server_close()
