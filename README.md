# 大厂校招技术岗市场需求分析工具

抓取国内 10 家大厂（字节、阿里、腾讯、美团、京东、网易、小米、拼多多、百度、华为）公开校招页面的技术岗位列表，归一化字段、过滤非技术岗、提取技术关键词，写入 SQLite，并通过 Jupyter notebook 输出宏观分布图表。

设计文档见 `docs/superpowers/specs/2026-06-17-job-market-crawler-design.md`，OpenSpec 实现说明见 `openspec/changes/implement-campus-tech-crawler/`。

## 安装

需要 Python ≥ 3.11。

```bash
pip install -e .[dev]
# 如果需要 Playwright 兜底（仅个别 adapter 使用）
pip install -e .[playwright]
playwright install chromium
```

## 运行

抓数据：

```bash
python -m job_market crawl
```

产物：

- `data/jobs.db`：归一化后的 SQLite，主表 `jobs`
- `data/raw/<日期>/<公司>.jsonl`：每家公司的原始响应，用于事后回放归一化逻辑

看分析：

```bash
jupyter lab notebooks/trends.ipynb
```

restart-and-run-all 即可得到 6 张图表：公司×类别堆叠图、技术词热度 Top 30、城市分布饼图、学历分布、细分方向 Top N、整体统计。

## 合法与合规

- 启动时检查并遵守每家网站的 `robots.txt`，被禁止的 adapter 直接跳过
- 全局 ≤ 10 QPS、单站 ≤ 1 QPS，远低于网站承载能力
- 仅访问公开端点，不抓登录后内容、不收集任何 PII（HR 联系方式、申请者信息）
- User-Agent 透明标识真实浏览器 UA + 项目名，不伪造身份、不绕反爬
- 数据仅用于个人研究，不二次商业分发

## 项目结构

```
job-market-analysis/
├── src/job_market/
│   ├── adapters/        # 每家大厂一个模块
│   ├── fetcher.py       # httpx + 限速 + 重试
│   ├── normalizer.py    # 字段归一 + parsing_error 标记
│   ├── classifier.py    # 是否技术岗 + 类别 + 技术词
│   ├── storage.py       # SQLite + 原始 JSONL 双写
│   ├── pipeline.py      # 编排器
│   └── cli.py           # python -m job_market crawl
├── config/
│   ├── companies.yaml   # 启用哪些公司、限速参数
│   ├── categories.yaml  # 类别词典
│   └── tech_keywords.yaml  # 技术词词典
├── tests/               # pytest 用例 + fixture
├── notebooks/trends.ipynb
└── data/                # 运行时产物（gitignored）
```

## 开发

```bash
pytest -q          # 跑测试
ruff check src tests  # 代码风格
```
