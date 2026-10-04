# Creator Ops Agent

**海外创作者营销的两个 AI 应用演示：固定工作流工作台 → 有边界的工具调用 Agent。**

面向创作者筛选、报价调研、英文沟通草稿和内容审核，展示如何把大模型接入业务流程：确定性规则、数据库、知识检索、结构化输出、人工确认和测试，而不只是一段聊天接口。

技术栈：Python 3.11+ · FastAPI · SQLite / FTS5 · Pydantic · 原生 HTML/CSS/JavaScript · 可选 DeepSeek API。

这是学习与求职展示项目，使用虚构品牌、创作者、邮箱和数据。默认 MOCK 不需要账号或 API Key，任务不会调用模型 API；首次安装依赖可能联网。它不是生产营销平台，也没有训练或微调大模型。

## 两个项目，怎么选

| | V1：Creator Ops Workbench | V2：Creator Research Agent |
|---|---|---|
| 主要问题 | 从 Brief 到候选、草稿和文本审核，如何可靠推进？ | 给定调研任务，模型如何选择工具、引用证据并生成报告？ |
| 控制方式 | 用户按固定步骤触发功能 | 模型在白名单工具内选择下一步 |
| 主要展示 | 数据清洗、硬条件筛选、AI 排序解释、外联草稿、人工审批、审核、日志与评测 | 创作者查询、报价统计、知识检索、报告与英文草稿、工具轨迹、历史任务、人工确认 |
| 入口 | `app.main:app` | `app.agent_main:app` |
| 本机地址 | <http://127.0.0.1:8000> | <http://127.0.0.1:8010> |
| 默认数据库 | `data/app.db` | `data/agent_v2.db` |
| 第一次启动 | 从页面导入示例 CSV | 自动导入示例创作者数据 |
| 详细说明 | [V1 README](README_WORKFLOW_V1.md) | [V2 README](README_AGENT_V2.md) |

两版共用数据清洗、匹配和检索模块，但入口、页面、任务记录和默认数据库分开。放在同一仓库是为了展示演进与复用，不代表两个完全独立的代码库。可以同时启动。

## 快速启动

### 1. 下载并安装依赖

需要 Git、Python 3.11 或更高版本；SQLite 构建需要支持 FTS5。以下命令均在项目根目录运行。

macOS / Linux：

```bash
git clone https://github.com/jackguo2016/creator-ops-agent.git
cd creator-ops-agent
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
git clone https://github.com/jackguo2016/creator-ops-agent.git
cd creator-ops-agent
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

不必激活虚拟环境：命令直接使用其中的 Python。没有 Git 时也可用 GitHub 的 **Code → Download ZIP**，解压后在该文件夹打开终端，从检查 Python 版本开始。

### 2. 启动 V1

macOS / Linux：

```bash
LLM_PROVIDER=mock DB_PATH=data/app.db .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell：

