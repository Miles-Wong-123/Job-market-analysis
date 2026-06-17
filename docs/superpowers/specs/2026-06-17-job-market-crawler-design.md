# 大厂校招技术岗市场需求分析工具 — 设计文档

**Date:** 2026-06-17
**Status:** Draft, awaiting user review
**Owner:** wmy

## 1. 背景与目标

用户希望了解当前国内大厂对**校招技术岗**的整体需求结构（哪些方向、哪些技术栈、哪些城市、哪些学历要求最多），用于辅助自身校招决策。

用户背景：北邮本科电子信息 + 港大硕士 CS，关注方向限定在技术岗（前端/后端/算法/AI/移动/嵌入式/数据/基础架构/安全/测试/客户端/硬件），不关注产品、运营、职能岗。

本工具产出一次性快照：跑一次脚本，得到 SQLite 数据库 + Jupyter 报告，呈现当前时点的技术岗市场分布。设计上预留扩展位，方便以后改成定期采集看趋势。

## 2. 范围

### In scope
- 从大厂**官方校招网站**采集**公开**的职位列表
- 覆盖 10 家头部大厂（字节、阿里、腾讯、美团、京东、网易、小米、拼多多、百度、华为）
- 仅采集校招 + 实习岗位，仅保留技术类岗位
- 字段归一化、分类、技术关键词提取、SQLite 存储
- Jupyter notebook 出可视化趋势报告

### Out of scope
- 第三方招聘聚合平台（智联、BOSS、拉勾、牛客等）
- 社招岗位
- 非技术岗（产品、运营、HR、销售、财务、法务等）
- 登录后才可见的内容、HR 个人信息、申请者信息
- 跨快照的时间序列分析（保留扩展位，不在本期实现）
- 薪资数据（多数公司公开 API 不提供，本期不做）

### 合法性边界
所有目标网站对外公开职位列表是其招聘前提。本工具严格遵守：
1. 启动时检查并遵守每家网站的 `robots.txt`
2. 控制总并发 ≤ 10 QPS、单站 ≤ 1 QPS，远低于网站承载能力
3. 仅访问公开端点，不抓取登录后内容
4. 不采集任何 PII（HR 联系方式、申请者信息）
5. 数据仅用于个人研究，不二次商业分发
6. User-Agent 透明标识，不伪造身份不绕反爬

## 3. 整体架构

分层管道，各层只关心自己的契约：

```
Adapters (每家公司独立)
  → Fetcher (统一 HTTP + 限速 + 重试)
  → Normalizer (统一 schema + 分类 + 关键词)
  → Filter (只保留技术岗)
  → Storage (SQLite + 原始 JSON 双写)
  → Analysis (Jupyter notebook)
```

### 项目结构

```
job-market-analysis/
├── src/job_market/
│   ├── adapters/
│   │   ├── base.py            # CampusAdapter 抽象基类
│   │   ├── bytedance.py
│   │   ├── alibaba.py
│   │   ├── tencent.py
│   │   ├── meituan.py
│   │   ├── jd.py
│   │   ├── netease.py
│   │   ├── xiaomi.py
│   │   ├── pdd.py
│   │   ├── baidu.py
│   │   └── huawei.py          # 可能用 Playwright 兜底
│   ├── fetcher.py             # httpx + 限速 + 重试
│   ├── normalizer.py          # 字段映射 + 分类 + 关键词
│   ├── classifier.py          # is_tech_role 过滤 + category 判定
│   ├── storage.py             # SQLite + raw JSON dump
│   ├── pipeline.py            # 编排器
│   └── cli.py                 # python -m job_market crawl
├── config/
│   ├── companies.yaml         # 启用哪些公司、限速参数
│   ├── categories.yaml        # 类别词典
│   └── tech_keywords.yaml     # 技术关键词词典
├── tests/
│   ├── fixtures/              # 真实 API 响应样本
│   ├── adapters/              # 每家 adapter 的解析测试
│   ├── test_normalizer.py
│   ├── test_classifier.py
│   ├── test_fetcher.py
│   └── test_pipeline.py
├── notebooks/
│   └── trends.ipynb
├── data/
│   ├── jobs.db
│   └── raw/YYYY-MM-DD/<company>.jsonl
├── pyproject.toml
└── README.md
```

### 关键设计决策

