import json
import os
import time
from pathlib import Path

import requests

HCNO = "8676EBC34F75CFFDF7EA4BC12517A007"
DETAIL_URL = f"https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno={HCNO}"
CAPTCHA_URL = "http://c.gb688.cn/bzgk/gb/gc"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36"
RUN_ID = os.environ["GITHUB_RUN_ID"]
OUT = Path("state/openstd-session-reuse")
OUT.mkdir(parents=True, exist_ok=True)

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})

# Establish the official OpenSTD entry context first.
r0 = s.get(DETAIL_URL, timeout=30)
r0.raise_for_status()

# Fetch the official download challenge without solving it.
r = s.get(
    CAPTCHA_URL,
    params={"_": int(time.time() * 1000)},
    headers={"Referer": DETAIL_URL},
    timeout=30,
)
r.raise_for_status()
ctype = r.headers.get("Content-Type", "")
if not ctype.lower().startswith("image/") or len(r.content) < 100:
    raise RuntimeError(f"captcha fetch did not return an image: content_type={ctype!r} bytes={len(r.content)}")

captcha_path = OUT / f"captcha-{RUN_ID}.png"
captcha_path.write_bytes(r.content)

cookies = []
for c in s.cookies:
    cookies.append({
        "name": c.name,
        "value": c.value,
        "domain": c.domain,
        "path": c.path,
        "secure": c.secure,
        "expires": c.expires,
    })
(OUT / f"cookies-{RUN_ID}.json").write_text(
    json.dumps({"run_id": RUN_ID, "hcno": HCNO, "cookies": cookies}, ensure_ascii=False),
    encoding="utf-8",
)
print(json.dumps({"captcha": str(captcha_path), "content_type": ctype, "bytes": len(r.content), "cookie_count": len(cookies)}))
