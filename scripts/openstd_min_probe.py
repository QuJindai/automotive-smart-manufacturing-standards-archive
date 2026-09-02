#!/usr/bin/env python3
import hashlib
import http.cookiejar
import json
import pathlib
import time
import urllib.error
import urllib.request

HCNO = "8676EBC34F75CFFDF7EA4BC12517A007"
DETAIL_URL = f"https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno={HCNO}"
CAPTCHA_URL = f"http://c.gb688.cn/bzgk/gb/gc?_{int(time.time() * 1000)}"
PDF_URL = f"http://c.gb688.cn/bzgk/gb/viewGb?hcno={HCNO}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133 Safari/537.36"

out = {
    "hcno": HCNO,
    "detail_url": DETAIL_URL,
    "detail_ok": False,
    "download_button_present": False,
    "captcha_reached": False,
    "captcha_content_type": None,
    "captcha_bytes": 0,
    "captcha_sha256": None,
    "pdf_without_captcha": False,
    "pdf_probe_status": None,
    "pdf_probe_content_type": None,
    "pdf_probe_bytes": 0,
    "boundary": None,
}

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def fetch(url, headers=None, limit=None):
    req_headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with opener.open(req, timeout=30) as resp:
        data = resp.read() if limit is None else resp.read(limit)
        return resp.status, resp.headers, data

# 1) Official OpenSTD detail page.
status, headers, body = fetch(DETAIL_URL)
text = body.decode("utf-8", errors="ignore")
out["detail_http_status"] = status
out["detail_ok"] = status == 200 and "GB 15082-2008" in text and "汽车用车速表" in text
out["download_button_present"] = "下载标准" in text

# 2) Probe direct PDF without solving any captcha. Range keeps this bounded if supported.
try:
    status, headers, body = fetch(
        PDF_URL,
        headers={"Referer": DETAIL_URL, "Range": "bytes=0-1023"},
        limit=2048,
    )
    out["pdf_probe_status"] = status
    out["pdf_probe_content_type"] = headers.get("Content-Type")
    out["pdf_probe_bytes"] = len(body)
    out["pdf_without_captcha"] = body.startswith(b"%PDF-")
except urllib.error.HTTPError as e:
    out["pdf_probe_status"] = e.code
    out["pdf_probe_content_type"] = e.headers.get("Content-Type") if e.headers else None
except Exception as e:
    out["pdf_probe_error"] = f"{type(e).__name__}: {e}"

# 3) Reach the official captcha challenge, but do not solve or submit it.
try:
    status, headers, body = fetch(CAPTCHA_URL, headers={"Referer": DETAIL_URL})
    ctype = headers.get("Content-Type", "")
    out["captcha_http_status"] = status
    out["captcha_content_type"] = ctype
    out["captcha_bytes"] = len(body)
    out["captcha_sha256"] = hashlib.sha256(body).hexdigest() if body else None
    out["captcha_reached"] = status == 200 and len(body) > 0 and ("image" in ctype.lower() or body[:8] == b"\x89PNG\r\n\x1a\n")
except urllib.error.HTTPError as e:
    out["captcha_http_status"] = e.code
    out["captcha_content_type"] = e.headers.get("Content-Type") if e.headers else None
except Exception as e:
    out["captcha_error"] = f"{type(e).__name__}: {e}"

if out["pdf_without_captcha"]:
    out["boundary"] = "FULLY_AUTOMATABLE_NO_CAPTCHA_OBSERVED"
elif out["captcha_reached"]:
    out["boundary"] = "AUTOMATABLE_TO_CAPTCHA_MANUAL_INPUT_REQUIRED"
else:
    out["boundary"] = "FLOW_NOT_CONFIRMED"

path = pathlib.Path("artifacts/openstd_min_probe.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))

if not out["detail_ok"] or not out["download_button_present"]:
    raise SystemExit(2)
if not (out["pdf_without_captcha"] or out["captcha_reached"]):
    raise SystemExit(3)