```powershell
$env:LLM_PROVIDER = "mock"
$env:DB_PATH = "data/app.db"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。服务运行时请保留终端，按 `Ctrl + C` 停止。

### 3. 启动 V2

另开一个终端，进入同一个项目目录。

macOS / Linux：

```bash
LLM_PROVIDER=mock AGENT_V2_DB_PATH=data/agent_v2.db .venv/bin/python -m uvicorn app.agent_main:app --host 127.0.0.1 --port 8010
```

Windows PowerShell：

```powershell
$env:LLM_PROVIDER = "mock"
$env:AGENT_V2_DB_PATH = "data/agent_v2.db"
.\.venv\Scripts\python.exe -m uvicorn app.agent_main:app --host 127.0.0.1 --port 8010
```

浏览器打开 <http://127.0.0.1:8010>。

macOS / Linux 也可使用快捷脚本：V1 为 `LLM_PROVIDER=mock bash ./run.sh`，V2 为 `bash ./run-agent-v2.sh`。V1 脚本会读取已有 `.env`，但显式 `LLM_PROVIDER=mock` 优先；V2 无参数脚本固定使用 MOCK，不读取 `.env`。

上面的手动 `python -m uvicorn` 命令只读取环境变量，**不会自动读取 `.env`**。Windows 命令提供手动启动方式；本次回归在 macOS / Python 3.12 执行，未在 Windows 实机验证。

## 五分钟演示

### V1：一次营销交付工作流

1. 在“项目 Brief”确认市场、预算、产品事实与限制。
2. 在“创作者库”导入 [`data/creators.csv`](data/creators.csv)，观察清洗与去重。
3. 在“智能匹配”先做规则筛选，再运行 AI 解释排序；检查结果是否满足硬条件。
4. 选择候选，在“沟通与交付”生成英文外联草稿，检查后人工批准。批准只记录本地状态，不发邮件。
5. 粘贴一段交付文案运行内容审核，查看标签与依据；这里只审核文字，不读取视频或链接内容。
6. 在“日志与评测”查看用量、耗时与错误摘要，运行 20 个固定业务案例。

逐句讲稿：[V1 演示稿](docs/DEMO_SCRIPT_CN.md)；原理：[V1 项目讲解](docs/PROJECT_GUIDE_CN.md)。

### V2：一个可追踪的调研任务

1. 选择“候选调研”，保留默认结构化条件，点击“运行调研”。
2. 查看候选、证据引用、报告和执行轨迹：哪些工具被调用，为什么需要这些资料？
3. 切换“报价分析”或“沟通草稿”，观察工具路径与输出的区别。
4. 修改预算或市场再运行，比较候选变化；查询范围由服务器规则控制，不能只靠 Prompt 放宽。
5. 核实报告后点击人工确认，查看历史记录。确认不触发邮件或 CRM 写入。

MOCK 使用确定性模拟工具路径，适合排练与回归，不能拿它证明真实模型推理能力或准确率。

完整按钮说明、练习与源码学习：[V2 使用与学习攻略](docs/AGENT_V2_GUIDE_CN.md)；[V2 演示与面试稿](docs/AGENT_V2_DEMO_CN.md)。

## 如何实现

```text
浏览器页面（HTML / CSS / JS）
        ↓ HTTP
FastAPI 路由 → 输入校验与业务规则 → SQLite / FTS5
        ↓
V1：固定步骤调用模型 → 校验 JSON → 草稿 / 审核 / 日志
V2：有界循环 → 只读工具 → 证据 → 校验报告 → 人工确认
```

| 层 | 源码入口 | 负责什么 |
|---|---|---|
| V1 HTTP / 页面 | [`app/main.py`](app/main.py)、[`app/templates/`](app/templates/) | 页面、表单、API 与固定工作流 |
| V2 HTTP / 页面 | [`app/agent_main.py`](app/agent_main.py)、[`agent_v2.js`](app/static/agent_v2.js) | 创建任务、历史、轨迹与人工确认 |
| Agent 编排 | [`app/agent_v2.py`](app/agent_v2.py) | 三个工具白名单、协议检查、有界循环、报告与证据校验 |
| 数据与规则 | [`creators.py`](app/creators.py)、[`matching.py`](app/matching.py) | CSV 清洗去重、硬条件与规则评分 |
| 知识检索 | [`app/retrieval.py`](app/retrieval.py) | SQLite FTS5 检索本地产品事实与合规条目；不是向量检索 |
| 模型与配置 | [`app/llm.py`](app/llm.py)、[`app/config.py`](app/config.py) | V1 模型客户端、MOCK、结构化输出、重试与估算用量；V2 自有工具调用协议 |
| 持久化 | [`app/db.py`](app/db.py)、[`app/schema.sql`](app/schema.sql) | 数据库连接、表结构、任务与事件保存 |
| 评测 / 回归 | [`evaluation.py`](app/evaluation.py)、[`tests/`](tests/) | 固定业务案例、边界与错误路径检查 |

V2 每个任务最多 5 次模型请求、8 次工具执行、60 秒，不自动重试。模型只能请求 `search_creators`、`quote_stats` 和 `search_knowledge`；不能执行任意 SQL、读文件或调用任意外部工具。事件逐步落库，当前页面不是流式输出，也不支持失败后从断点继续执行。

## 可选：接入真实 DeepSeek

**先把 MOCK 跑通。公开仓库没有 Key，也没有你本机的配置。**

1. 在项目根目录复制 `.env.example` 为 `.env`，仅在私有 `.env` 中填写 Key；不要覆盖已有配置。
2. 设置 `LLM_PROVIDER=deepseek`，并根据服务商当前文档确认 `DEEPSEEK_MODEL`。示例模型名是项目配置，不是对当前可用模型的保证。
3. macOS / Linux：V1 运行 `bash ./run.sh`；V2 必须显式运行 `bash ./run-agent-v2.sh --deepseek`。
4. Windows / 手动启动：在当前 PowerShell 设置 `LLM_PROVIDER`、`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 等环境变量，再运行对应的 uvicorn 命令。直接运行 uvicorn 不加载 `.env`；不要截图或共享含 Key 的命令与终端历史。

