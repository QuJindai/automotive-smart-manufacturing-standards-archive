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
KEYWORDS = re.compile(r"(?i)(download|pdf|preview|view|attach|file|标准全文|下载标准|hcno|stdFile|ajax|url|src|href|form|action)")
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


def probe_download_metadata(session: requests.Session, hcno: str, referer: str) -> dict:
    """Inspect wrapper-page metadata and internal endpoints; never store the standard body in public CI."""
    base = 'https://openstd.samr.gov.cn'
    endpoint = f'{base}/bzgk/std/showGb?type=download&hcno={hcno}&request_locale=zh_CN'
    headers = {'Referer': referer, 'Accept': 'application/pdf,text/html,application/octet-stream;q=0.9,*/*;q=0.8'}
    result = {'hcno': hcno, 'endpoint': endpoint}

    r0 = session.get(endpoint, headers=headers, timeout=30, allow_redirects=False, stream=True)
    result['initial'] = response_metadata(r0)
    location = r0.headers.get('location')
    r0.close()

    try:
        r1 = session.get(endpoint, headers=headers, timeout=30, allow_redirects=True, stream=True)
        result['final'] = response_metadata(r1)
        result['redirect_chain'] = [response_metadata(x) for x in r1.history]
        content_type = r1.headers.get('content-type', '').lower()
        result['is_pdf_by_header'] = 'pdf' in content_type
        result['is_attachment'] = 'attachment' in r1.headers.get('content-disposition', '').lower()

        # HTML wrapper is not the standard text. Read only a bounded wrapper body to resolve the next official endpoint.
        if 'html' in content_type:
            chunks = []
            total = 0
            for chunk in r1.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                remain = 512 * 1024 - total
                if remain <= 0:
                    break
                chunks.append(chunk[:remain])
                total += min(len(chunk), remain)
                if total >= 512 * 1024:
                    break
            raw = b''.join(chunks)
            enc = r1.encoding or 'utf-8'
            text = raw.decode(enc, errors='replace')
            result['wrapper_bytes_read'] = len(raw)
            result['wrapper_sha256'] = hashlib.sha256(raw).hexdigest()
            result['wrapper_hits'] = scan_text(text, r1.url)[:120]
            result['wrapper_endpoints'] = extract_page_endpoints(text, r1.url)[:120]
        r1.close()
    except Exception as exc:
        result['follow_error'] = str(exc)

    if location:
        result['resolved_location'] = urljoin(endpoint, location)
    return result


def probe_one(session: requests.Session, target: dict, out_dir: Path) -> dict:
    ref = target['reference']
    detail_url = target['detail_url']
    result = {'reference': ref, 'detail_url': detail_url, 'status': 'UNKNOWN', 'html_url': None, 'html_hits': [], 'script_hits': [], 'candidates': []}
    try:
        r = fetch(session, detail_url)
        result['html_url'] = r.url
        result['http_status'] = r.status_code
        result['content_type'] = r.headers.get('content-type', '')
        html = r.text
        result['html_hits'] = scan_text(html, r.url)[:120]

        hcnos = HCNO_RE.findall(html)
        hcno = target.get('hcno') or (hcnos[0] if hcnos else '')
        result['hcno'] = hcno
        if hcno:
            result['download_probe'] = probe_download_metadata(session, hcno, r.url)

        scripts = [urljoin(r.url, x) for x in SCRIPT_RE.findall(html)]
        scripts = list(dict.fromkeys(scripts))[:40]
        for script_url in scripts:
            try:
                sr = fetch(session, script_url)
                hits = scan_text(sr.text, sr.url)
                # Skip giant generic libraries unless a likely standards endpoint is present.
                useful = [h for h in hits if any('/bzgk/' in u or '/std/' in u or '/gb/' in u for u in h.get('urls', [])) or re.search(r'(?i)(showGb|download|pdf|hcno|stdFile)', h['text'])]
                if useful:
                    result['script_hits'].append({'url': sr.url, 'hits': useful[:30]})
            except Exception as exc:
                result['script_hits'].append({'url': script_url, 'error': str(exc)})

        candidate_urls = []
        for hit in result['html_hits']:
            candidate_urls.extend(hit.get('urls', []))
        for block in result['script_hits']:
            for hit in block.get('hits', []):
                candidate_urls.extend(hit.get('urls', []))
        candidate_urls.extend(result.get('download_probe', {}).get('wrapper_endpoints', []))
        for u in dict.fromkeys(candidate_urls):
            host = urlparse(u).netloc.lower()
            if host.endswith('samr.gov.cn') or host.endswith('sac.gov.cn'):
                result['candidates'].append(u)

        result['status'] = 'PROBED'
    except Exception as exc:
        result['status'] = 'ERROR'
        result['error'] = str(exc)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    targets = json.loads(Path(args.targets).read_text(encoding='utf-8'))['targets']
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8', 'Referer': 'https://openstd.samr.gov.cn/'})

    results = [probe_one(session, t, out) for t in targets]
    (out / 'resolver-results.json').write_text(json.dumps({'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'results': results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
