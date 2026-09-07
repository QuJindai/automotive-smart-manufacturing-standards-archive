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
EXECUTOR_VERSION = "0.4.0"
USER_AGENT = f"DownloadExecutor/{EXECUTOR_VERSION} (+GitHubActions)"
SOURCE_SIZE_UNKNOWN = "SOURCE_SIZE_UNKNOWN"
SOURCE_FETCH_FAILED = "SOURCE_FETCH_FAILED"
INTEGRITY_ERROR = "INTEGRITY_ERROR"


class IntegrityError(ValueError):
    """The response cannot represent the complete, expected source."""


class SourcePageError(RuntimeError):
    """A landing/challenge page was returned instead of the requested binary."""


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
    error_code: str | None = None


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
    return result.status != "PASS" and result.error_code != INTEGRITY_ERROR


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
        if prefix.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            raise SourcePageError("source returned an HTML page instead of the requested file")
        raise IntegrityError(f"magic mismatch: expected {wanted}, got {actual}")


def validate_file(path: Path, kind: str | None, expected_size: int | None, expected_sha: str | None) -> tuple[int, str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        prefix = handle.read(64)
    validate_magic_prefix(prefix, kind)
    if size <= 0 or (expected_size and size != expected_size):
        raise IntegrityError(f"size mismatch: {size} != {expected_size}")
    digest = sha256_file(path)
    if expected_sha and digest.lower() != expected_sha.lower():
        raise IntegrityError("SHA256 mismatch")
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
            _check_source_page(response, asset.get("kind"))
            header_size = response.headers.get("Content-Length")
            transfer_size = int(asset.get("expected_size_bytes") or 0) or (int(header_size) if header_size and header_size.isdigit() else None)
            if transfer_size:
                _check_source_response(response, 0, transfer_size - 1, transfer_size, asset.get("kind"))
            while True:
                chunk = response.read(DEFAULT_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
        size, digest = validate_file(
            destination,
            asset.get("kind"),
            transfer_size,
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
            error_code=INTEGRITY_ERROR if isinstance(exc, IntegrityError) else SOURCE_FETCH_FAILED,
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
            error_code=INTEGRITY_ERROR if isinstance(exc, IntegrityError) else SOURCE_FETCH_FAILED,
            source_url_redacted=redact_url(url) if url else None,
        )


def query_drive_status(session_url: str, total: int) -> tuple[int, dict | None]:
    """Keep the completion receipt as well as the next byte offset."""
    try:
        with _request(
            session_url,
            method="PUT",
            headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"},
            data=b"",
            timeout=60,
        ) as response:
            if response.status in {200, 201}:
                data = json.loads(response.read().decode("utf-8"))
                return total, data
            raise RuntimeError(f"unexpected Drive session status {response.status}")
    except urllib.error.HTTPError as exc:
        if exc.code != 308:
            raise
        range_header = exc.headers.get("Range", "")
        match = re.search(r"bytes=0-(\d+)", range_header)
        return (int(match.group(1)) + 1 if match else 0), None


def query_drive_offset(session_url: str, total: int) -> int:
    """Compatibility helper for callers only interested in the byte offset."""
    return query_drive_status(session_url, total)[0]


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
        next_offset = int(match.group(1)) + 1 if match else 0
        return next_offset, None


def _source_prefix(url: str) -> bytes:
    with _request(url, headers={"Range": "bytes=0-63"}, timeout=60) as response:
        if response.status not in {200, 206}:
            raise RuntimeError(f"source prefix status {response.status}")
        return response.read(64)


def _check_source_response(source, start: int, end: int, total: int, kind: str | None = None) -> None:
    headers = source.headers
    error = None
    if source.status == 206:
        expected = f"bytes {start}-{end}/{total}"
        if headers.get("Content-Range", "") != expected:
            error = "source Content-Range mismatch"
    elif source.status != 200 or start != 0 or end != total - 1:
        error = "source did not return the requested range"
    length = headers.get("Content-Length")
    if length is not None and (not length.isdigit() or int(length) != end - start + 1):
        error = "source Content-Length mismatch"
    if error:
        # Error pages often omit or mislabel Content-Type. Sniff only a doomed
        # response; successful streams remain untouched for hashing/upload.
        if expected_magic(kind):
            validate_magic_prefix(source.read(64), kind)
        raise IntegrityError(error)


def _check_source_page(source, kind: str | None) -> None:
    if expected_magic(kind) and "text/html" in source.headers.get("Content-Type", "").lower():
        raise SourcePageError("source returned an HTML page instead of the requested file")


def _read_exact(source, size: int) -> bytes:
    chunks = []
    left = size
    while left:
        block = source.read(left)
        if not block:
            raise IntegrityError("unexpected source EOF")
        chunks.append(block)
        left -= len(block)
    return b"".join(chunks)


def _check_source_end(source) -> None:
    if source.read(1):
        raise IntegrityError("source contains bytes beyond expected size")


def _check_digest(digest: str, expected: str | None) -> None:
    if expected and digest.lower() != expected.lower():
        raise IntegrityError("SHA256 mismatch")


def _drive_ref(receipt: dict | None, filename: str, total: int, digest: str, *, completed_session=False) -> dict:
    if not isinstance(receipt, dict) or not receipt.get("id"):
        raise IntegrityError("completed Drive receipt file_id missing")
    if receipt.get("size") is not None and int(receipt["size"]) != total:
        raise IntegrityError("completed Drive receipt size mismatch")
    if completed_session and not re.fullmatch(r"[a-fA-F0-9]{64}", str(receipt.get("sha256Checksum") or "")):
        raise IntegrityError("completed Drive session checksum unavailable; retry with a new session")
    _check_digest(digest, receipt.get("sha256Checksum"))
    return {"file_id": str(receipt["id"]), "name": str(receipt.get("name") or filename),
            "size": total, "sha256": digest, "web_url": receipt.get("webViewLink")}


def _hash_complete_source(asset: dict, total: int) -> str:
    with _request(str(asset["source_url"]), timeout=300) as source:
        _check_source_response(source, 0, total - 1, total)
        digest = hashlib.sha256()
        for start, end in chunk_ranges(total):
            block = _read_exact(source, end - start + 1)
            if start == 0:
                validate_magic_prefix(block, asset.get("kind"))
            digest.update(block)
        _check_source_end(source)
    sha = digest.hexdigest()
    _check_digest(sha, asset.get("expected_sha256"))
    return sha


def upload_direct_resumable(asset: dict, session_url: str, chunk_size: int = DEFAULT_CHUNK) -> AssetResult:
    """Stream a source into Drive using the supplied one-file resumable session."""
    asset_id = str(asset.get("asset_id") or "")
    filename = str(asset.get("filename") or f"{asset_id}.bin")
    url = str(asset.get("source_url") or "")
    total = int(asset.get("expected_size_bytes") or 0) or source_size(url)
    if not total:
        return AssetResult(
            asset_id,
            filename,
            "FAIL",
            0,
            None,
            "drive-resumable",
            "source size unavailable",
            source_url_redacted=redact_url(url),
            error_code=SOURCE_SIZE_UNKNOWN,
        )
    if chunk_size % DRIVE_ALIGNMENT:
        chunk_size = max(DRIVE_ALIGNMENT, (chunk_size // DRIVE_ALIGNMENT) * DRIVE_ALIGNMENT)
    phase = "drive"
    offset = position = 0
    try:
        offset, receipt = query_drive_status(session_url, total)
        position = offset
        if offset > total:
            raise IntegrityError("Drive offset exceeds source size")
        if offset == total:
            sha = _hash_complete_source(asset, total)
            ref = _drive_ref(receipt, filename, total, sha, completed_session=True)
            return AssetResult(asset_id, filename, "PASS", total, sha, "drive-resumable-resume", drive_ref=ref, source_url_redacted=redact_url(url))
        if offset and not re.fullmatch(r"[a-fA-F0-9]{64}", str(asset.get("expected_sha256") or "")):
            raise IntegrityError("partial source resume requires an expected SHA256; retry with a new session")
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        phase = "source"
        with _request(url, headers=headers, timeout=300) as source:
            _check_source_page(source, asset.get("kind"))
            _check_source_response(source, offset, total - 1, total, asset.get("kind"))
            digest = hashlib.sha256()
            prefix_checked = False
            if offset:
                with _request(url, headers={"Range": f"bytes=0-{offset-1}"}, timeout=300) as prefix_source:
                    _check_source_response(prefix_source, 0, offset - 1, total)
                    for start, end in chunk_ranges(offset):
                        block = _read_exact(prefix_source, end - start + 1)
                        if not prefix_checked:
                            validate_magic_prefix(block, asset.get("kind"))
                            prefix_checked = True
                        digest.update(block)
                    _check_source_end(prefix_source)
            position = offset
            final_drive = None
            while position < total:
                need = min(chunk_size, total - position)
                phase = "source"
                buf = _read_exact(source, need)
                if not prefix_checked:
                    validate_magic_prefix(buf, asset.get("kind"))
                    prefix_checked = True
                digest.update(buf)
                if position + len(buf) == total:
                    # Do not finalize a truncated or hash-mismatched object.
                    _check_source_end(source)
                    _check_digest(digest.hexdigest(), asset.get("expected_sha256"))
                phase = "drive"
                next_position, drive_data = _put_drive_chunk(session_url, buf, position, total)
                if next_position != position + len(buf):
                    raise IntegrityError("Drive acknowledged an unexpected byte offset")
                position = next_position
                if drive_data is not None:
                    final_drive = drive_data
            sha = digest.hexdigest()
            if final_drive is None:
                _, final_drive = query_drive_status(session_url, total)
            drive_ref = _drive_ref(final_drive, filename, total, sha)
            return AssetResult(asset_id, filename, "PASS", total, sha, "drive-resumable", drive_ref=drive_ref, source_url_redacted=redact_url(url))
    except Exception as exc:
        code = INTEGRITY_ERROR if isinstance(exc, IntegrityError) else (
            SOURCE_FETCH_FAILED if phase == "source" and position == 0 else "TRANSFER_FAILED")
        return AssetResult(asset_id, filename, "FAIL", 0, None, "drive-resumable", str(exc)[:1000], source_url_redacted=redact_url(url), error_code=code)


def upload_staged_resumable(staged: AssetResult, asset: dict, session_url: str, chunk_size: int = DEFAULT_CHUNK) -> AssetResult:
    """Upload one already-downloaded and verified local snapshot to Drive."""
    asset_id = str(asset.get("asset_id") or staged.asset_id or "")
    filename = str(asset.get("filename") or staged.filename or f"{asset_id}.bin")
    url = str(asset.get("source_url") or "")
    if not staged.artifact_path:
        return AssetResult(asset_id, filename, "FAIL", 0, None, "drive-resumable-local", "staged artifact path unavailable", source_url_redacted=redact_url(url) if url else None)
    path = Path(staged.artifact_path)
    try:
        total, digest = validate_file(path, asset.get("kind"), staged.bytes if staged.bytes > 0 else None, staged.sha256)
        if total <= 0:
            raise ValueError("staged artifact is empty")
        if chunk_size % DRIVE_ALIGNMENT:
            chunk_size = max(DRIVE_ALIGNMENT, (chunk_size // DRIVE_ALIGNMENT) * DRIVE_ALIGNMENT)
        offset, receipt = query_drive_status(session_url, total)
        if offset > total:
            raise IOError("Drive offset exceeds staged artifact size")
        if offset == total:
            ref = _drive_ref(receipt, filename, total, digest, completed_session=True)
            return AssetResult(asset_id, filename, "PASS", total, digest, "drive-resumable-local-resume", drive_ref=ref, artifact_path=str(path), source_url_redacted=redact_url(url) if url else None)
        # The token is not persisted: only its one-way fingerprint identifies
        # which session owns this validated local snapshot.
        checkpoint = path.with_name(path.name + ".upload-state.json")
        identity = {"session_sha256": hashlib.sha256(session_url.encode()).hexdigest(),
                    "snapshot_sha256": digest, "size": total}
        if offset:
            saved = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else None
            if saved != identity:
                raise IntegrityError("partial upload snapshot identity unavailable or changed; retry with a new session")
        else:
            checkpoint.write_text(json.dumps(identity, separators=(",", ":")), encoding="utf-8")
        position = offset
        final_drive = None
        with path.open("rb") as source:
            source.seek(offset)
            while position < total:
                need = min(chunk_size, total - position)
                buf = source.read(need)
                if not buf:
                    raise IOError("unexpected staged artifact EOF")
                next_position, drive_data = _put_drive_chunk(session_url, buf, position, total)
                if next_position != position + len(buf):
                    raise IntegrityError("Drive acknowledged an unexpected byte offset")
                position = next_position
                if drive_data is not None:
                    final_drive = drive_data
        if final_drive is None:
            _, final_drive = query_drive_status(session_url, total)
        drive_ref = _drive_ref(final_drive, filename, total, digest)
        return AssetResult(asset_id, filename, "PASS", total, digest, "drive-resumable-local", drive_ref=drive_ref, artifact_path=str(path), source_url_redacted=redact_url(url) if url else None)
    except Exception as exc:
        return AssetResult(asset_id, filename, "FAIL", 0, None, "drive-resumable-local", str(exc)[:1000], artifact_path=str(path), source_url_redacted=redact_url(url) if url else None)


def run_small_asset(asset: dict, out_dir: Path) -> AssetResult:
    last: AssetResult | None = None
    for method in fallback_methods(asset):
        if method == "native":
            current = download_native(asset, out_dir)
        elif method == "browser":
            current = download_browser(asset, out_dir)
        else:
            current = AssetResult(asset_id=str(asset.get("asset_id") or ""), filename=str(asset.get("filename") or "download.bin"), status="FAIL", bytes=0, sha256=None, method=method, error="fallback method is delegated to control plane", source_url_redacted=redact_url(str(asset.get("source_url") or "")) if asset.get("source_url") else None)
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
            if result.status != "PASS" and result.error_code in {SOURCE_SIZE_UNKNOWN, SOURCE_FETCH_FAILED}:
                staged = run_small_asset(raw, out_dir)
                if staged.status == "PASS" and staged.bytes > 0 and staged.sha256 and staged.artifact_path:
                    result = upload_staged_resumable(staged, raw, str(session))
                elif staged.status == "PASS":
                    result = AssetResult(asset_id=str(raw.get("asset_id") or staged.asset_id or ""), filename=str(raw.get("filename") or staged.filename or "download.bin"), status="FAIL", bytes=0, sha256=None, method="drive-resumable-local", error="staged artifact metadata incomplete", artifact_path=staged.artifact_path, source_url_redacted=redact_url(str(raw.get("source_url") or "")) if raw.get("source_url") else None)
                else:
                    result = staged
        else:
            result = run_small_asset(raw, out_dir)
        results.append(result)
    drive_refs = [r.drive_ref for r in results if r.drive_ref and r.status == "PASS"]
    return {"download_id": job.get("download_id"), "assets": [asdict(r) for r in results], "drive_refs": drive_refs, "pass_count": sum(r.status == "PASS" for r in results), "fail_count": sum(r.status != "PASS" for r in results)}


def apply_drive_verification(data: dict, verification: dict) -> dict:
    """Normalize gateway failures so the control plane receives a terminal result."""
    verification = verification if isinstance(verification, dict) else {}
    references = verification.get("drive_refs")
    references = references if isinstance(references, list) else []
    by_id = {r.get("file_id"): r for r in references if isinstance(r, dict) and isinstance(r.get("file_id"), str)}
    verified = []
    for asset in data.get("assets", []):
        if asset.get("status") != "PASS" or not asset.get("drive_ref"):
            continue
        original = asset["drive_ref"]
        ref = by_id.get(original.get("file_id"))
        valid = verification.get("verified") is True and isinstance(ref, dict) and (
            ref.get("checksum_verified") is True and
            ref.get("name") == original.get("name") and
            ref.get("size") == asset.get("bytes") and
            ref.get("sha256") == asset.get("sha256"))
        if valid:
            asset["drive_ref"] = ref
            verified.append(ref)
        else:
            asset["status"] = "FAIL"
            asset["error_code"] = "DRIVE_VERIFICATION_FAILED"
            asset["error"] = "Independent Drive verification failed"
            asset["drive_ref"] = None
    data["drive_refs"] = verified
    data["pass_count"] = sum(a.get("status") == "PASS" for a in data.get("assets", []))
    data["fail_count"] = len(data.get("assets", [])) - data["pass_count"]
    data["drive_verified"] = bool(verified) and data["fail_count"] == 0
    if data["fail_count"]:
        data["executor_exit_code"] = 2
    return data


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
    print(json.dumps({"download_id": result["download_id"], "pass_count": result["pass_count"], "fail_count": result["fail_count"]}))
    return 0 if result["fail_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
