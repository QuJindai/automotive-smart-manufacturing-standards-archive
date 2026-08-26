from __future__ import annotations
import base64, hashlib, hmac, json

def _enc(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _dec(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def sign_compact(payload: bytes, secret: bytes) -> str:
    header=json.dumps({"alg":"HS256","typ":"JWT"},separators=(",",":"),sort_keys=True).encode()
    signing=f"{_enc(header)}.{_enc(payload)}".encode("ascii")
    sig=hmac.new(secret,signing,hashlib.sha256).digest()
    return signing.decode("ascii")+"."+_enc(sig)

def verify_compact(token: str, secret: bytes) -> tuple[bool, bytes | None]:
    try:
        header_b64,payload_b64,sig_b64=token.split(".")
        header=json.loads(_dec(header_b64))
        if header.get("alg") != "HS256":
            return False,None
        signing=f"{header_b64}.{payload_b64}".encode("ascii")
        expected=hmac.new(secret,signing,hashlib.sha256).digest()
        actual=_dec(sig_b64)
        if not hmac.compare_digest(expected,actual):
            return False,None
        return True,_dec(payload_b64)
    except Exception:
        return False,None
