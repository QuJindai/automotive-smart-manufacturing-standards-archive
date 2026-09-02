#!/usr/bin/env python3
import http.cookiejar
import time
import urllib.request

HCNO = "8676EBC34F75CFFDF7EA4BC12517A007"
DETAIL_URL = f"https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno={HCNO}"
CAPTCHA_URL = f"http://c.gb688.cn/bzgk/gb/gc?_{int(time.time() * 1000)}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133 Safari/537.36"

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def get(url, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with opener.open(req, timeout=30) as r:
        return r.status, r.headers, r.read()

status, headers, body = get(DETAIL_URL)
text = body.decode("utf-8", errors="ignore")
assert status == 200
assert "GB 15082-2008" in text
assert "下载标准" in text

status, headers, body = get(CAPTCHA_URL, {"Referer": DETAIL_URL})
ctype = headers.get("Content-Type", "")
print(f"captcha_status={status}")
print(f"captcha_content_type={ctype}")
print(f"captcha_bytes={len(body)}")
assert status == 200
assert len(body) > 0
assert "image" in ctype.lower() or body.startswith(b"\x89PNG\r\n\x1a\n")
print("OPENSTD_CAPTCHA_REACHED=PASS")
