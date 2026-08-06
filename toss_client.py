"""Minimal Toss Securities Open API client: token cache + GET helper.

문서: https://developers.tossinvest.com/docs (OpenAPI JSON:
https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)

키는 환경변수(TOSS_CLIENT_ID / TOSS_CLIENT_SECRET) 또는 API-KEY.txt 의
`Toss Client ID:` / `Toss Client Secret:` 줄에서 읽는다.
"""
import json
import time
from pathlib import Path

import requests

from kis_client import read_key

BASE = "https://openapi.tossinvest.com"
TOKEN_FILE = Path.home() / ".toss_token.json"
MIN_INTERVAL = 0.21  # 차트 API가 가장 빡빡하다(초당 5회) -> 0.21s 간격


def _credentials():
    key = read_key(r"Toss\s*Client\s*ID", "TOSS_CLIENT_ID")
    secret = read_key(r"Toss\s*Client\s*Secret", "TOSS_CLIENT_SECRET")
    if not (key and secret):
        raise SystemExit(
            "TOSS_CLIENT_ID/TOSS_CLIENT_SECRET 환경변수 또는 "
            "API-KEY.txt('Toss Client ID:', 'Toss Client Secret:') 필요"
        )
    return key, secret


class Toss:
    def __init__(self):
        self.key, self.secret = _credentials()
        self.token = self._token()
        self._last_call = 0.0

    def _token(self):
        # client 당 유효 토큰이 1개뿐이라(재발급 시 이전 토큰 즉시 무효) 캐시가 사실상 필수다.
        if TOKEN_FILE.exists():
            cached = json.loads(TOKEN_FILE.read_text())
            if cached.get("key") == self.key and cached.get("exp", 0) > time.time() + 600:
                return cached["token"]
        res = requests.post(
            f"{BASE}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.key,
                "client_secret": self.secret,
            },
            timeout=10,
        )
        if res.status_code == 403:
            raise RuntimeError(
                "토큰 발급 403: 토스증권 WTS > 설정 > Open API > 허용 IP 관리에 현재 공인 IP를 등록해야 한다"
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

    def get(self, path, params=None, retries=4):
        for attempt in range(retries):
            wait = MIN_INTERVAL - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            res = requests.get(
                BASE + path,
                headers={"Authorization": f"Bearer {self.token}"},
                params=params or {},
                timeout=20,
            )
            self._last_call = time.time()
            if res.status_code == 429 and attempt < retries - 1:
                time.sleep(float(res.headers.get("Retry-After", 0)) or 2**attempt)
                continue
            if res.status_code == 401 and attempt < retries - 1:
                TOKEN_FILE.unlink(missing_ok=True)  # 만료/무효화 -> 재발급 후 재시도
                self.token = self._token()
                continue
            if not res.ok:
                err = (res.json().get("error") or {}) if res.headers.get(
                    "content-type", ""
                ).startswith("application/json") else {}
                raise RuntimeError(
                    f"{path} failed: {res.status_code} {err.get('code', '')} "
                    f"{err.get('message', res.text[:120])}"
                )
            return res.json()