真实请求可能计费，费用由输入、输出 Token、调用次数及服务商价格决定。代码中的单价只是估算配置，不是账户余额或账单；未知用量不应视为零成本。当前没有账户级累计预算熔断。

[DeepSeek 官方 API 文档](https://api-docs.deepseek.com/zh-cn/) · [官方定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) · [V1 历史接口实测记录](docs/DEEPSEEK_TEST_CN.md)。V1 曾对三个真实模型入口做接口与格式抽样；这不是全量业务质量评测。V2 用受控 HTTP 响应验证协议，本次发布未做 V2 付费实测。

## 验证与能力边界

macOS / Linux：

```bash
.venv/bin/python -m pytest -q
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

本次发布检查（2026-10-04）：**116 个自动测试实例通过**，其中 V1 84 个、V2 32 个。另有 **20 个固定业务评测案例**（10 个匹配、10 个审核）；这与自动测试数量不是同一概念。检查过程和未验证范围见 [发布检查记录](docs/PUBLICATION_2026-10-04_CN.md)，历史复查见 [复查记录](docs/RECHECK_2026-10-04_CN.md)。

- JSON/schema 合格、来源 ID 属于资料库，都不代表结论真实或引文语义充分。
- 没有真实社媒抓取、网页浏览、真实发信、CRM 集成、登录或多租户权限。
- 没有模型训练、生产部署、账户级总预算控制或完整的真实模型质量评测。
- 输入修改会让 V1 旧候选选择、评分与草稿失效；旧内容审核不会自动按新 Brief 重跑。
- MOCK 结果只用于模拟。产品知识固定为示例，改品牌名称不会自动更新知识库。
- 只绑定 `127.0.0.1` 本地使用；不要直接把无认证服务暴露到公网。

## 学习与求职展示

建议顺序：**首页启动 → V1 演示 → V1 原理 → V2 演示 → V2 学习攻略 → 源码 → 测试与局限**。

- [V1 README](README_WORKFLOW_V1.md)：工作流功能与排查。
- [V2 README](README_AGENT_V2.md)：Agent 架构、工具与有界控制。
- [V1 面试问答](docs/INTERVIEW_QA_CN.md)、[V2 面试与讲稿](docs/AGENT_V2_DEMO_CN.md)：解释设计选择，避免把演示说成生产实绩。
- [GitHub 与简历参考](docs/GITHUB_AND_RESUME_CN.md)：项目描述模板；只有能自己解释、确实参与过的内容才能写入简历。
- [`docs/superpowers/`](docs/superpowers/)：历史设计与实现计划，不是启动必读材料。

这是 AI 辅助开发的个人学习与作品展示项目。展示时应按实际经历说明 AI 工具的使用、自己的理解和验证工作，不应将生成代码直接表述为已在公司生产环境独立交付的经历。

## 常见问题

| 现象 | 处理 |
|---|---|
| 缺少 `DEEPSEEK_API_KEY` | 先确认是否误用了真实模式；用首页显式 MOCK 命令启动，不需要 Key。 |
| 8000 / 8010 被占用 | 改 uvicorn 的 `--port`，并打开对应新端口；不用关闭其他不相关服务。 |
| 想做全新排练 | 停止服务，选择一个未使用的 DB_PATH 或 AGENT_V2_DB_PATH；不要删除已有数据库。路径已存在则会保留历史。 |
| 提示没有 FTS5 模块 | 使用带 FTS5 的 Python / SQLite 构建；不是安装一个 PyPI 包就能修复。 |
| 真实请求余额不足、超时或格式错误 | 查看应用安全错误摘要；先用 MOCK 排练。V1 最多一次校验重试，V2 不自动重试。 |
| 打开网页只有代码列表 | GitHub 托管的是源码；Python 后端需要在本机运行，仓库链接不是在线应用地址。 |

发布范围仅含源码、虚构数据、测试和说明。`.env`、运行数据库及 sidecar、虚拟环境、缓存、个人简历和本机教程站点没有上传。
