import argparse
import json
from pathlib import Path
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0"
STD1 = ("GB 15082-2008", "8676EBC34F75CFFDF7EA4BC12517A007")
STD2 = ("GB 4599-2024", "D88797E512723F8CBF170A20E81F27AD")


def load_state(root: Path):
    candidates = sorted(root.rglob("*.json"))
    errors = []
    for p in candidates:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{p.name}: {e}")
            continue
        if isinstance(data, dict) and any(k in data for k in ("cookies", "cookie_dict", "session_cookies", "cookie_jar")):
            return p, data, errors
        if isinstance(data, dict) and "base_url" in data:
            return p, data, errors
    raise RuntimeError(f"No usable session state JSON found. files={[str(x) for x in candidates]} errors={errors}")


def restore_cookies(session: requests.Session, value):
    if value is None:
        return 0
    count = 0
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (str, int, float)):
                session.cookies.set(str(k), str(v))
                count += 1
        return count
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict) or "name" not in item or "value" not in item:
                continue
            kwargs = {}
            if item.get("domain"):
                kwargs["domain"] = item["domain"]
            if item.get("path"):
                kwargs["path"] = item["path"]
            session.cookies.set(str(item["name"]), str(item["value"]), **kwargs)
            count += 1
        return count
    return 0


def probe_pdf(session, base_url, item):
    name, hcno = item
    referer = f"https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno={hcno}"
    try:
        with session.get(base_url + "viewGb", params={"hcno": hcno}, headers={"Referer": referer}, stream=True, allow_redirects=True, timeout=35) as r:
            prefix = next(r.iter_content(chunk_size=4096), b"")
            ctype = r.headers.get("Content-Type", "")
            dispo = r.headers.get("Content-Disposition", "")
            is_pdf = prefix.startswith(b"%PDF") or "application/pdf" in ctype.lower() or ".pdf" in dispo.lower()
            body_hint = prefix[:240].decode("utf-8", "ignore").replace("\n", " ").replace("\r", " ")
            return {
                "standard": name,
                "hcno": hcno,
                "status_code": r.status_code,
                "final_url": r.url.split("?")[0],
                "content_type": ctype,
                "content_disposition": dispo,
                "first_chunk_bytes": len(prefix),
                "is_pdf": bool(is_pdf),
                "body_hint": body_hint if not is_pdf else "%PDF...",
            }
    except Exception as e:
        return {"standard": name, "hcno": hcno, "error": repr(e), "is_pdf": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-dir", required=True)
    ap.add_argument("--captcha-file", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    artifact_dir = Path(args.artifact_dir)
    answer = Path(args.captcha_file).read_text(encoding="utf-8").strip()
    state_path, state, parse_errors = load_state(artifact_dir)

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    if isinstance(state.get("headers"), dict):
        for k, v in state["headers"].items():
            if isinstance(k, str) and isinstance(v, str) and k.lower() not in ("cookie", "authorization"):
                s.headers[k] = v
    cookie_value = state.get("cookies", state.get("cookie_dict", state.get("session_cookies", state.get("cookie_jar"))))
    cookie_count = restore_cookies(s, cookie_value)
    base_url = state.get("base_url") or "https://c.gb688.cn/bzgk/gb/"
    if not base_url.endswith("/"):
        base_url += "/"

    result = {
        "state_file": state_path.name,
        "cookie_count": cookie_count,
        "base_url": base_url.split("?", 1)[0],
        "parse_errors": parse_errors,
        "captcha_answer_source": "user_provided",
    }

    try:
        vr = s.post(base_url + "verifyCode", data={"verifyCode": answer, "agreeIECTips": "true"}, timeout=35, allow_redirects=True)
        verify_text = vr.text.strip()
        verify_ok = verify_text == "success"
        result["verify"] = {"status_code": vr.status_code, "ok": verify_ok, "response": verify_text[:120]}
    except Exception as e:
        result["verify"] = {"ok": False, "error": repr(e)}
        verify_ok = False

    if verify_ok:
        first = probe_pdf(s, base_url, STD1)
        second = probe_pdf(s, base_url, STD2)
        result["first"] = first
        result["second"] = second
        if first.get("is_pdf") and second.get("is_pdf"):
            verdict = "SESSION_REUSE_CONFIRMED"
        elif first.get("is_pdf") and not second.get("is_pdf"):
            verdict = "SECOND_STANDARD_BLOCKED_AFTER_FIRST"
        elif not first.get("is_pdf"):
            verdict = "VERIFIED_BUT_FIRST_DOWNLOAD_NOT_PDF"
        else:
            verdict = "INCONCLUSIVE"
    else:
        verdict = "CAPTCHA_REJECTED_OR_EXPIRED"
    result["verdict"] = verdict

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