- **Adapter Pattern**：每家公司独立模块。新增公司只需加一个文件，失败时只这家失败不影响其他公司
- **Raw JSON 双写**：保留每次抓取的原始响应，归一化逻辑可以重跑
- **SQLite 而非 CSV**：支持 SQL 查询、增量去重、字段演化；又比 PostgreSQL 简单不需起服务
- **关键词分类而非 LLM**：一次性快照要可复现，词典版本化
- **CLI + Notebook 分离**：抓数据是脚本任务，分析是探索任务

## 4. 数据模型

### SQLite 表 `jobs`

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | TEXT PK | `<company>:<原始ID>` 复合主键 |
| `company` | TEXT | 公司枚举 |
| `title` | TEXT | 原始岗位标题 |
| `category` | TEXT | 归一化类别（见下） |
| `subcategory` | TEXT | 细分方向，如「推荐系统」「分布式存储」 |
| `description` | TEXT | 岗位职责 |
| `requirements` | TEXT | 任职要求 |
| `tech_keywords` | JSON | 技术词数组 |
| `location` | JSON | 工作地点数组 |
| `education` | TEXT | `本科` / `硕士` / `博士` / `不限` |
| `job_type` | TEXT | `校招` / `实习` |
| `department` | TEXT | 业务线 |
| `posted_at` | DATE | 发布日期（如 API 提供） |
| `crawled_at` | DATETIME | 抓取时间 |
| `source_url` | TEXT | 详情页 URL |
| `raw_payload` | JSON | 原始 API 响应 |
| `parsing_error` | BOOLEAN | normalize 是否有缺字段 |

索引：`company`, `category`, `crawled_at`。

### 类别枚举（仅技术岗）

`algorithm` / `ai` / `backend` / `frontend` / `mobile` / `client` / `embedded` / `hardware` / `data` / `infra` / `security` / `qa` / `tech_other`

分类两阶段：
1. **`is_tech_role(title, description)`**：先判是不是技术岗。命中明确非技术关键词（产品经理、运营、HR、销售、财务、法务、行政、市场、品牌、设计师非技术向、客服、采购等）则返回 false，**直接丢弃不入库**
2. **`assign_category(title, description)`**：对确认是技术岗的，按 `categories.yaml` 关键词匹配；都不命中则归 `tech_other`（仍入库，分析时单独看）

`tech_other` 是「技术岗但没匹配到细分类别」的兜底，不是「不确定是不是技术」。后者通过 is_tech_role 拦在入库之前。

### 配置文件示例

`config/categories.yaml`：

```yaml
algorithm:
  patterns: [算法, 推荐, 搜索, 广告, NLP, CV, 大模型, LLM, 机器学习, machine learning]
ai:
  patterns: [人工智能, 深度学习, AIGC, 生成式, 多模态, AGI]
backend:
  patterns: [后端, 服务端, server, java工程师, golang, 分布式, 中间件, 数据库开发]
frontend:
  patterns: [前端, web前端, 大前端, react, vue]
mobile:
  patterns: [移动端, ios, android, 客户端开发]
embedded:
  patterns: [嵌入式, 固件, RTOS, 单片机, 驱动]
hardware:
  patterns: [硬件, 芯片, 数字IC, 模拟IC, FPGA, 射频, RF]
data:
  patterns: [数据开发, 数据工程, 数仓, ETL, 大数据]
infra:
  patterns: [基础架构, 运维, SRE, devops, 云原生, kubernetes]
security:
  patterns: [安全, 渗透, 攻防, 风控]
qa:
  patterns: [测试, QA, 质量, 自动化测试]
client:
  patterns: [桌面, 客户端, electron, unity]
```

匹配优先级：specific → general（先匹 algorithm 再匹 backend）。

`config/tech_keywords.yaml` 列约 200 个技术词（编程语言、框架、云平台、数据库、AI 框架等），用于从 JD 文本扫词频。

## 5. Adapter 契约

```python
# src/job_market/adapters/base.py
from dataclasses import dataclass
from typing import Iterator

@dataclass
class RawJob:
    source_url: str
    payload: dict

@dataclass
class NormalizedJob:
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
    raw_payload: dict

class CampusAdapter(ABC):
    company: str
    rate_limit_qps: float = 1.0

    @abstractmethod
    def list_jobs(self, fetcher: "Fetcher") -> Iterator[RawJob]: ...

    @abstractmethod
    def normalize(self, raw: RawJob) -> NormalizedJob: ...
```

