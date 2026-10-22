#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36"
KEYWORDS = re.compile(r"(?i)(download|pdf|preview|view|attach|file|标准全文|下载标准|hcno|stdFile|ajax|url|src|href|form|action|verifyCode|captcha)")
URL_RE = re.compile(r"(?P<url>(?:https?:)?//[^\"'<>\\\s]+|/[A-Za-z0-9_./?=&%+:@-]+)")
SCRIPT_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)
HCNO_RE = re.compile(r'data-value=["\']([A-Fa-f0-9]{32})["\']')
ATTR_URL_RE = re.compile(r'(?i)(?:href|src|action|data-url|data-src)\s*=\s*["\']([^"\']+)["\']')
QUOTED_PATH_RE = re.compile(r'["\']((?:/bzgk/|/gb/|/std/|https?://)[^"\']+)["\']', re.I)


def fetch(session: requests.Session, url: str) -> requests.Response:
    r = session.get(url, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r


def response_metadata(r: requests.Response) -> dict:
    return {
        'status_code': r.status_code,
        'url': r.url,
        'content_type': r.headers.get('content-type', ''),
        'content_disposition': r.headers.get('content-disposition', ''),
        'content_length': r.headers.get('content-length', ''),
        'location': r.headers.get('location', ''),
        'set_cookie_names': sorted({part.split('=',1)[0].strip() for part in r.headers.get('set-cookie','').split(';') if '=' in part})[:20],
    }


def scan_text(text: str, base_url: str) -> list[dict]:
    hits = []
    seen = set()
    for line_no, line in enumerate(text.splitlines(), 1):
        if not KEYWORDS.search(line):
            continue
        urls = []
        for m in URL_RE.finditer(line):
            raw = m.group('url')
            if raw.startswith('//'):
                raw = 'https:' + raw
            elif raw.startswith('/'):
                raw = urljoin(base_url, raw)
            if raw.startswith('http'):
                urls.append(raw)
        key = (line_no, line.strip()[:500])
        if key in seen:
            continue
        seen.add(key)
        hits.append({'line': line_no, 'text': line.strip()[:1200], 'urls': list(dict.fromkeys(urls))})
    return hits


def extract_page_endpoints(text: str, base_url: str) -> list[str]:
    candidates = []
    for raw in ATTR_URL_RE.findall(text) + QUOTED_PATH_RE.findall(text):
        raw = raw.strip()
        if raw.startswith('//'):
            raw = 'https:' + raw
        elif raw.startswith('/'):
            raw = urljoin(base_url, raw)
        if raw.startswith('http'):
            candidates.append(raw)
    return list(dict.fromkeys(candidates))


def control_context(text: str) -> list[dict]:
    lines=text.splitlines()
    anchors=[]
    for idx,line in enumerate(lines):
        if re.search(r'(?i)(function\s+download|verifyCode|viewGb\?hcno|function\s+check|gc\?_?)',line):
            anchors.append(idx)
    indices=set()
    for a in anchors:
        indices.update(range(max(0,a-6),min(len(lines),a+12)))
    return [{'line':i+1,'text':lines[i].strip()[:1600]} for i in sorted(indices)][:180]


def bounded_html_metadata(r: requests.Response, limit: int = 512 * 1024) -> dict:
    chunks=[]; total=0
    for chunk in r.iter_content(chunk_size=16384):
        if not chunk: continue
        remain=limit-total
        if remain<=0: break
        chunks.append(chunk[:remain]); total+=min(len(chunk),remain)
        if total>=limit: break
    raw=b''.join(chunks)
    text=raw.decode(r.encoding or 'utf-8',errors='replace')
    return {
        'wrapper_bytes_read':len(raw),'wrapper_sha256':hashlib.sha256(raw).hexdigest(),
        'wrapper_hits':scan_text(text,r.url)[:120],
        'wrapper_endpoints':extract_page_endpoints(text,r.url)[:120],
        'control_context':control_context(text),
    }


def bounded_binary_prefix(r: requests.Response, limit: int = 32) -> dict:
    prefix=b''
    for chunk in r.iter_content(chunk_size=limit):
        if chunk:
            prefix=chunk[:limit]; break
    return {'prefix_bytes_read':len(prefix),'prefix_hex':prefix.hex(),'prefix_ascii':''.join(chr(b) if 32<=b<127 else '.' for b in prefix),'starts_with_pdf_magic':prefix.startswith(b'%PDF-'),'starts_with_zip_magic':prefix.startswith(b'PK')}


def probe_stream_metadata(session: requests.Session, url: str, referer: str) -> dict:
    headers={'Referer':referer,'Accept':'application/pdf,text/html,application/octet-stream;q=0.9,*/*;q=0.8'}
    result={'endpoint':url}
    r0=session.get(url,headers=headers,timeout=30,allow_redirects=False,stream=True)
    result['initial']=response_metadata(r0); location=r0.headers.get('location'); r0.close()
    try:
        r1=session.get(url,headers=headers,timeout=30,allow_redirects=True,stream=True)
        result['final']=response_metadata(r1); result['redirect_chain']=[response_metadata(x) for x in r1.history]
        ct=r1.headers.get('content-type','').lower(); result['is_pdf_by_header']='pdf' in ct; result['is_attachment']='attachment' in r1.headers.get('content-disposition','').lower()
        if 'html' in ct: result.update(bounded_html_metadata(r1))
        else: result.update(bounded_binary_prefix(r1))
        r1.close()
    except Exception as exc: result['follow_error']=str(exc)
    if location: result['resolved_location']=urljoin(url,location)
    return result


def probe_download_metadata(session: requests.Session, hcno: str, referer: str) -> dict:
    base='https://openstd.samr.gov.cn'
    show_url=f'{base}/bzgk/std/showGb?type=download&hcno={hcno}&request_locale=zh_CN'
    result={'hcno':hcno,'showGb':probe_stream_metadata(session,show_url,referer)}
    view_url=f'{base}/bzgk/std/viewGb?hcno={hcno}'
    result['viewGb']=probe_stream_metadata(session,view_url,show_url)
    result['session_cookie_names']=sorted(session.cookies.keys())
    return result


def probe_one(session: requests.Session, target: dict, out_dir: Path) -> dict:
    ref=target['reference']; detail_url=target['detail_url']
    result={'reference':ref,'detail_url':detail_url,'status':'UNKNOWN','html_url':None,'html_hits':[],'script_hits':[],'candidates':[]}
    try:
        r=fetch(session,detail_url); result['html_url']=r.url; result['http_status']=r.status_code; result['content_type']=r.headers.get('content-type',''); html=r.text; result['html_hits']=scan_text(html,r.url)[:120]
        hcnos=HCNO_RE.findall(html); hcno=target.get('hcno') or (hcnos[0] if hcnos else ''); result['hcno']=hcno
        if hcno: result['download_probe']=probe_download_metadata(session,hcno,r.url)
        scripts=list(dict.fromkeys([urljoin(r.url,x) for x in SCRIPT_RE.findall(html)]))[:40]
        for script_url in scripts:
            try:
                sr=fetch(session,script_url); hits=scan_text(sr.text,sr.url)
                useful=[h for h in hits if any('/bzgk/' in u or '/std/' in u or '/gb/' in u for u in h.get('urls',[])) or re.search(r'(?i)(showGb|download|pdf|hcno|stdFile|viewGb|verifyCode)',h['text'])]
                if useful: result['script_hits'].append({'url':sr.url,'hits':useful[:30]})
            except Exception as exc: result['script_hits'].append({'url':script_url,'error':str(exc)})
        candidate_urls=[]
        for hit in result['html_hits']: candidate_urls.extend(hit.get('urls',[]))
        for block in result['script_hits']:
            for hit in block.get('hits',[]): candidate_urls.extend(hit.get('urls',[]))
        dp=result.get('download_probe',{})
        for hop in ['showGb','viewGb']:
            candidate_urls.extend(dp.get(hop,{}).get('wrapper_endpoints',[]))
            if dp.get(hop,{}).get('resolved_location'): candidate_urls.append(dp[hop]['resolved_location'])
            if dp.get(hop,{}).get('final',{}).get('url'): candidate_urls.append(dp[hop]['final']['url'])
        for u in dict.fromkeys(candidate_urls):
            host=urlparse(u).netloc.lower()
            if host.endswith('samr.gov.cn') or host.endswith('sac.gov.cn') or host.endswith('gb688.cn'): result['candidates'].append(u)
        result['status']='PROBED'
    except Exception as exc: result['status']='ERROR'; result['error']=str(exc)
    return result


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--targets',required=True); ap.add_argument('--out',required=True); args=ap.parse_args()
    targets=json.loads(Path(args.targets).read_text(encoding='utf-8'))['targets']; out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    session=requests.Session(); session.headers.update({'User-Agent':UA,'Accept':'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8','Referer':'https://openstd.samr.gov.cn/'})
    results=[probe_one(session,t,out) for t in targets]
    (out/'resolver-results.json').write_text(json.dumps({'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'results':results},ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
