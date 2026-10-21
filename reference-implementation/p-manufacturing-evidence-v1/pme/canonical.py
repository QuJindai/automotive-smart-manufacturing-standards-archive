from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_record_bytes(record: dict[str, Any]) -> bytes:
    candidate = copy.deepcopy(record)
    integrity = dict(candidate.get("integrity") or {})
    integrity.pop("record_sha256", None)
    candidate["integrity"] = integrity
    return canonical_json_bytes(candidate)


def record_sha256(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_record_bytes(record)).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def package_sha256(package: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(package)).hexdigest()
