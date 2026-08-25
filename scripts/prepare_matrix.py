#!/usr/bin/env python3
"""Validate the public-asset manifest and build a GitHub Actions matrix."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

MAX_ARTIFACT_BYTES = 95 * 1024 * 1024
SUPPORTED_KINDS = {"pdf", "zip"}
REQUIRED_FIELDS = {
    "id",
    "title",
    "url",
    "filename",
    "kind",
    "artifact_group",
    "license_class",
    "redistributable",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


def _sanitize_artifact_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    value = value.strip("-.")
    if not value:
        raise ValueError("artifact name becomes empty after sanitization")
    return value[:100]


def load_manifest(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_manifest(manifest: dict) -> list[dict]:
    if manifest.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("assets must be a non-empty list")

    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()
    group_expected: dict[str, int] = defaultdict(int)

    for index, asset in enumerate(assets):
        missing = REQUIRED_FIELDS - set(asset)
        if missing:
            raise ValueError(f"asset[{index}] missing fields: {sorted(missing)}")

        asset_id = asset["id"]
        if not isinstance(asset_id, str) or not SAFE_ID.fullmatch(asset_id):
            raise ValueError(f"invalid asset id: {asset_id!r}")
        if asset_id in seen_ids:
            raise ValueError(f"duplicate asset id: {asset_id}")
        seen_ids.add(asset_id)

        filename = asset["filename"]
        if not isinstance(filename, str) or not filename.strip() or "/" in filename or "\\" in filename:
            raise ValueError(f"invalid filename for {asset_id}: {filename!r}")
        if filename in seen_filenames:
            raise ValueError(f"duplicate filename: {filename}")
        seen_filenames.add(filename)

        parsed = urlparse(asset["url"])
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"asset {asset_id} must use an https URL")

        if asset["kind"] not in SUPPORTED_KINDS:
            raise ValueError(f"asset {asset_id} has unsupported kind: {asset['kind']}")
        if asset["redistributable"] is not True:
            raise ValueError(f"asset {asset_id} is not marked redistributable=true")

        group = asset["artifact_group"]
        if not isinstance(group, str) or not group.strip():
            raise ValueError(f"asset {asset_id} has invalid artifact_group")
        _sanitize_artifact_name(group)

        expected = asset.get("expected_size_bytes")
        if expected is not None and (not isinstance(expected, int) or expected <= 0):
            raise ValueError(f"asset {asset_id} has invalid expected_size_bytes")

        split_parts = asset.get("split_parts")
        if split_parts is not None:
            if not isinstance(split_parts, int) or split_parts < 2:
                raise ValueError(f"asset {asset_id} split_parts must be an integer >= 2")
            if expected is not None and math.ceil(expected / split_parts) > MAX_ARTIFACT_BYTES:
                raise ValueError(
                    f"asset {asset_id} remains too large after split_parts={split_parts}; "
                    "increase split_parts"
                )
        elif expected is not None:
            group_expected[group] += expected

    for group, total in group_expected.items():
        if total > MAX_ARTIFACT_BYTES:
            raise ValueError(
                f"artifact_group {group!r} expected payload {total} bytes exceeds "
                f"{MAX_ARTIFACT_BYTES}; split the group"
            )

    return assets


def build_matrix(assets: list[dict]) -> dict:
    include: list[dict] = []

    groups = sorted({asset["artifact_group"] for asset in assets if "split_parts" not in asset})
    for group in groups:
        include.append(
            {
                "mode": "group",
                "group": group,
                "asset_id": "",
                "part_index": 0,
                "part_total": 0,
                "artifact_name": _sanitize_artifact_name(group),
            }
        )

    split_assets = sorted(
        (asset for asset in assets if "split_parts" in asset), key=lambda item: item["id"]
    )
    for asset in split_assets:
        total = asset["split_parts"]
        base = _sanitize_artifact_name(asset["artifact_group"])
        for part_index in range(total):
            include.append(
                {
                    "mode": "split",
                    "group": "",
                    "asset_id": asset["id"],
                    "part_index": part_index,
                    "part_total": total,
                    "artifact_name": f"{base}-part{part_index:02d}",
                }
            )

    return {"include": include}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="manifest/standards.json")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    assets = validate_manifest(manifest)
    print(json.dumps(build_matrix(assets), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
