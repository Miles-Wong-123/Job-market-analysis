"""技术岗判断 + 类别分配 + 技术词抽取。

两阶段策略：先 `is_tech_role` 把非技术岗拦在入库之前，再 `assign_category`
对存活下来的岗位按 `categories.yaml` 关键词匹配。词典在 YAML 里维护，
迭代不需要改代码。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

# 非技术岗黑名单：命中其一即视为非技术岗，直接丢弃不入库。
# 注意：纯设计师/UI 设计算非技术岗，但 "前端" / "客户端开发" 是技术岗，
# 不会被这里的关键词误伤。
NON_TECH_PATTERNS: tuple[str, ...] = (
    "产品经理",
    "产品运营",
    "运营",
    "市场营销",
    "市场专员",
    "品牌",
    "公关",
    "销售",
    "BD",
    "商务",
    "财务",
    "会计",
    "审计",
    "出纳",
    "法务",
    "律师",
    "合规",
    "行政",
    "人力资源",
    "HRBP",
    "招聘",
    "客服",
    "售后",
    "采购",
    "供应链管理",
    "美工",
    "UI 设计师",
    "UX 设计师",
    "视觉设计",
    "平面设计",
    "文案",
    "翻译",
    "编辑",
    "策划",
    "影视",
    "新媒体",
    "主播",
    "助理",
    "秘书",
)


def _lower(s: str) -> str:
    return s.casefold()


def is_tech_role(title: str, description: str = "") -> bool:
    """命中非技术黑名单返回 False，否则视为可能技术岗（True）。

    匹配是 case-insensitive 的子串匹配，对中英文都生效。
    """
    haystack = _lower(f"{title}\n{description}")
    for pat in NON_TECH_PATTERNS:
        if _lower(pat) in haystack:
            return False
    return True


CategoryRules = list[tuple[str, list[str]]]
"""保留 YAML 文件顺序的类别规则：[(类别名, [模式...]), ...]。"""


def load_categories(path: str | Path) -> CategoryRules:
    """从 YAML 加载类别词典，**保留文件顺序**以支持 first-match-wins。

    YAML 形如：
        algorithm:
          patterns: [算法, 推荐, ...]
        backend:
          patterns: [后端, ...]

    用 PyYAML 默认的 `safe_load` 即可保序（CPython 3.7+ dict 有序）。
    """
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules: CategoryRules = []
    for name, body in data.items():
        if not isinstance(body, dict):
            continue
        patterns = body.get("patterns") or []
        if not isinstance(patterns, list):
            continue
        rules.append((name, [str(p) for p in patterns]))
    return rules


def assign_category(title: str, description: str, rules: CategoryRules) -> str:
    """按规则顺序匹配；都没命中返回 `tech_other`。"""
    haystack = _lower(f"{title}\n{description}")
    for name, patterns in rules:
        for pat in patterns:
            if _lower(pat) in haystack:
                return name
    return "tech_other"


def load_tech_keywords(path: str | Path) -> list[str]:
    """从 YAML 加载技术词列表，返回小写化、去重、保序的列表。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    seen: set[str] = set()
    out: list[str] = []
    if isinstance(data, dict):
        # 也支持顶层是 {keywords: [...]} 的写法
        data = data.get("keywords", [])
    for kw in data or []:
        s = _lower(str(kw)).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def extract_tech_keywords(text: str, keywords: Iterable[str]) -> list[str]:
    """对文本扫词频，返回**去重、保序**的命中列表。

    保留输入 keywords 列表里的顺序（按词典出现顺序），便于结果稳定可复现。
    匹配规则：case-insensitive 子串匹配。
    """
    haystack = _lower(text)
    seen: set[str] = set()
    hits: list[str] = []
    for kw in keywords:
        s = _lower(kw).strip()
        if not s or s in seen:
            continue
        if s in haystack:
            seen.add(s)
            hits.append(s)
    return hits
