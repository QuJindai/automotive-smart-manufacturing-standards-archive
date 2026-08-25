#!/usr/bin/env python3
"""Download, validate, hash and optionally split public standards assets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.prepare_matrix import MAX_ARTIFACT_BYTES, load_manifest, validate_manifest

EVIDENCE_FIELDS = [
    "id",
    "filename",
    "source_url",
    "status",
    "error",
    "expected_size_bytes",
    "source_size_bytes",
    "source_sha256",
    "output_filename",
    "output_size_bytes",
    "output_sha256",
    "part_index",
    "part_total",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_magic(path: Path, kind: str) -> None:
    with path.open("rb") as handle:
        prefix = handle.read(5)
    if kind == "pdf" and prefix != b"%PDF-":
        raise ValueError(f"invalid PDF header for {path.name}")
    if kind == "zip" and prefix[:2] != b"PK":
        raise ValueError(f"invalid ZIP header for {path.name}")


def split_bounds(size: int, part_index: int, part_total: int) -> tuple[int, int]:
    if size <= 0:
        raise ValueError("size must be positive")
    if part_total < 2:
        raise ValueError("part_total must be >= 2")
    if not 0 <= part_index < part_total:
        raise ValueError("part_index out of range")
    start = (size * part_index) // part_total
    end = (size * (part_index + 1)) // part_total
    if end <= start:
        raise ValueError("split would create an empty part")
    return start, end


def write_part(source: Path, destination: Path, part_index: int, part_total: int) -> None:
    size = source.stat().st_size
    start, end = split_bounds(size, part_index, part_total)
    remaining = end - start
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("wb") as dst:
        src.seek(start)
        while remaining:
            chunk = src.read(min(1024 * 1024, remaining))
            if not chunk:
                raise IOError("unexpected EOF while writing split part")
            dst.write(chunk)
            remaining -= len(chunk)


def payload_size_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def enforce_payload_limit(path: Path, limit: int = MAX_ARTIFACT_BYTES) -> int:
    size = payload_size_bytes(path)
    if size > limit:
        raise ValueError(f"artifact payload {size} bytes exceeds limit {limit}")
    return size


def download_with_curl(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "curl",
        "-L",
        "--fail",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "20",
        "--max-time",
        "300",
        "-A",
        "Mozilla/5.0 GitHubActions-StandardsArchive",
        "-o",
        str(destination),
        url,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl failed with code {result.returncode}")


def _select_assets(assets: list[dict], mode: str, group: str, asset_id: str) -> list[dict]:
    if mode == "group":
        selected = [asset for asset in assets if asset["artifact_group"] == group and "split_parts" not in asset]
        if not selected:
            raise ValueError(f"no non-split assets found for group {group!r}")
        return selected
    selected = [asset for asset in assets if asset["id"] == asset_id and "split_parts" in asset]
    if len(selected) != 1:
        raise ValueError(f"split asset {asset_id!r} not found")
    return selected


def _write_evidence(out_dir: Path, rows: list[dict]) -> None:
    with (out_dir / "evidence.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVIDENCE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_fetch(
    manifest_path: Path,
    out_dir: Path,
    mode: str,
    group: str = "",
    asset_id: str = "",
    part_index: int = 0,
    part_total: int = 0,
) -> None:
    manifest = load_manifest(manifest_path)
    assets = validate_manifest(manifest)
    selected = _select_assets(assets, mode, group, asset_id)

    out_dir.mkdir(parents=True, exist_ok=True)
    evidence: list[dict] = []
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="standards-fetch-") as temp_name:
        temp_dir = Path(temp_name)
        for asset in selected:
            row = {field: "" for field in EVIDENCE_FIELDS}
            row.update(
                {
                    "id": asset["id"],
                    "filename": asset["filename"],
                    "source_url": asset["url"],
                    "status": "FAIL",
                    "expected_size_bytes": asset.get("expected_size_bytes", ""),
                    "part_index": part_index if mode == "split" else "",
                    "part_total": part_total if mode == "split" else "",
                }
            )
            try:
                source = temp_dir / asset["filename"]
                download_with_curl(asset["url"], source)
                validate_magic(source, asset["kind"])
                source_size = source.stat().st_size
                source_sha = sha256_file(source)
                row["source_size_bytes"] = source_size
                row["source_sha256"] = source_sha

                if mode == "split":
                    declared_total = asset["split_parts"]
                    if part_total != declared_total:
                        raise ValueError(
                            f"matrix part_total={part_total} does not match manifest split_parts={declared_total}"
                        )
                    output_name = f"{asset['filename']}.part{part_index:02d}of{part_total:02d}"
                    output = out_dir / output_name
                    write_part(source, output, part_index, part_total)
                    reconstruct = {
                        "source_filename": asset["filename"],
                        "source_size_bytes": source_size,
                        "source_sha256": source_sha,
                        "part_total": part_total,
                        "part_pattern": f"{asset['filename']}.partNNof{part_total:02d}",
                        "reconstruct_windows": f"copy /b {asset['filename']}.part00of{part_total:02d}+... {asset['filename']}",
                        "reconstruct_posix": f"cat {asset['filename']}.part*of{part_total:02d} > {asset['filename']}",
                    }
                    (out_dir / "reconstruct.json").write_text(
                        json.dumps(reconstruct, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                else:
                    output_name = asset["filename"]
                    output = out_dir / output_name
                    shutil.copy2(source, output)

                row["output_filename"] = output_name
                row["output_size_bytes"] = output.stat().st_size
                row["output_sha256"] = sha256_file(output)
                row["status"] = "OK"
            except Exception as exc:  # evidence should survive a failed asset
                row["error"] = str(exc).replace("\n", " ")
                errors.append(f"{asset['id']}: {exc}")
            evidence.append(row)

    _write_evidence(out_dir, evidence)
    enforce_payload_limit(out_dir)
    if errors:
        raise RuntimeError("; ".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="manifest/standards.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=("group", "split"), required=True)
    parser.add_argument("--group", default="")
    parser.add_argument("--asset-id", default="")
    parser.add_argument("--part-index", type=int, default=0)
    parser.add_argument("--part-total", type=int, default=0)
    args = parser.parse_args()

    run_fetch(
        manifest_path=Path(args.manifest),
        out_dir=Path(args.out),
        mode=args.mode,
        group=args.group,
        asset_id=args.asset_id,
        part_index=args.part_index,
        part_total=args.part_total,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
