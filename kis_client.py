"""Minimal Korea Investment (KIS) Open API client: token cache + GET helper."""
import json
import os
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
# 키 파일 이름은 둘 다 허용 (APP Key / APP Secret / ECOS Key / OilPriceAPI Key 줄)
KEY_FILE = next((p for p in (ROOT / "API-KEY.txt", ROOT / "KIS-API-KEY.txt") if p.exists()),
                ROOT / "API-KEY.txt")

BASE = {
    "prod": "https://openapi.koreainvestment.com:9443",
    "vps": "https://openapivts.koreainvestment.com:29443",
}
TOKEN_FILE = Path.home() / ".kis_token.json"
MIN_INTERVAL = 0.35  # 실계좌 시세 API는 체감 초당 3건 수준에서 EGW00201이 난다
RATE_LIMIT_CODE = "EGW00201"


def read_key(label, env_var):
    """환경변수 우선, 없으면 KIS-API-KEY.txt 의 `<label>: 값` 줄에서 읽는다."""
    if os.environ.get(env_var):
        return os.environ[env_var]
    if not KEY_FILE.exists():
        return None
    found = re.search(rf"{label}\s*[:=]\s*(\S+)", KEY_FILE.read_text(), re.I)
    return found.group(1) if found else None


def _credentials():
    key = read_key(r"APP\s*Key", "KIS_APP_KEY")
    secret = read_key(r"APP\s*Secret", "KIS_APP_SECRET")
    if not (key and secret):
        raise SystemExit("KIS_APP_KEY/KIS_APP_SECRET 환경변수 또는 KIS-API-KEY.txt('APP Key:', 'APP Secret:') 필요")
    return key, secret


class KIS:
    def __init__(self, env=None):
        env = env or os.environ.get("KIS_ENV", "prod")
        self.base = BASE[env]
        self.key, self.secret = _credentials()
        self.token = self._token()
        self._last_call = 0.0

    def _token(self):
        if TOKEN_FILE.exists():
            cached = json.loads(TOKEN_FILE.read_text())
            if cached.get("key") == self.key and cached.get("exp", 0) > time.time() + 600:
                return cached["token"]
        res = requests.post(
            f"{self.base}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret},
            timeout=10,
        )
        res.raise_for_status()
        body = res.json()
        TOKEN_FILE.write_text(
            json.dumps(
                {
                    "token": body["access_token"],
                    "exp": time.time() + int(body.get("expires_in", 86400)),
                    "key": self.key,
                }
            )
        )
        TOKEN_FILE.chmod(0o600)
        return body["access_token"]

    def get(self, path, tr_id, params, tr_cont="", retries=3):
        for attempt in range(retries):
            try:
                return self._get(path, tr_id, params, tr_cont)
            except RuntimeError as exc:
                if RATE_LIMIT_CODE not in str(exc) or attempt == retries - 1:
                    raise
                time.sleep(1 + attempt)

    def _get(self, path, tr_id, params, tr_cont=""):
        wait = MIN_INTERVAL - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        res = requests.get(
            self.base + path,
            headers={
                "authorization": f"Bearer {self.token}",
                "appkey": self.key,
                "appsecret": self.secret,
                "tr_id": tr_id,
                "tr_cont": tr_cont,
                "custtype": "P",
            },
            params=params,
            timeout=15,
        )
        self._last_call = time.time()
        try:
            body = res.json()
        except ValueError:
            # 일부 오류 응답은 깨진 JSON(`{rt_cd:"1",...}`)으로 온다 -> 메시지만 뽑아 올린다
            msg = re.search(r'"msg1"\s*:\s*"([^"]*)"', res.text)
            code = re.search(r'"msg_cd"\s*:\s*"([^"]*)"', res.text)
            raise RuntimeError(
                f"{tr_id} failed: {code.group(1) if code else res.status_code} "
                f"{msg.group(1) if msg else res.text[:120]}"
            ) from None
        # KIS는 업무 오류도 HTTP 500으로 주므로 본문 메시지를 먼저 살린다
        if body.get("rt_cd") not in (None, "0"):
            raise RuntimeError(f"{tr_id} failed: {body.get('msg_cd')} {body.get('msg1')}")
        res.raise_for_status()
        return body
