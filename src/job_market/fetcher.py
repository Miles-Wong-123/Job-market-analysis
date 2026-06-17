"""统一的 HTTP fetcher：

- 单站令牌桶限速（默认 1 QPS，可按 host 覆盖）
- 全局并发 ≤ 10 QPS（通过单进程 ThreadPool 配合 per-host bucket 间接达成）
- 5xx / 网络错误指数退避重试，最多 3 次
- 4xx 直接返回（业务错误不重试）
- 透明 User-Agent：真实浏览器 UA + 项目标识，不伪造
- robots.txt 启动时拉一次缓存，禁止的路径直接判 False
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

# 真实浏览器 UA + 项目自报家门：透明，不伪造
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "job-market-analysis/0.1.0 (+https://github.com/wmy/job-market-analysis)"
)


class TokenBucket:
    """简单线程安全的令牌桶。`rate` 单位为 token/秒，`capacity` 默认等于 rate（突发=1 秒）。"""

    __slots__ = ("rate", "capacity", "_tokens", "_last", "_lock", "_clock")

    def __init__(self, rate: float, capacity: float | None = None, *, clock=time.monotonic) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be > 0, got {rate}")
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate
        self._tokens = self.capacity
        self._clock = clock
        self._last = clock()
        self._lock = threading.Lock()

    def take(self, tokens: float = 1.0, *, sleep=time.sleep) -> float:
        """阻塞到拿到 `tokens` 个令牌。返回实际等待的秒数。"""
        with self._lock:
            now = self._clock()
            elapsed = now - self._last
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._last = now
                return 0.0
            shortfall = tokens - self._tokens
            wait = shortfall / self.rate
            # 预订未来的时间点：等待结束后正好把这些令牌都消耗掉
            self._tokens = 0.0
            self._last = now + wait
        sleep(wait)
        return wait


@dataclass(slots=True)
class FetcherConfig:
    """fetcher 全局配置。per-host 限速通过 `set_host_qps()` 单独配置。"""

    default_qps: float = 1.0
    max_retries: int = 3
    backoff_base: float = 1.0  # 第 i 次重试等待 backoff_base * 2**(i-1) 秒
    user_agent: str = DEFAULT_USER_AGENT
    timeout_s: float = 20.0


class Fetcher:
    """所有 adapter 共用的 HTTP 客户端。线程安全。"""

    def __init__(
        self,
        config: FetcherConfig | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config or FetcherConfig()
        self._client = client or httpx.Client(
            http2=True,
            timeout=self.config.timeout_s,
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )
        self._buckets: dict[str, TokenBucket] = {}
        self._buckets_lock = threading.Lock()
        self._robots: dict[str, RobotFileParser] = {}
        self._robots_lock = threading.Lock()

    # --- 限速 ---

    def set_host_qps(self, host: str, qps: float) -> None:
        """为某 host 单独设置 QPS。未设置的 host 走 `default_qps`。"""
        with self._buckets_lock:
            self._buckets[host] = TokenBucket(qps)

    def _bucket_for(self, host: str) -> TokenBucket:
        with self._buckets_lock:
            b = self._buckets.get(host)
            if b is None:
                b = TokenBucket(self.config.default_qps)
                self._buckets[host] = b
            return b

    # --- robots.txt ---

    def check_robots(self, url: str) -> bool:
        """判断 url 是否被目标站点的 robots.txt 允许（按当前 UA）。

        失败/超时按 "允许" 处理（与多数爬虫一致）。同 host 只拉一次。
        """
        parsed = urlparse(url)
        host = parsed.netloc
        if not host:
            return True
        with self._robots_lock:
            rp = self._robots.get(host)
        if rp is None:
            rp = RobotFileParser()
            robots_url = f"{parsed.scheme}://{host}/robots.txt"
            try:
                resp = self._client.get(robots_url, timeout=10.0)
                if resp.status_code >= 400:
                    rp.parse([])  # 没有 robots.txt 视为全部允许
                else:
                    rp.parse(resp.text.splitlines())
            except httpx.HTTPError as exc:
                log.debug("拉取 %s 失败：%s（按允许处理）", robots_url, exc)
                rp.parse([])
            with self._robots_lock:
                self._robots[host] = rp
        return rp.can_fetch(self.config.user_agent, url)

    # --- 请求 ---

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urlparse(url).netloc
        bucket = self._bucket_for(host)

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= self.config.max_retries:
            bucket.take()
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt == self.config.max_retries:
                    raise
                self._sleep_backoff(attempt)
                attempt += 1
                continue
            # 4xx 不重试
            if 400 <= resp.status_code < 500:
                return resp
            # 5xx 走退避重试
            if resp.status_code >= 500 and attempt < self.config.max_retries:
                self._sleep_backoff(attempt)
                attempt += 1
                continue
            return resp
        # 理论上不会到这里
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("fetcher: unreachable retry path")

    def _sleep_backoff(self, attempt: int) -> None:
        wait = self.config.backoff_base * (2 ** attempt)
        log.debug("退避 %.1fs（第 %d 次）", wait, attempt + 1)
        time.sleep(wait)

    # --- 资源管理 ---

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def hosts_from_urls(urls: Iterable[str]) -> set[str]:
    """工具：从一组 URL 取出去重的 host 集合。"""
    return {urlparse(u).netloc for u in urls if urlparse(u).netloc}
