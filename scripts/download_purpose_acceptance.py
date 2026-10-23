"""Exercise the deployed MCP contract using the existing masked CI credential.

Staging tests admission only. Production submits three explicitly public test
sources through normal MCP calls; the regular executor and Drive verifier do
all byte transfer and verification. No credentials or response bodies are logged.
"""
import json
import os
import urllib.request


def main():
    environment = os.environ.get('ACCEPTANCE_ENVIRONMENT', 'staging')
    if environment not in ('staging', 'production'):
        raise ValueError('invalid environment')
    suffix = '-staging' if environment == 'staging' else ''
    endpoint = 'https://ezvfqrhzucjvkwnnbjux.supabase.co/functions/v1/download-mcp' + suffix + os.environ['MCP_PRIVATE_PATH']

    def rpc(method, params):
        payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
        request = urllib.request.Request(endpoint, payload, {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                value = json.load(response)
        except Exception:
            raise RuntimeError('MCP request failed; inspect service logs (endpoint redacted)') from None
        assert 'error' not in value, 'JSON-RPC failure'
        return value['result']

    def call(name, arguments, reject=False):
        result = rpc('tools/call', {'name': name, 'arguments': arguments})
        assert bool(result.get('isError')) == reject, f'{name}: unexpected admission result'
        return result.get('structuredContent', {})

    init = rpc('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'purpose-acceptance', 'version': '1'}})
    assert init['serverInfo']['version'] == '0.5.2-purpose-aware'
    definitions = rpc('tools/list', {})['tools']
    fields = next(t for t in definitions if t['name'] == 'resolve_download_sources')['inputSchema']['properties']['sources']['items']['properties']
    assert fields['redistributable']['type'] == 'boolean' and 'const' not in fields['redistributable']
    assert all(k in fields for k in ('publicly_accessible', 'access_restriction', 'rights_evidence_url'))
    print('PURPOSE_SCHEMA=PASS', flush=True)

    source = {
        'source_url': 'https://proceedings.neurips.cc/paper_files/paper/2017/file/3f5ee243547dee91fbd053c1c4a845aa-Paper.pdf',
        'filename': 'Attention-Is-All-You-Need-NeurIPS-2017.pdf',
        'official': True, 'redistributable': False, 'publicly_accessible': True,
        'access_restriction': 'none',
        'rights_evidence_url': 'https://proceedings.neurips.cc/paper_files/paper/2017/hash/3f5ee243547dee91fbd053c1c4a845aa-Abstract.html',
        'license_class': 'Official freely accessible proceedings PDF for personal reading; public redistribution permission not established',
    }
    destination = 'Google Drive/下载/插件验收/20261023-purpose-aware'
    if environment == 'staging':
        public = call('start_download', {'request': source['source_url'], 'constraints': {'purpose': 'public_redistribution'}})
        assert public['status'] == 'RESOLVING' and not public['assets']
        call('resolve_download_sources', {'download_id': public['download_id'], 'sources': [source]}, reject=True)
        personal = call('start_download', {'request': 'Purpose-aware generic publication acceptance', 'destination': destination})
        for patch in ({'access_restriction': 'paywall'}, {'access_restriction': 'login'}, {'publicly_accessible': False}, {'rights_evidence_url': ''}):
            call('resolve_download_sources', {'download_id': personal['download_id'], 'sources': [{**source, **patch}]}, reject=True)
        job = call('resolve_download_sources', {'download_id': personal['download_id'], 'sources': [source]})
        assert job['status'] == 'QUEUED' and job['purpose'] == 'personal_archive'
        assert job['assets'][0]['redistributable'] is False
        print('PURPOSE_STAGING_ADMISSION=PASS', flush=True)
        return

    paper = call('start_download', {'request': 'Attention Is All You Need, NeurIPS 2017; personal reading copy only', 'destination': destination, 'constraints': {'purpose': 'personal_archive'}})
    paper = call('resolve_download_sources', {'download_id': paper['download_id'], 'sources': [source]})
    assert paper['assets'][0]['redistributable'] is False
    print('ACCEPTANCE_JOB paper', paper['download_id'], flush=True)
    for label, url in (
        ('standard', 'https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.203.pdf'),
        ('large', 'https://download.blender.org/release/Blender4.5/blender-4.5.0-linux-x64.tar.xz'),
    ):
        job = call('start_download', {'request': url, 'destination': destination, 'constraints': {'purpose': 'personal_archive'}})
        assert job['purpose'] == 'personal_archive'
        print('ACCEPTANCE_JOB', label, job['download_id'], flush=True)


if __name__ == '__main__':
    main()
