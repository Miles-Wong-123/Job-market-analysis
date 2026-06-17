"""测试公共配置：屏蔽用户环境里的 HTTP/SOCKS 代理变量，避免 httpx 启动时尝试加载 socksio。"""

from __future__ import annotations

import os

import pytest


_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@pytest.fixture(autouse=True)
def _strip_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
