"""Fetcher 测试：限速、5xx 退避重试、4xx 不重试、令牌桶节流。"""

from __future__ import annotations

import time

import httpx
import pytest

from job_market.fetcher import Fetcher, FetcherConfig, TokenBucket


# --- TokenBucket ---


def test_token_bucket_first_take_immediate() -> None:
    clock_t = [0.0]
    sleep_calls: list[float] = []
    b = TokenBucket(rate=1.0, capacity=1.0, clock=lambda: clock_t[0])
    waited = b.take(sleep=sleep_calls.append)
    assert waited == 0.0
    assert sleep_calls == []


def test_token_bucket_rate_limits_subsequent_calls() -> None:
    clock_t = [0.0]
    sleep_calls: list[float] = []
    b = TokenBucket(rate=1.0, capacity=1.0, clock=lambda: clock_t[0])
    b.take(sleep=sleep_calls.append)  # 立刻拿走 1 个，此时桶空
    # 紧接着再要 1 个：应该等约 1 秒
    waited = b.take(sleep=sleep_calls.append)
    assert pytest.approx(waited, rel=1e-3) == 1.0
    assert sleep_calls == [pytest.approx(1.0, rel=1e-3)]


# --- Fetcher 重试 ---


def _make_fetcher(handler) -> Fetcher:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, timeout=5.0, headers={"User-Agent": "test"})
    cfg = FetcherConfig(default_qps=1000.0, max_retries=3, backoff_base=0.0, timeout_s=5.0)
    return Fetcher(cfg, client=client)


def test_5xx_then_200_retries_and_succeeds() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    f = _make_fetcher(handler)
    resp = f.get("https://api.example.com/x")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert calls["n"] == 3
    f.close()


def test_4xx_not_retried() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    f = _make_fetcher(handler)
    resp = f.get("https://api.example.com/x")
    assert resp.status_code == 404
    assert calls["n"] == 1
    f.close()


def test_5xx_exhausts_retries_returns_last_response() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    f = _make_fetcher(handler)
    resp = f.get("https://api.example.com/x")
    assert resp.status_code == 503
    assert calls["n"] == 4  # 1 次首发 + 3 次重试
    f.close()


def test_request_error_retries_then_raises() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=req)

    f = _make_fetcher(handler)
    with pytest.raises(httpx.ConnectError):
        f.get("https://api.example.com/x")
    assert calls["n"] == 4
    f.close()


# --- per-host 限速 ---


def test_per_host_rate_limit_paces_requests() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, headers={"User-Agent": "test"})
    cfg = FetcherConfig(default_qps=2.0, max_retries=0, backoff_base=0.0)
    f = Fetcher(cfg, client=client)

    t0 = time.monotonic()
    # 2 QPS、桶容量 = 2：前 2 个立刻通过，之后每个等约 0.5s。
    # 5 个请求总耗时 ≈ (5 - 2) * 0.5 = 1.5s
    for _ in range(5):
        f.get("https://api.example.com/x")
    elapsed = time.monotonic() - t0
    assert elapsed >= 1.4
    f.close()


def test_set_host_qps_overrides_default() -> None:
    f = _make_fetcher(lambda req: httpx.Response(200))
    f.set_host_qps("api.example.com", 50.0)
    bucket = f._bucket_for("api.example.com")
    assert bucket.rate == 50.0
    f.close()
