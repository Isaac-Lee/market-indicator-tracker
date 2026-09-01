"""python test_notify.py — 네트워크 없이 순수 로직만 검증."""
from notify_daily import healthcheck_target


def test_healthcheck_target():
    base = "https://hc-ping.com/abc-123"
    # 성공이면 주소 그대로
    assert healthcheck_target(base, True) == base
    # 실패면 /fail 을 붙여 즉시 알린다 — 기한까지 기다리지 않는다
    assert healthcheck_target(base, False) == base + "/fail"
    # 끝의 슬래시가 //fail 을 만들면 안 된다
    assert healthcheck_target(base + "/", False) == base + "/fail"
    assert healthcheck_target(base + "/", True) == base


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
