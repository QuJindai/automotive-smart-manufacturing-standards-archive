#!/usr/bin/env python3
"""Generic download executor used by the public GitHub Actions runner.

The executor deliberately receives secret job payloads at runtime from the
Download MCP control plane. Public git descriptors contain only download_id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator

DRIVE_ALIGNMENT = 256 * 1024
DEFAULT_CHUNK = 8 * 1024 * 1024
USER_AGENT = "DownloadExecutor/0.2 (+GitHubActions)"


@dataclass
class AssetResult:
    asset_id: str
    filename: str
    status: str
    bytes: int
    sha256: str | None
    method: str
    error: str | None = None
    drive_ref: dict | None = None
    artifact_path: str | None = None
    source_url_redacted: str | None = None


def validate_descriptor(value: dict) -> str:
    if not isinstance(value, dict) or set(value) != {"download_id"}:
        raise ValueError("descriptor must contain exactly download_id")
    download_id = value.get("download_id")
    if not isinstance(download_id, str) or not re.fullmatch(r"download-[A-Za-z0-9]+", download_id):
        raise ValueError("invalid download_id")
    return download_id


def detect_magic(prefix: bytes) -> str:
    if prefix.startswith(b"%PDF-"):
        return "pdf"
    if prefix.startswith(b"GGUF"):
        return "gguf"
    if prefix.startswith(b"PK\x03\x04") or prefix.startswith(b"PK\x05\x06") or prefix.startswith(b"PK\x07\x08"):
        return "zip"
    stripped = prefix.lstrip()
    if stripped.startswith(b"{") or stripped.startswith(b"["):
        return "json"
    return "binary"


def chunk_ranges(total: int, chunk_size: int = DEFAULT_CHUNK) -> Iterator[tuple[int, int]]:
    if total < 0:
        raise ValueError("total must be >= 0")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    start = 0
    while start < total:
        end = min(total, start + chunk_size) - 1
        yield start, end
        start = end + 1


def redact_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def should_fallback(result: AssetResult) -> bool:
    return result.status != "PASS"


def fallback_methods(asset: dict) -> list[str]:
    evidence = asset.get("evidence") if isinstance(asset, dict) else None
    evidence = evidence if isinstance(evidence, dict) else {}
    raw = evidence.get("fallback_chain")
    methods = raw if isinstance(raw, list) else []
    normalized: list[str] = ["native"]
    for method in methods:
        value = str(method).strip().lower()
        if value in {"native", "browser", "alternate_egress"} and value not in normalized:
            normalized.append(value)
    if evidence.get("browser_hint") is True and "browser" not in normalized:
        normalized.append("browser")
    if evidence.get("browser_hint") is not True and not methods:
        return ["native"]
    return normalized


def sha256_file(path: Path, chunk_size: int = DEFAULT_CHUNK) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _request(url: str, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None, timeout: int = 120):
    merged = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, data=data, headers=merged, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def source_size(url: str) -> int | None:
    try:
        with _request(url, method="HEAD", timeout=30) as response:
            value = response.headers.get("Content-Length")
            if value and value.isdigit():
                return int(value)
    except Exception:
        pass
    try:
        with _request(url, headers={"Range": "bytes=0-0"}, timeout=30) as response:
            content_range = response.headers.get("Content-Range", "")
            match = re.search(r"/(\d+)$", content_range)
            if match:
                return int(match.group(1))
            length = response.headers.get("Content-Length")
            if response.status == 200 and length and length.isdigit():
                return int(length)
    except Exception:
        pass
    return None


def expected_magic(kind: str | None) -> str | None:
    normalized = (kind or "").lower()
    if normalized in {"pdf", "gguf", "zip"}:
        return normalized
    return None


def validate_magic_prefix(prefix: bytes, kind: str | None) -> None:
    wanted = expected_magic(kind)
    if not wanted:
        return
    actual = detect_magic(prefix[:64])
    if actual != wanted:
        raise ValueError(f"magic mismatch: expected {wanted}, got {actual}")


def validate_file(path: Path, kind: str | None, expected_size: int | None, expected_sha: str | None) -> tuple[int, str]:
    size = path.stat().st_size
    if expected_size and size != expected_size:
        raise ValueError(f"size mismatch: {size} != {expected_size}")
    with path.open("rb") as handle:
        prefix = handle.read(64)
    validate_magic_prefix(prefix, kind)
    digest = sha256_file(path)
    if expected_sha and digest.lower() != expected_sha.lower():
        raise ValueError("SHA256 mismatch")
    return size, digest


def download_native(asset: dict, out_dir: Path) -> AssetResult:
    asset_id = str(asset.get("asset_id") or "")
    filename = str(asset.get("filename") or f"{asset_id}.bin")
    url = str(asset.get("source_url") or "")
    destination = out_dir / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        headers = {}
        evidence = asset.get("evidence") or {}
        if isinstance(evidence, dict) and evidence.get("referer"):
            headers["Referer"] = str(evidence["referer"])
        with _request(url, headers=headers, timeout=300) as response, destination.open("wb") as handle:
            while True:
                chunk = response.read(DEFAULT_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
        size, digest = validate_file(
            destination,
            asset.get("kind"),
            int(asset["expected_size_bytes"]) if asset.get("expected_size_bytes") else None,
            str(asset["expected_sha256"]) if asset.get("expected_sha256") else None,
        )
        return AssetResult(
            asset_id=asset_id,
            filename=filename,
            status="PASS",
            bytes=size,
            sha256=digest,
            method="native",
            artifact_path=str(destination),
            source_url_redacted=redact_url(url),
        )
    except Exception as exc:
        destination.unlink(missing_ok=True)
        return AssetResult(
            asset_id=asset_id,
            filename=filename,
            status="FAIL",
            bytes=0,
            sha256=None,
            method="native",
            error=str(exc)[:1000],
            source_url_redacted=redact_url(url) if url else None,
        )


def download_browser(asset: dict, out_dir: Path) -> AssetResult:
    asset_id = str(asset.get("asset_id") or "")
    filename = str(asset.get("filename") or f"{asset_id}.bin")
    url = str(asset.get("source_url") or "")
    destination = out_dir / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        helper = Path(__file__).with_name("download_browser.mjs")
        proc = subprocess.run(
            ["node", str(helper), str(destination)],
            input=json.dumps(asset, separators=(",", ":")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "browser helper failed")[-1000:])
        size, digest = validate_file(
            destination,
            asset.get("kind"),
            int(asset["expected_size_bytes"]) if asset.get("expected_size_bytes") else None,
            str(asset["expected_sha256"]) if asset.get("expected_sha256") else None,
        )
        return AssetResult(
            asset_id=asset_id,
            filename=filename,
            status="PASS",
            bytes=size,
            sha256=digest,
            method="browser",
            artifact_path=str(destination),
            source_url_redacted=redact_url(url),
        )
    except Exception as exc:
        destination.unlink(missing_ok=True)
        return AssetResult(
            asset_id=asset_id,
            filename=filename,
            status="FAIL",
            bytes=0,
            sha256=None,
            method="browser",
            error=str(exc)[:1000],
            source_url_redacted=redact_url(url) if url else None,
        )


def query_drive_offset(session_url: str, total: int) -> int:
    """Return next byte offset for a resumable upload session."""
    try:
        with _request(
            session_url,
            method="PUT",
            headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"},
            data=b"",
            timeout=60,
        ) as response:
            if response.status in {200, 201}:
                return total
            return 0
    except urllib.error.HTTPError as exc:
        if exc.code != 308:
            raise
        range_header = exc.headers.get("Range", "")
        match = re.search(r"bytes=0-(\d+)", range_header)
        return int(match.group(1)) + 1 if match else 0


def _put_drive_chunk(session_url: str, chunk: bytes, start: int, total: int) -> tuple[int, dict | None]:
    end = start + len(chunk) - 1
    headers = {
        "Content-Length": str(len(chunk)),
        "Content-Type": "application/octet-stream",
        "Content-Range": f"bytes {start}-{end}/{total}",
    }
    try:
        with _request(session_url, method="PUT", headers=headers, data=chunk, timeout=300) as response:
            body = response.read()
            if response.status not in {200, 201}:
                raise RuntimeError(f"unexpected Drive status {response.status}")
            data = json.loads(body.decode("utf-8")) if body else {}
            return end + 1, data
    except urllib.error.HTTPError as exc:
        if exc.code != 308:
            raise
        range_header = exc.headers.get("Range", "")
        match = re.search(r"bytes=0-(\d+)", range_header)
        next_offset = int(match.group(1)) + 1 if match else end + 1
        return next_offset, None


def _source_prefix(url: str) -> bytes:
    with _request(url, headers={"Range": "bytes=0-63"}, timeout=60) as response:
        if response.status not in {200, 206}:
            raise RuntimeError(f"source prefix status {response.status}")
        return response.read(64)


def upload_direct_resumable(asset: dict, session_url: str, chunk_size: int = DEFAULT_CHUNK) -> AssetResult:
    """Stream a source into Drive using the supplied one-file resumable session."""
    asset_id = str(asset.get("asset_id") or "")
    filename = str(asset.get("filename") or f"{asset_id}.bin")
    url = str(asset.get("source_url") or "")
    total = int(asset.get("expected_size_bytes") or 0) or source_size(url)
    if not total:
        return AssetResult(asset_id, filename, "FAIL", 0, None, "drive-resumable", "source size unavailable", source_url_redacted=redact_url(url))
    if chunk_size % DRIVE_ALIGNMENT:
        chunk_size = max(DRIVE_ALIGNMENT, (chunk_size // DRIVE_ALIGNMENT) * DRIVE_ALIGNMENT)
    try:
        offset = query_drive_offset(session_url, total)
        if offset >= total:
            validate_magic_prefix(_source_prefix(url), asset.get("kind"))
            return AssetResult(asset_id, filename, "PASS", total, asset.get("expected_sha256"), "drive-resumable-resume", drive_ref={"size": total})
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with _request(url, headers=headers, timeout=300) as source:
            if offset and source.status != 206:
                raise RuntimeError("source ignored Range during resume")
            digest = hashlib.sha256()
            prefix_checked = False
            if offset:
                with _request(url, headers={"Range": f"bytes=0-{offset-1}"}, timeout=300) as prefix_source:
                    if prefix_source.status != 206:
                        raise RuntimeError("source does not support deterministic Range hashing")
                    while True:
                        block = prefix_source.read(DEFAULT_CHUNK)
                        if not block:
                            break
                        if not prefix_checked:
                            validate_magic_prefix(block, asset.get("kind"))
                            prefix_checked = True
                        digest.update(block)
            position = offset
            final_drive = None
            while position < total:
                need = min(chunk_size, total - position)
                buf = source.read(need)
                if not buf:
                    raise IOError("unexpected source EOF")
                while len(buf) < need:
                    more = source.read(need - len(buf))
                    if not more:
                        raise IOError("unexpected source EOF")
                    buf += more
                if not prefix_checked:
                    validate_magic_prefix(buf, asset.get("kind"))
                    prefix_checked = True
                digest.update(buf)
                next_position, drive_data = _put_drive_chunk(session_url, buf, position, total)
                if next_position < position + len(buf):
                    raise IOError("Drive acknowledged fewer bytes than supplied")
                position = next_position
                if drive_data is not None:
                    final_drive = drive_data
            sha = digest.hexdigest()
            expected_sha = str(asset.get("expected_sha256") or "")
            if expected_sha and sha.lower() != expected_sha.lower():
                raise ValueError("SHA256 mismatch after direct upload")
            drive_ref = {
                "file_id": str((final_drive or {}).get("id") or ""),
                "name": str((final_drive or {}).get("name") or filename),
                "size": total,
                "sha256": sha,
                "web_url": (final_drive or {}).get("webViewLink"),
            }
            return AssetResult(asset_id, filename, "PASS", total, sha, "drive-resumable", drive_ref=drive_ref, source_url_redacted=redact_url(url))
    except Exception as exc:
        return AssetResult(asset_id, filename, "FAIL", 0, None, "drive-resumable", str(exc)[:1000], source_url_redacted=redact_url(url))


def run_small_asset(asset: dict, out_dir: Path) -> AssetResult:
    last: AssetResult | None = None
    for method in fallback_methods(asset):
        if method == "native":
            current = download_native(asset, out_dir)
        elif method == "browser":
            current = download_browser(asset, out_dir)
        else:
            current = AssetResult(
                asset_id=str(asset.get("asset_id") or ""),
                filename=str(asset.get("filename") or "download.bin"),
                status="FAIL",
                bytes=0,
                sha256=None,
                method=method,
                error="fallback method is delegated to control plane",
                source_url_redacted=redact_url(str(asset.get("source_url") or "")) if asset.get("source_url") else None,
            )
        last = current
        if not should_fallback(current):
            return current
    assert last is not None
    return last


def run_job(job: dict, out_dir: Path) -> dict:
    assets = job.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("job has no assets")
    sessions = job.get("upload_sessions") or {}
    results: list[AssetResult] = []
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        session = sessions.get(str(raw.get("asset_id"))) if isinstance(sessions, dict) else None
        if session:
            result = upload_direct_resumable(raw, str(session))
            if result.status != "PASS" and result.error == "source size unavailable":
                staged = run_small_asset(raw, out_dir)
                if staged.status == "PASS" and staged.bytes > 0 and staged.sha256:
                    retry_asset = dict(raw)
                    retry_asset["expected_size_bytes"] = staged.bytes
                    retry_asset["expected_sha256"] = staged.sha256
                    result = upload_direct_resumable(retry_asset, str(session))
                else:
                    result = staged
        else:
            result = run_small_asset(raw, out_dir)
        results.append(result)
    drive_refs = [r.drive_ref for r in results if r.drive_ref and r.status == "PASS"]
    return {
        "download_id": job.get("download_id"),
        "assets": [asdict(r) for r in results],
        "drive_refs": drive_refs,
        "pass_count": sum(r.status == "PASS" for r in results),
        "fail_count": sum(r.status != "PASS" for r in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = run_job(job, out_dir)
    Path(args.result).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "download_id": result["download_id"],
        "pass_count": result["pass_count"],
        "fail_count": result["fail_count"],
    }))
    return 0 if result["fail_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())