"""robots.txt 检查：allow / deny 决策、缓存、404 视为放行。"""

from __future__ import annotations

import httpx

from job_market.fetcher import Fetcher, FetcherConfig


def _make_fetcher_with_robots(robots_text: str | None) -> Fetcher:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            if robots_text is None:
                return httpx.Response(404)
            return httpx.Response(200, text=robots_text)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, headers={"User-Agent": "test-bot/1.0"})
    cfg = FetcherConfig(default_qps=1000.0, max_retries=0, user_agent="test-bot/1.0")
    return Fetcher(cfg, client=client)


def test_allow_when_no_robots_txt() -> None:
    f = _make_fetcher_with_robots(None)
    assert f.check_robots("https://example.com/some/path") is True
    f.close()


def test_allow_when_robots_silent_about_path() -> None:
    f = _make_fetcher_with_robots("User-agent: *\nDisallow: /admin/\n")
    assert f.check_robots("https://example.com/jobs/list") is True
    f.close()


def test_deny_when_robots_disallows_path() -> None:
    f = _make_fetcher_with_robots("User-agent: *\nDisallow: /jobs/\n")
    assert f.check_robots("https://example.com/jobs/list") is False
    f.close()


def test_robots_cached_per_host() -> None:
    fetch_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            fetch_count["n"] += 1
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, headers={"User-Agent": "test-bot/1.0"})
    cfg = FetcherConfig(default_qps=1000.0, max_retries=0, user_agent="test-bot/1.0")
    f = Fetcher(cfg, client=client)

    f.check_robots("https://example.com/a")
    f.check_robots("https://example.com/b")
    f.check_robots("https://example.com/c")
    assert fetch_count["n"] == 1
    f.close()
