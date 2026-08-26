#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36"
KEYWORDS = re.compile(r"(?i)(download|pdf|preview|view|attach|file|标准全文|下载标准|hcno|stdFile)")
URL_RE = re.compile(r"(?P<url>(?:https?:)?//[^\"'<>\\\s]+|/[A-Za-z0-9_./?=&%+:-]+)")
SCRIPT_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)
HCNO_RE = re.compile(r'data-value=["\']([A-Fa-f0-9]{32})["\']')


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


def probe_download_metadata(session: requests.Session, hcno: str, referer: str) -> dict:
    """Probe headers/redirects only. Never persist or upload standard text in public CI."""
    base = 'https://openstd.samr.gov.cn'
    endpoint = f'{base}/bzgk/std/showGb?type=download&hcno={hcno}&request_locale=zh_CN'
    headers = {'Referer': referer, 'Accept': 'application/pdf,text/html,application/octet-stream;q=0.9,*/*;q=0.8'}
    result = {'hcno': hcno, 'endpoint': endpoint}

    # First request without following redirects, streamed so the body is not downloaded.
    r0 = session.get(endpoint, headers=headers, timeout=30, allow_redirects=False, stream=True)
    result['initial'] = response_metadata(r0)
    location = r0.headers.get('location')
    r0.close()

    # Then follow the official redirect chain, still streamed; inspect only final headers.
    try:
        r1 = session.get(endpoint, headers=headers, timeout=30, allow_redirects=True, stream=True)
        result['final'] = response_metadata(r1)
        result['redirect_chain'] = [response_metadata(x) for x in r1.history]
        result['is_pdf_by_header'] = 'pdf' in r1.headers.get('content-type', '').lower()
        result['is_attachment'] = 'attachment' in r1.headers.get('content-disposition', '').lower()
        r1.close()
    except Exception as exc:
        result['follow_error'] = str(exc)

    if location:
        result['resolved_location'] = urljoin(endpoint, location)
    return result


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
        hits.append({'line': line_no, 'text': line.strip()[:1000], 'urls': urls})
    return hits


def probe_one(session: requests.Session, target: dict, out_dir: Path) -> dict:
    ref = target['reference']
    detail_url = target['detail_url']
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', ref)
    item_dir = out_dir / safe
    item_dir.mkdir(parents=True, exist_ok=True)

    result = {'reference': ref, 'detail_url': detail_url, 'status': 'UNKNOWN', 'html_url': None, 'html_hits': [], 'script_hits': [], 'candidates': []}
    try:
        r = fetch(session, detail_url)
        result['html_url'] = r.url
        result['http_status'] = r.status_code
        result['content_type'] = r.headers.get('content-type', '')
        html = r.text
        result['html_hits'] = scan_text(html, r.url)

        hcnos = HCNO_RE.findall(html)
        hcno = target.get('hcno') or (hcnos[0] if hcnos else '')
        result['hcno'] = hcno
        if hcno:
            result['download_probe'] = probe_download_metadata(session, hcno, r.url)

        # Only inspect first-party script text in memory. Do not persist page/script bodies in artifact.
        scripts = [urljoin(r.url, x) for x in SCRIPT_RE.findall(html)]
        scripts = list(dict.fromkeys(scripts))[:40]
        for script_url in scripts:
            try:
                sr = fetch(session, script_url)
                hits = scan_text(sr.text, sr.url)
                if hits:
                    result['script_hits'].append({'url': sr.url, 'hits': hits[:20]})
            except Exception as exc:
                result['script_hits'].append({'url': script_url, 'error': str(exc)})

        candidate_urls = []
        for hit in result['html_hits']:
            candidate_urls.extend(hit.get('urls', []))
        for block in result['script_hits']:
            for hit in block.get('hits', []):
                candidate_urls.extend(hit.get('urls', []))
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
