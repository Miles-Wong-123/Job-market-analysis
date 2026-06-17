"""CLI 集成测试：monkeypatch adapter 注册，跑 `python -m job_market crawl`，
确认数据库被填充、raw JSONL 落盘、退出码符合预期。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from job_market import cli
from job_market.adapters import base as base_mod
from job_market.adapters.base import CampusAdapter, NormalizedJob, RawJob


class FakeAdapter(CampusAdapter):
    company = "fake"

    def list_jobs(self, fetcher):  # type: ignore[override]
        for i in range(2):
            yield RawJob(source_url=f"https://fake.example.com/{i}", payload={"id": i})

    def normalize(self, raw: RawJob) -> NormalizedJob:
        i = raw.payload["id"]
        return NormalizedJob(
            job_id=f"fake:{i}",
            company="fake",
            title="后端开发工程师",
            description="Java 服务端",
            requirements="",
            location=["北京"],
            education="本科",
            job_type="校招",
            department=None,
            posted_at=None,
            source_url=raw.source_url,
            raw_payload=raw.payload,
        )


@pytest.fixture
def patched_registry(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(base_mod, "discover_adapters", lambda: {"fake": FakeAdapter})
    from job_market import pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "discover_adapters", lambda: {"fake": FakeAdapter})


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "companies.yaml").write_text(
        "companies:\n  fake: {enabled: true, rate_limit_qps: 100}\n",
        encoding="utf-8",
    )
    (cfg_dir / "categories.yaml").write_text(
        "backend:\n  patterns: [后端, Java]\n",
        encoding="utf-8",
    )
    (cfg_dir / "tech_keywords.yaml").write_text(
        "- java\n- python\n",
        encoding="utf-8",
    )
    return cfg_dir


def test_cli_crawl_populates_db_and_raw(
    tmp_path: Path,
    patched_registry: None,
    config_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "out.db"
    raw_dir = tmp_path / "raw"

    code = cli.main(
        [
            "crawl",
            "--config",
            str(config_dir / "companies.yaml"),
            "--db",
            str(db_path),
            "--raw-dir",
            str(raw_dir),
        ]
    )
    assert code == 0

    # 数据库被填充
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        ids = sorted(r[0] for r in conn.execute("SELECT job_id FROM jobs"))
    assert ids == ["fake:0", "fake:1"]

    # raw JSONL 落盘
    day_dirs = list(raw_dir.iterdir())
    assert len(day_dirs) == 1
    fake_jsonl = day_dirs[0] / "fake.jsonl"
    assert fake_jsonl.exists()
    lines = fake_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["payload"] == {"id": 0}

    # 摘要被打印
    out = capsys.readouterr().out
    assert "fake" in out
    assert "fetched=2" in out
    assert "kept=2" in out


def test_cli_missing_config_returns_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(
        [
            "crawl",
            "--config",
            str(tmp_path / "nope.yaml"),
            "--db",
            str(tmp_path / "out.db"),
            "--raw-dir",
            str(tmp_path / "raw"),
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "找不到配置文件" in err


def test_cli_no_subcommand_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # argparse 把缺失子命令当成 SystemExit(2)
    with pytest.raises(SystemExit) as exc_info:
        cli.main([])
    assert exc_info.value.code == 2


def test_cli_help_lists_crawl(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "crawl" in out
