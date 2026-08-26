#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

import ddddocr
import httpx
from PIL import Image, ImageFilter
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = "https://openstd.samr.gov.cn/bzgk/std"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36"
AAD = b"SAMR_RESEARCH_ARCHIVE_BATCH1_20260826"


def clean_code(raw: str) -> str:
    return "".join(c.upper() for c in raw if c.isalnum())[:4]


def solve_code(ocr: ddddocr.DdddOcr, image_bytes: bytes) -> str:
    """Last-resort CAPTCHA recognition for the official public download gate."""
    candidates = []
    try:
        candidates.append(clean_code(ocr.classification(image_bytes)))
    except Exception:
        pass
    if any(len(x) == 4 for x in candidates):
        return next(x for x in candidates if len(x) == 4)

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            gray = im.convert("L")
            w, h = gray.size
            variants = [
                gray.resize((w * 2, h * 2), Image.Resampling.LANCZOS),
                gray.resize((w * 2, h * 2), Image.Resampling.LANCZOS).filter(ImageFilter.MedianFilter(3)),
            ]
            for v in variants:
                for threshold in (120, 145, 170, 195):
                    bw = v.point(lambda p, t=threshold: 255 if p > t else 0)
                    buf = io.BytesIO()
                    bw.save(buf, format="PNG")
                    try:
                        code = clean_code(ocr.classification(buf.getvalue()))
                        if len(code) == 4:
                            return code
                        candidates.append(code)
                    except Exception:
                        pass
    except Exception:
        pass
    return max(candidates, key=len, default="")


def filename_for(target: dict) -> str:
    ref = target["reference"].replace("/", "_").replace(" ", "_")
    title = re.sub(r"[\\/:*?\"<>|]", "_", target["title"])
    return f"{ref}_{title}_SAMR官方原文.pdf"


def valid_pdf(data: bytes) -> bool:
    return len(data) > 500 and data[:5] == b"%PDF-"


def get_pdf(client: httpx.Client, hcno: str) -> bytes | None:
    r = client.get(f"{BASE}/viewGb", params={"hcno": hcno}, timeout=90)
    return r.content if valid_pdf(r.content) else None


def retrieve_one(ocr: ddddocr.DdddOcr, target: dict, plain_dir: Path) -> dict:
    hcno = target["hcno"]
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    }
    failures = []
    with httpx.Client(headers=headers, follow_redirects=True, timeout=45) as client:
        # Establish official download session.
        show = client.get(
            f"{BASE}/showGb",
            params={"type": "download", "hcno": hcno, "request_locale": "zh"},
            headers={"Referer": target["detail_url"]},
        )
        show.raise_for_status()

        direct = get_pdf(client, hcno)
        if direct:
            pdf = direct
            attempts = 0
            method = "showGb->viewGb"
        else:
            pdf = None
            attempts = 0
            method = "showGb->gc->verifyCode->viewGb"
            for attempt in range(1, 25):
                attempts = attempt
                show = client.get(
                    f"{BASE}/showGb",
                    params={"type": "download", "hcno": hcno, "request_locale": "zh"},
                    headers={"Referer": target["detail_url"]},
                )
                show.raise_for_status()
                cap = client.get(f"{BASE}/gc", params={"_": int(time.time() * 1000)})
                cap.raise_for_status()
                code = solve_code(ocr, cap.content)
                if len(code) != 4:
                    failures.append("ocr_short")
                    time.sleep(0.3)
                    continue
                vr = client.post(
                    f"{BASE}/verifyCode",
                    data={"verifyCode": code},
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": str(show.url)},
                )
                if vr.text.strip() != "success":
                    failures.append("verify_fail")
                    time.sleep(0.3)
                    continue
                candidate = get_pdf(client, hcno)
                if candidate:
                    pdf = candidate
                    break
                failures.append("verified_but_non_pdf")
                client.cookies.clear()
                time.sleep(0.5)

            if pdf is None:
                raise RuntimeError(f"failed after {attempts} attempts; recent={failures[-10:]}")

    name = filename_for(target)
    path = plain_dir / name
    path.write_bytes(pdf)
    return {
        "reference": target["reference"],
        "title": target["title"],
        "hcno": hcno,
        "detail_url": target["detail_url"],
        "download_endpoint": f"{BASE}/viewGb?hcno={hcno}",
        "download_method": method,
        "captcha_attempts": attempts,
        "filename": name,
        "bytes": len(pdf),
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "pdf_magic": True,
    }