每家 adapter 自己决定分页、过滤参数、原始字段映射。category / tech_keywords / parsing_error 不在 adapter 里算，由 normalizer 后处理。

## 6. Fetcher

`httpx` 客户端，支持 HTTP/2。

- Token-bucket 限速器，per-host 独立
- 重试：5xx 和网络错误指数退避 (1s, 2s, 4s)，最多 3 次
- 4xx 不重试（业务错误）
- User-Agent：真实浏览器 UA + 项目标识，不伪造
- 全局并发上限：≤ 10 QPS

## 7. Pipeline 编排

```
load config.yaml → 实例化 enabled adapters
  → 启动时检查 robots.txt，禁止的 adapter 跳过并记录
  → ThreadPoolExecutor(max_workers=10) 并行跑公司
    → 公司内串行（rate_limit_qps 限速）
      → list_jobs() 流式抓 → normalize() → classify(category, keywords)
      → is_tech_role 过滤 → 累积
  → 全部完成后，批量 INSERT OR REPLACE 进 SQLite
  → 同时把每家原始响应 dump 到 data/raw/YYYY-MM-DD/<company>.jsonl
  → 输出统计：每家 N 条 / 失败原因
```

### 错误隔离

- 一家 adapter 抛异常 → 记日志，其他公司继续
- 一条记录 normalize 失败 → 标 `parsing_error=True`，保留 raw payload 入库，其他继续
- API schema 变化检测：normalize 时关键字段（id/title）缺失即标记

## 8. 测试策略

按 TDD 顺序：

1. `test_classifier.py` — 喂示例标题，断言 category 与 is_tech_role
2. `test_normalizer.py` — 喂保存的 fixture，断言统一 schema 输出
3. `test_<company>.py` — mock fetcher，断言 list_jobs 调用 endpoint 与分页
4. `test_pipeline.py` — 端到端，多家 adapter 全 mock，断言 SQLite 数据正确、错误隔离生效

Fixture：每家 adapter 第一次手动跑通后，保存一两页真实响应到 `tests/fixtures/<company>_jobs_p1.json`，去敏。

## 9. 输出报告（`notebooks/trends.ipynb`）

1. 总体统计：本次抓到 N 个技术岗，覆盖 X 家公司，按公司分组数量
2. 岗位类别分布：堆叠柱状图（X 轴公司，Y 轴 category 数量）
3. 技术栈热度：tech_keywords 词频 top 30
4. 地点分布：饼图（北京/上海/深圳/杭州/广州/其他）
5. 学历要求分布：本科/硕士/博士占比，分 category 看
6. 细分方向 Top N：subcategory 热度排名（推荐系统 vs 搜索 vs 大模型 …）

## 10. 失败模式与缓解

| 失败模式 | 表现 | 缓解 |
|---|---|---|
| 公司 API 变更 | normalize 报错或字段缺失 | parsing_error 标记 + raw payload 保留，便于事后修 |
| 公司 API 找不到 | 公开端点是 SPA + JS 混淆 | 该 adapter 用 Playwright 兜底（华为可能需要） |
| 网络抖动 | 单次请求失败 | 指数退避重试 |
| 分类不准 | 关键词词典覆盖不全 | 词典是配置文件可迭代；技术岗但无具体类别匹配标 `tech_other` 单独看 |
| robots.txt 禁止 | 不应抓 | 启动时检测、跳过、日志 |

## 11. Future Work

- 定期快照（schema 已有 `crawled_at`，加一个 cron + 增量去重即可）
- 跨快照趋势分析（同一职位连续在招多久、新增/下架追踪）
- 薪资字段（部分公司 API 有，本期未抓）
- 第三方平台兜底（仅在确认其 ToS 允许的前提下）
- LLM 辅助 subcategory 提取（在词典覆盖不足时）

## 12. 验收标准

- 跑一次 `python -m job_market crawl` 能在 10 分钟内抓完 10 家公司，输出 `data/jobs.db` + `data/raw/<date>/`
- 所有测试通过（`pytest`）
- 对每家公司，至少能从 fixture 解析出 ≥ 95% 字段不报 parsing_error
- `notebooks/trends.ipynb` 跑完输出 6 张图表，能直观回答「目前国内大厂校招技术岗在招什么方向、什么技术栈、什么城市、什么学历」

