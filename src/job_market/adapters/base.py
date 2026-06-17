"""统一的 adapter 契约：每家公司继承 `CampusAdapter`，实现 `list_jobs` 和 `normalize`。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from job_market.fetcher import Fetcher


@dataclass(slots=True)
class RawJob:
    """单条原始抓取结果。`source_url` 是详情页或来源页 URL，`payload` 是原始 JSON 字典。"""

    source_url: str
    payload: dict[str, Any]


@dataclass(slots=True)
class NormalizedJob:
    """统一 schema 下的一条岗位。category / tech_keywords / parsing_error 由后续层补齐。"""

    job_id: str
    company: str
    title: str
    description: str
    requirements: str
    location: list[str]
    education: str | None
    job_type: str
    department: str | None
    posted_at: str | None
    source_url: str
    raw_payload: dict[str, Any]
    subcategory: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class CampusAdapter(ABC):
    """每家大厂校招 adapter 的抽象基类。

    子类必须设置 `company`（与 `companies.yaml` 中的 key 对应）。`rate_limit_qps`
    由 fetcher 用作单站限速预算，可被 yaml 覆盖。
    """

    company: str = ""
    rate_limit_qps: float = 1.0

    def __init__(self, *, rate_limit_qps: float | None = None) -> None:
        if rate_limit_qps is not None:
            self.rate_limit_qps = rate_limit_qps

    @abstractmethod
    def list_jobs(self, fetcher: Fetcher) -> Iterator[RawJob]:
        """流式产出原始岗位。负责分页、过滤参数等公司特定逻辑。"""

    @abstractmethod
    def normalize(self, raw: RawJob) -> NormalizedJob:
        """把原始 payload 映射到 NormalizedJob。字段缺失/异常由 normalizer 层捕获。"""


def discover_adapters() -> dict[str, type[CampusAdapter]]:
    """导入 adapters 子包内所有模块，返回 {company: adapter_cls}。

    导入失败的模块会被忽略（写日志），保证一家 adapter 写坏不会拖垮其他。
    """
    import importlib
    import logging
    import pkgutil

    from job_market import adapters as adapters_pkg

    log = logging.getLogger(__name__)
    found: dict[str, type[CampusAdapter]] = {}
    for mod_info in pkgutil.iter_modules(adapters_pkg.__path__):
        if mod_info.name.startswith("_") or mod_info.name == "base":
            continue
        mod_name = f"{adapters_pkg.__name__}.{mod_info.name}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001 — 任何导入失败都不应阻断其它公司
            log.warning("跳过 adapter 模块 %s（导入失败：%s）", mod_name, exc)
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, CampusAdapter)
                and obj is not CampusAdapter
                and obj.company
            ):
                found[obj.company] = obj
    return found