def encrypt_zip(plain_zip: Path, public_key_path: Path, encrypted_dir: Path, manifest: dict) -> None:
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    aes_key = os.urandom(32)
    nonce = os.urandom(12)
    plain = plain_zip.read_bytes()
    ciphertext = AESGCM(aes_key).encrypt(nonce, plain, AAD)
    encrypted_key = public_key.encrypt(
        aes_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    encrypted_dir.mkdir(parents=True, exist_ok=True)
    (encrypted_dir / "samr-batch1.payload.aesgcm").write_bytes(nonce + ciphertext)
    (encrypted_dir / "samr-batch1.key.rsa-oaep").write_bytes(encrypted_key)
    envelope = {
        "schema_version": 1,
        "encryption": "AES-256-GCM; key wrapped with RSA-3072 OAEP-SHA256",
        "aad": AAD.decode("ascii"),
        "payload_layout": "12-byte nonce || AESGCM ciphertext+tag",
        "encrypted_payload_sha256": hashlib.sha256(nonce + ciphertext).hexdigest(),
        "encrypted_key_sha256": hashlib.sha256(encrypted_key).hexdigest(),
        "plaintext_zip_sha256": hashlib.sha256(plain).hexdigest(),
        "standards": [{"reference": r["reference"], "bytes": r["bytes"], "sha256": r["sha256"]} for r in manifest["results"]],
        "notice": "Artifact contains ciphertext only. Plain SAMR standard text is not uploaded to the public artifact.",
    }
    (encrypted_dir / "envelope.json").write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--public-key", required=True)
    ap.add_argument("--encrypted-out", required=True)
    args = ap.parse_args()

    targets = json.loads(Path(args.targets).read_text(encoding="utf-8"))["targets"]
    # HCNO is part of the official detail URL for this first batch.
    for t in targets:
        if "hcno" not in t:
            m = re.search(r"[?&]hcno=([A-Fa-f0-9]{32})", t["detail_url"])
            if not m:
                raise ValueError(f"missing hcno for {t['reference']}")
            t["hcno"] = m.group(1)

    work = Path("samr-private-work")
    plain_dir = work / "plain"
    if work.exists():
        shutil.rmtree(work)
    plain_dir.mkdir(parents=True)

    ocr = ddddocr.DdddOcr(show_ad=False)
    results = []
    failures = []
    for target in targets:
        print(f"START {target['reference']}", flush=True)
        try:
            r = retrieve_one(ocr, target, plain_dir)
            results.append(r)
            print(f"PASS {r['reference']} bytes={r['bytes']} sha256={r['sha256']}", flush=True)
        except Exception as exc:
            failures.append({"reference": target["reference"], "error": str(exc)})
            print(f"FAIL {target['reference']} {exc}", flush=True)

    manifest = {
        "schema_version": 1,
        "source": "SAMR National Standards Full-text Disclosure System",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "usage_note": "Personal learning/research archive; do not redistribute without authorization.",
        "success_count": len(results),
        "failure_count": len(failures),
        "results": results,
        "failures": failures,
    }
    (plain_dir / "SAMR_BATCH1_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (plain_dir / "SHA256SUMS.txt").write_text("\n".join(f"{r['sha256']}  {r['filename']}" for r in results) + "\n", encoding="utf-8")

    if failures or len(results) != len(targets):
        raise SystemExit(2)

    plain_zip = work / "SAMR_BATCH1_OFFICIAL_FULLTEXT.zip"
    with zipfile.ZipFile(plain_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(plain_dir.iterdir()):
            z.write(p, p.name)

    encrypt_zip(plain_zip, Path(args.public_key), Path(args.encrypted_out), manifest)

    # Ensure no plaintext file is ever passed to artifact upload.
    shutil.rmtree(plain_dir)
    plain_zip.unlink(missing_ok=True)
    print("SAMR_ENCRYPTED_RELAY=PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
