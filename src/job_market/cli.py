"""命令行入口：`python -m job_market crawl`。

子命令目前只有 `crawl`，可通过 `--config / --db / --raw-dir` 覆盖默认路径。
运行结束后打印每家公司的进度表；收到 Ctrl-C 时也会打印当前已完成的部分再退出。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from job_market import __version__
from job_market.pipeline import (
    CompanyResult,
    PipelineConfig,
    RunSummary,
    run_pipeline,
)

DEFAULT_CONFIG = Path("config/companies.yaml")
DEFAULT_DB = Path("data/jobs.db")
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_CATEGORIES = Path("config/categories.yaml")
DEFAULT_TECH_KEYWORDS = Path("config/tech_keywords.yaml")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job-market",
        description="大厂校招技术岗抓取与分析工具",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    crawl = sub.add_parser("crawl", help="抓取所有启用的公司，写入 SQLite + raw JSONL")
    crawl.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"companies.yaml 路径（默认 {DEFAULT_CONFIG}）",
    )
    crawl.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite 数据库路径（默认 {DEFAULT_DB}）",
    )
    crawl.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"原始 JSONL 落盘目录（默认 {DEFAULT_RAW_DIR}）",
    )
    crawl.add_argument(
        "--categories",
        type=Path,
        default=None,
        help="categories.yaml 路径（默认与 --config 同目录）",
    )
    crawl.add_argument(
        "--tech-keywords",
        type=Path,
        default=None,
        help="tech_keywords.yaml 路径（默认与 --config 同目录）",
    )
    crawl.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="打开 DEBUG 日志",
    )
    return parser


def _resolve_companion(
    explicit: Path | None,
    fallback_name: str,
    config_path: Path,
    project_default: Path,
) -> Path:
    """优先用 --xxx 显式路径；否则取 --config 同目录下同名文件；都没有就回退到项目默认。"""
    if explicit is not None:
        return explicit
    sibling = config_path.parent / fallback_name
    if sibling.exists():
        return sibling
    return project_default


def _format_row(r: CompanyResult) -> str:
    if r.skipped_reason:
        return f"  {r.company:<12} skipped  ({r.skipped_reason})"
    err = f"  ERROR: {r.error}" if r.error else ""
    return (
        f"  {r.company:<12} fetched={r.fetched:<4} kept={r.kept:<4} "
        f"dropped_non_tech={r.dropped_non_tech:<3} parsing_errors={r.parsing_errors:<3} "
        f"{r.duration_s:.1f}s{err}"
    )


def _print_summary(summary: RunSummary, *, partial: bool = False) -> None:
    title = "运行汇总（中断前已完成）" if partial else "运行汇总"
    print(f"\n=== {title} ===")
    if not summary.companies:
        print("  (无任何公司被处理)")
        return
    for r in summary.companies:
        print(_format_row(r))
    print(f"  合计写入 {summary.total_kept()} 条技术岗")


def _exit_code(summary: RunSummary) -> int:
    """至少一家公司无环境性错误地完成 → 0；否则 1。"""
    finished_ok = any(
        c.error is None and c.skipped_reason is None for c in summary.companies
    )
    return 0 if finished_ok else 1


def _run_crawl(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config_path: Path = args.config
    if not config_path.exists():
        print(f"找不到配置文件 {config_path}", file=sys.stderr)
        return 2

    categories_path = _resolve_companion(
        args.categories, "categories.yaml", config_path, DEFAULT_CATEGORIES
    )
    tech_keywords_path = _resolve_companion(
        args.tech_keywords, "tech_keywords.yaml", config_path, DEFAULT_TECH_KEYWORDS
    )
    for p, label in (
        (categories_path, "categories.yaml"),
        (tech_keywords_path, "tech_keywords.yaml"),
    ):
        if not p.exists():
            print(f"找不到 {label}：{p}", file=sys.stderr)
            return 2

    cfg = PipelineConfig(
        db_path=args.db,
        raw_dir=args.raw_dir,
        companies_yaml=config_path,
        categories_yaml=categories_path,
        tech_keywords_yaml=tech_keywords_path,
    )

    summary = RunSummary()

    def _log_one(r: CompanyResult) -> None:
        # 流式打印每家公司的状态，让用户在长跑时也能看到进度
        print(_format_row(r), flush=True)

    try:
        summary = run_pipeline(cfg, on_company_done=_log_one)
    except KeyboardInterrupt:
        print("\n收到中断信号，已停止派发新任务。", file=sys.stderr)
        # 部分进度已经被 _log_one 流式打印；此处补一份概览。
        # 注意：被中断时 run_pipeline 抛出 KeyboardInterrupt，summary 仍是初始空值，
        # 因此这里只能告诉用户已经写下的内容（每家公司在自己 future 里已经 upsert + write_raw）。
        print("已完成的公司数据已写入 SQLite + raw JSONL。", file=sys.stderr)
        return 130
    except FileNotFoundError as exc:
        print(f"配置或路径错误：{exc}", file=sys.stderr)
        return 2

    _print_summary(summary)
    return _exit_code(summary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "crawl":
        return _run_crawl(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
