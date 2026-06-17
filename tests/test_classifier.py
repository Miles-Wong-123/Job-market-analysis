"""分类器单元测试：is_tech_role、assign_category、tech keyword 抽取。"""

from __future__ import annotations

from pathlib import Path

import pytest

from job_market.classifier import (
    assign_category,
    extract_tech_keywords,
    is_tech_role,
    load_categories,
    load_tech_keywords,
)


@pytest.mark.parametrize(
    "title,desc,expected",
    [
        ("后端开发工程师", "Java/Go", True),
        ("算法工程师-推荐方向", "", True),
        ("产品经理-社交方向", "", False),
        ("用户增长运营", "", False),
        ("HRBP", "", False),
        ("销售实习生", "", False),
        ("UI 设计师", "", False),
        ("前端开发工程师", "", True),
        ("客户端开发-iOS", "", True),
        ("数据分析师", "", True),
        ("人力资源实习生", "", False),
        ("法务实习生", "", False),
    ],
)
def test_is_tech_role(title: str, desc: str, expected: bool) -> None:
    assert is_tech_role(title, desc) is expected


@pytest.fixture
def categories_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "categories.yaml"
    p.write_text(
        """\
algorithm:
  patterns: [算法, 推荐, 搜索, NLP, 大模型, machine learning]
ai:
  patterns: [人工智能, 深度学习, AIGC, 多模态]
backend:
  patterns: [后端, 服务端, server, java工程师, 分布式]
frontend:
  patterns: [前端, web前端, react, vue]
mobile:
  patterns: [移动端, ios, android, 客户端]
data:
  patterns: [数据开发, 数据工程, 数仓]
infra:
  patterns: [基础架构, 运维, SRE, kubernetes]
""",
        encoding="utf-8",
    )
    return p


def test_load_categories_preserves_order(categories_yaml: Path) -> None:
    rules = load_categories(categories_yaml)
    names = [name for name, _ in rules]
    assert names == ["algorithm", "ai", "backend", "frontend", "mobile", "data", "infra"]


def test_specific_wins_over_general(categories_yaml: Path) -> None:
    rules = load_categories(categories_yaml)
    # "推荐算法" 同时含 "推荐"(algorithm)，algorithm 排在 backend 前应胜出
    assert assign_category("推荐算法工程师", "Java 后端", rules) == "algorithm"


def test_case_insensitive(categories_yaml: Path) -> None:
    rules = load_categories(categories_yaml)
    assert assign_category("Java工程师", "", rules) == "backend"
    assert assign_category("REACT 高级前端", "", rules) == "frontend"


def test_unmatched_falls_to_tech_other(categories_yaml: Path) -> None:
    rules = load_categories(categories_yaml)
    assert assign_category("某种新奇技术岗", "随便什么描述", rules) == "tech_other"


def test_extract_tech_keywords_dedup_and_order() -> None:
    keywords = ["python", "pytorch", "java", "go", "react"]
    hits = extract_tech_keywords(
        "我们用 Python 和 PyTorch，业务有 Java 后端，再加点 pytorch 复读",
        keywords,
    )
    assert hits == ["python", "pytorch", "java"]


def test_extract_tech_keywords_empty_returns_list_not_none() -> None:
    out = extract_tech_keywords("没有命中任何关键词", ["python", "java"])
    assert out == []
    assert out is not None


def test_load_tech_keywords_dedups_and_lowercases(tmp_path: Path) -> None:
    p = tmp_path / "tk.yaml"
    p.write_text("- Python\n- python\n- Java\n- JAVA\n- Go\n", encoding="utf-8")
    assert load_tech_keywords(p) == ["python", "java", "go"]
