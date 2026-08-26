from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def artifact_entry(output_dir: Path, path: Path, artifact_id: str, mime_type: str, source_system: str='p-aas-reference') -> dict:
    path=path.resolve(); output_dir=output_dir.resolve()
    return {
        'artifact_id':artifact_id,
        'name':path.name,
        'uri':path.relative_to(output_dir).as_posix(),
        'sha256':sha256_file(path),
        'mime_type':mime_type,
        'created_at':now_iso(),
        'source_system':source_system,
    }


def assertion(assertion_id: str, passed: bool, expected: Any=None, observed: Any=None, message: str | None=None) -> dict:
    return {'assertion_id':assertion_id,'status':'PASS' if passed else 'FAIL','expected':expected,'observed':observed,'message':message}


def test_result(test_id: str, level: str, passed: bool, linked_rule_ids: list[str], assertions: list[dict], artifacts: list[dict], observations: str | None=None, blocked: bool=False) -> dict:
    result='BLOCKED' if blocked else ('PASS' if passed else 'FAIL')
    return {
        'test_id':test_id,'level':level,'result':result,'executed_at':now_iso(),'executor':'p-aas-reference-v1',
        'linked_rule_ids':linked_rule_ids,'metrics':{},'observations':observations,'assertions':assertions,'artifacts':artifacts,'deviations':[]
    }
