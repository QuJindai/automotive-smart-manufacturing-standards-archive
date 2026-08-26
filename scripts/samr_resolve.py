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


def fetch(session: requests.Session, url: str) -> requests.Response:
    r = session.get(url, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r


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
        (item_dir / 'detail.html').write_text(html, encoding='utf-8', errors='replace')
        result['html_hits'] = scan_text(html, r.url)

        scripts = [urljoin(r.url, x) for x in SCRIPT_RE.findall(html)]
        scripts = list(dict.fromkeys(scripts))[:40]
        for idx, script_url in enumerate(scripts):
            try:
                sr = fetch(session, script_url)
                text = sr.text
                hits = scan_text(text, sr.url)
                if hits:
                    result['script_hits'].append({'url': sr.url, 'hits': hits})
                    (item_dir / f'script_{idx:02d}.js').write_text(text, encoding='utf-8', errors='replace')
            except Exception as exc:
                result['script_hits'].append({'url': script_url, 'error': str(exc)})

        candidate_urls = []
        for hit in result['html_hits']:
            candidate_urls.extend(hit.get('urls', []))
        for block in result['script_hits']:
            for hit in block.get('hits', []):
                candidate_urls.extend(hit.get('urls', []))
        # Keep SAMR-origin candidates and likely files/endpoints.
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
